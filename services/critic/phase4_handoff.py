"""Reconcile/export the pinned Phase 4 DEV set, resuming only missing trace/arms.

Read-only git show of Phase 4 contracts; no merge, checkout, dataset rewrite or
task replay. The original calls.jsonl enforces the $1 cap including prior spend.
"""
from __future__ import annotations

import argparse
import builtins
from collections import Counter
import copy
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import types

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "sdk") not in sys.path:
    sys.path.insert(0, str(ROOT / "sdk"))

from services.critic.dev_adapter import dev_labels, dev_traces  # noqa: E402
from services.critic.detector_adapter import from_detector  # noqa: E402
from services.critic.leak_assert import assert_no_evidence_leaks  # noqa: E402
from services.critic.llm import DeepSeekProvider  # noqa: E402
from services.critic.round3_part_b import (  # noqa: E402
    OUT, Round3Ledger, baseline_config, git, run_experiment,
)
from services.critic.round2_specificity import MiniLMEmbeddings  # noqa: E402

ARMS = ("new", "v1_structured")
PHASE4 = "origin/phase-4-healing"
MAIN = "origin/main"


def source(ref, path):
    return subprocess.check_output(["git", "-c", f"safe.directory={ROOT.as_posix()}",
                                    "show", f"{ref}:{path}"], cwd=ROOT)


def read_records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def write_records(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix+".tmp")
    temporary.write_text("".join(json.dumps(r, ensure_ascii=False)+"\n" for r in records), encoding="utf-8")
    temporary.replace(path)


def reconcile_sets(sets, rows):
    failures = sets["failures"]
    if len(failures) != 59 or len({r["trace_id"] for r in failures}) != 59:
        raise ValueError("Expected 59 unique pre-registered Phase 4 failures")
    by_id = {r["trace_id"]: r for r in rows}
    checks, mismatches, selected = [], [], []
    for failure in failures:
        tid = failure["trace_id"]
        row = by_id.get(tid)
        differences = {}
        if row is None:
            differences["split"] = {"expected": "dev", "actual": "absent from DEV labels"}
        else:
            for field in ("task_id", "fault", "provider", "model", "family"):
                if failure.get(field) != row[field]:
                    differences[field] = {"expected": failure.get(field), "actual": row[field]}
            for field in ("v11_label", "selection_label"):
                if failure.get(field) != row["label"]:
                    differences[field] = {"expected": failure.get(field), "actual": row["label"]}
            if row["label"] != row["fault"] or row["split"] != "dev":
                differences["effective_dev_fault"] = {"label": row["label"], "fault": row["fault"], "split": row["split"]}
            selected.append(row)
        check = {"trace_id": tid, "preregistered_label": failure["v11_label"],
                 "main_label": row["label"] if row else None, "differences": differences}
        checks.append(check)
        if differences:
            mismatches.append(check)
    return selected, {"failures_checked": 59, "mismatch_count": len(mismatches),
                      "mismatches": mismatches, "checks": checks}


def partition_records(records, allowed):
    if len({(r["trace_id"], r["arm"]) for r in records}) != len(records):
        raise ValueError("Duplicate trace/arm in saved records")
    return ([r for r in records if r["trace_id"] in allowed],
            [r for r in records if r["trace_id"] not in allowed])


def contract_modules(ref=PHASE4):
    """Load the exact pure config/loader contracts with an isolated import hook."""
    modules = {}
    for short in ("config", "critic"):
        name = f"services.critic._phase4_contract_{short}"
        module = types.ModuleType(name)
        module.__file__ = f"git-show:{ref}:bench/heal/{short}.py"
        sys.modules[name] = module
        importer = builtins.__import__
        def isolated(name, globals=None, locals=None, fromlist=(), level=0, *, original=importer, lookup=modules):
            if name == "bench.heal.config":
                return lookup["config"]
            return original(name, globals, locals, fromlist, level)
        module.__dict__["__builtins__"] = {**vars(builtins), "__import__": isolated}
        exec(compile(source(ref, f"bench/heal/{short}.py"), module.__file__, "exec"), module.__dict__)
        modules[short] = module
    return modules["config"], modules["critic"]


def export_record(record, failure, config_contract, *, reused):
    result = copy.deepcopy(record)
    proposal = result.get("proposal")
    result.update(failure_id=failure["failure_id"], task_id=failure["task_id"],
                  evidence_mode="detector", reused_completed_record=reused,
                  eligible_phase4=True, completed=True)
    if proposal is None:
        result.update(source="not_generated", provenance=None, fix_tag="other_fix", deployable=False)
        result["no_proposal_reason"] = ("detector predicted NORMAL" if result.get("detector_type") == "NORMAL"
                                        else result.get("no_proposal_reason", "no proposal generated"))
        return result
    # Model output is preserved. Only reporting metadata is enriched. Phase 4
    # normalizes both prompt aliases to system_prompt and tags removed injected
    # segments, in addition to exact whole-value restoration.
    proposal.setdefault("phase3_exact_restore_tag", proposal.get("fix_tag"))
    try:
        patch = config_contract.from_phase3(proposal["target_component"], proposal["patch_content"])
        tag = config_contract.injection_tag(patch, failure["fault"])
        result["phase4_tag_reason"] = "Phase 4 config.injection_tag with normalized prompt aliases"
    except (ValueError, TypeError, KeyError) as exc:
        tag = "other_fix"
        result["phase4_tag_reason"] = f"inapplicable config: {exc}"
    proposal["fix_tag"] = tag
    result.update(source=proposal["provenance"]["source"], provenance=proposal["provenance"], fix_tag=tag,
                  deployable=proposal["provenance"]["source"] == "llm" and bool(result["c1_valid"]) and bool(result["dry_run_applied"]))
    return result


def prepare(output=OUT):
    output.mkdir(parents=True, exist_ok=True)
    labels_blob = source(MAIN, "data/nexusbench/labels.csv")
    if git("rev-parse", f"{MAIN}:data/nexusbench/labels.csv") != git("rev-parse", "bench-v1.1:data/nexusbench/labels.csv"):
        raise ValueError("origin/main labels do not match bench-v1.1")
    for path in ("data/nexusbench/labels.csv", "data/nexusbench/traces.jsonl", "bench/agent.py", "bench/tools.py"):
        if git("rev-parse", f"HEAD:{path}") != git("rev-parse", f"{MAIN}:{path}"):
            raise ValueError(f"Local benchmark differs from authoritative main: {path}")
    sets_blob = source(PHASE4, "reports/phase4/prereg_sets.json")
    sets = json.loads(sets_blob)
    rows, reconciliation = reconcile_sets(sets, list(dev_labels(io.StringIO(labels_blob.decode("utf-8")))))
    reconciliation.update(phase4_commit=git("rev-parse", PHASE4), main_commit=git("rev-parse", MAIN),
        labels_git_object=git("rev-parse", f"{MAIN}:data/nexusbench/labels.csv"),
        labels_sha256=hashlib.sha256(labels_blob).hexdigest(),
        prereg_sets_sha256=hashlib.sha256(sets_blob).hexdigest(),
        prereg_excluded=sets.get("excluded", []))
    reconciliation["loader_contract_sha256"] = {name: hashlib.sha256(source(PHASE4, f"bench/heal/{name}.py")).hexdigest()
                                                  for name in ("config", "critic")}
    # Also quantify the historical v1 selection-label mismatch without using it
    # for the current selection, or ever decoding TEST rows.
    # The original results selection was ignored/untracked at 7d95b15. Phase 4
    # committed its exact input copy alongside the preregistration.
    legacy = json.loads(source(PHASE4, "reports/phase4/phase3_selection.json"))
    reconciliation["legacy_selection_source"] = "origin/phase-4-healing:reports/phase4/phase3_selection.json"
    by_id = {r["trace_id"]: r for r in dev_labels(io.StringIO(labels_blob.decode("utf-8")))}
    reconciliation["legacy_selection_mismatches"] = [{"trace_id": r["trace_id"], "selection_label": r["label"],
        "main_label": by_id.get(r["trace_id"], {}).get("label")} for r in legacy["selection"]
        if r["trace_id"] not in by_id or r["label"] != by_id[r["trace_id"]]["label"]]
    (output / "phase4_reconciliation.json").write_text(json.dumps(reconciliation, indent=2)+"\n", encoding="utf-8")
    (output / "phase4_prereg_sets.json").write_bytes(sets_blob)
    if reconciliation["mismatch_count"]:
        raise ValueError("Phase 4 preregistered failures mismatch main; see reconciliation")
    from bench.detector_view import detector_view
    from bench.world import build_world
    from bench.tools import DRIFT_CUSTOMER
    traces = dev_traces(ROOT / "data/nexusbench/traces.jsonl", {r["trace_id"] for r in rows})
    saved = json.loads((ROOT / "results/phase2_dev_predictions.json").read_text(encoding="utf-8"))["predictions"]
    predictions = {tid: {"pred": saved[tid]["pred"]} for tid in traces}
    views = {tid: detector_view(t.model_dump(mode="json")) for tid, t in traces.items()}
    evidence = {tid: from_detector(predictions[tid], views[tid]) for tid in traces}
    leak = assert_no_evidence_leaks(evidence, views, output / "phase4_leak_assert.json",
        raw_canaries=tuple(u.canary for u in build_world().users), raw_drift_target=DRIFT_CUSTOMER)
    archive = output / "prior_selection"
    if not (archive / "preservation_manifest.json").exists():
        archive.mkdir(exist_ok=True)
        preserved = {}
        for name in ("new.jsonl", "v1_structured.jsonl", "original.jsonl", "summary.json", "protocol.json", "leak_assert.json"):
            path = output / name
            if path.exists():
                shutil.copy2(path, archive / name)
                preserved[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        (archive / "preservation_manifest.json").write_text(json.dumps(preserved, indent=2)+"\n", encoding="utf-8")
    config_contract, loader = contract_modules()
    failures = {r["trace_id"]: r for r in sets["failures"]}
    migration = {"phase4_failures": 59, "arms": {}, "prior_spend_usd": Round3Ledger(output / "calls.jsonl", "audit").spent}
    complete = {}
    for arm in (*ARMS, "original"):
        records = read_records(output / f"{arm}.jsonl")
        kept, excluded = partition_records(records, failures)
        excluded_path = output / "excluded" / f"{arm}.jsonl"
        previous_excluded = read_records(excluded_path)
        merged_excluded = {r["trace_id"]: r for r in previous_excluded}
        merged_excluded.update({r["trace_id"]: r for r in excluded})
        write_records(excluded_path, list(merged_excluded.values()))
        migration["arms"][arm] = {"kept": len(kept), "excluded": len(merged_excluded),
            "missing": len(failures)-len(kept), "kept_proposals": sum(r.get("proposal") is not None for r in kept)}
        if arm in ARMS:
            complete[arm] = [export_record(r, failures[r["trace_id"]], config_contract,
                reused=r.get("reused_completed_record", True)) for r in kept]
            # Reused evidence must satisfy the same actual-input invariant too.
            from services.critic.evidence import FailureEvidence
            reused_evidence = {r["trace_id"]: FailureEvidence.model_validate(r["evidence"]) if r.get("evidence") else None for r in kept}
            assert_no_evidence_leaks(reused_evidence, views, output / f"phase4_reused_leak_{arm}.json",
                raw_canaries=tuple(u.canary for u in build_world().users), raw_drift_target=DRIFT_CUSTOMER)
            write_records(output / f"{arm}.jsonl", complete[arm])
        else:
            write_records(output / f"{arm}.jsonl", [{**r, "eligible_phase4": False, "deployable": False,
                                                     "usage": "historical original arm; non-deployable"} for r in kept])
    manifest = output / "phase4_migration.json"
    if not manifest.exists():
        manifest.write_text(json.dumps(migration, indent=2)+"\n", encoding="utf-8")
    return sets, rows, traces, predictions, views, evidence, complete, leak, config_contract, loader


def finish(sets, output, config_contract, loader):
    failures = {r["trace_id"]: r for r in sets["failures"]}
    faults = {tid: f["fault"] for tid, f in failures.items()}
    loader_results = {}
    for arm in ARMS:
        records = read_records(output / f"{arm}.jsonl")
        records = [export_record(r, failures[r["trace_id"]], config_contract,
                                  reused=r.get("reused_completed_record", False)) for r in records]
        records.sort(key=lambda r: list(failures).index(r["trace_id"]))
        write_records(output / f"{arm}.jsonl", records)
        loaded = loader.load_round3(str(output / f"{arm}.jsonl"), arm, faults)
        for record in records:
            imported = loaded[record["trace_id"]]
            record["phase4_status"] = imported.status
            record["phase4_reason"] = imported.reason
            record["deployable"] = imported.status == "patch"
        write_records(output / f"{arm}.jsonl", records)
        loader_results[arm] = {"records": len(records), "proposals": sum(r["proposal"] is not None for r in records),
            "missing": sorted(set(failures)-set(loaded)), "statuses": dict(Counter(p.status for p in loaded.values()))}
    (output / "phase4_loader_validation.json").write_text(json.dumps(loader_results, indent=2)+"\n", encoding="utf-8")
    return loader_results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--env-file", default="C:/Umich/Projects/Nexus/.env")
    args = parser.parse_args()
    sets, rows, traces, predictions, views, evidence, completed, leak, cfg, loader = prepare()
    if args.prepare_only:
        print(json.dumps({"gate": leak["status"], "evidence_checked": leak["evidence_checked"],
                          "kept": {arm: len(r) for arm, r in completed.items()}}))
        return
    if git("status", "--porcelain", "--", "services/critic", "tests/unit/critic"):
        raise RuntimeError("Commit implementation before continuing generation")
    ledger = Round3Ledger(OUT / "calls.jsonl", git("rev-parse", "HEAD"))
    pending = {arm: len(rows)-len(completed[arm]) for arm in ARMS}
    if not any(pending.values()):
        result = finish(sets, OUT, cfg, loader)
        print(json.dumps({"status": "already_complete", "total_spend_usd": ledger.spent, "phase4": result}))
        return
    protocol_path = OUT / "phase4_continuation_protocol.json"
    if not protocol_path.exists():
        protocol_path.write_text(json.dumps({"implementation_commit": git("rev-parse", "HEAD"),
            "phase4_commit": git("rev-parse", PHASE4), "main_commit": git("rev-parse", MAIN),
            "trace_ids": [r["trace_id"] for r in rows], "arms": ARMS, "evidence_mode": "detector",
            "pending_trace_arm_pairs": pending, "starting_spend_usd": ledger.spent,
            "aggregate_cap_usd": 1.0, "leak_assert": leak, "destinations": ["https://api.deepseek.com/beta/chat/completions"],
            "oracle_arm": "not run", "source_ledger": "calls.jsonl"}, indent=2)+"\n", encoding="utf-8")
    # Only the pending trace/arm pairs are sent. The completed records, including
    # misses, fallback responses and rejected dry runs, are never regenerated.
    from bench.llm import load_env
    load_env(args.env_file)
    providers = {arm: DeepSeekProvider(ledger=ledger) for arm in ARMS}
    embedder = MiniLMEmbeddings()
    try:
        summary = run_experiment(rows, traces, predictions, views, evidence, legacy=None,
            providers=providers, ledger=ledger, config=baseline_config(), embedder=embedder,
            output=OUT, arms=ARMS, completed=completed)
    finally:
        result = finish(sets, OUT, cfg, loader)
    print(json.dumps({"status": summary["status"], "total_spend_usd": ledger.spent, "phase4": result}))


if __name__ == "__main__":
    main()
