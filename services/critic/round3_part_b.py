"""Part B: merged main or the explicitly authorized rebased phase-3-critic branch.

python -m services.critic.round3_part_b [--env-file PATH]
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import statistics

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "sdk") not in sys.path:
    sys.path.insert(0, str(ROOT / "sdk"))

from nexus_agent.models import Alert  # noqa: E402
from services.critic.accounting import BudgetExceeded, CostLedger  # noqa: E402
from services.critic.c3 import score_c3, summarize_c3  # noqa: E402
from services.critic.detector_adapter import critic_view, from_detector  # noqa: E402
from services.critic.dev_adapter import CLASSES, dev_labels, dev_traces  # noqa: E402
from services.critic.experiments import interval, select_labels  # noqa: E402
from services.critic.graph import run_critic  # noqa: E402
from services.critic.fault_reversal import snapshots, tag_fix  # noqa: E402
from services.critic.hardening import inspect_patch  # noqa: E402
from services.critic.leak_assert import assert_no_evidence_leaks  # noqa: E402
from services.critic.llm import DeepSeekProvider  # noqa: E402
from services.critic.proposal import CriticProposal  # noqa: E402
from services.critic.registry import ConfigRegistry  # noqa: E402
from services.critic.round2 import Store  # noqa: E402
from services.critic.round2_legacy import OriginalCritic  # noqa: E402
from services.critic.round2_providers import OriginalDeepSeek  # noqa: E402
from services.critic.round2_specificity import (  # noqa: E402
    COSINE_THRESHOLD, EMBED_MODEL, EMBED_REVISION, MiniLMEmbeddings,
    distinctness, evidence_anchors, grounding,
)
from services.critic.scoring_truth import truth_from_dev  # noqa: E402

ARMS = ("original", "v1_structured", "new")
OUT = ROOT / "reports/phase3/round3"


def git(*args):
    return subprocess.check_output(["git", "-c", f"safe.directory={ROOT.as_posix()}", *args],
                                   cwd=ROOT, text=True, encoding="utf-8").rstrip("\r\n")


def preflight():
    branch = git("branch", "--show-current")
    if branch not in {"main", "phase-3-critic"}:
        raise RuntimeError("Part B requires main or the authorized rebased phase-3-critic branch")
    if branch == "phase-3-critic":
        git("merge-base", "--is-ancestor", "origin/main", "HEAD")
    dirty = git("status", "--porcelain")
    if any(not line[3:].startswith("reports/phase3/") for line in dirty.splitlines()):
        raise RuntimeError("Commit code before Part B; only report artifacts may be dirty")
    for path in ("data/nexusbench/traces.jsonl", "data/nexusbench/labels.csv"):
        if git("rev-parse", f"HEAD:{path}") != git("rev-parse", f"bench-v1.1:{path}"):
            raise RuntimeError(f"Expected unchanged bench-v1.1 object: {path}")
    if (OUT / "protocol.json").exists():
        raise RuntimeError("Part B already started; refusing overwrite or unbudgeted rerun")


class Round3Ledger(CostLedger):
    """Separate, persistent aggregate $1 budget. Unknown calls retain reservations."""
    def __init__(self, path, commit):
        super().__init__(path, cap_usd=1.0)
        self.lock = threading.RLock()
        self.commit = commit
        self.arm = "preflight"

    def append(self, row):
        with self.lock:
            if row.get("status") == "reserved":
                self.check(row["cost_usd"])
            super().append({**row, "arm": self.arm, "git_commit": self.commit,
                            "evidence_mode": "detector"})


def baseline_config():
    # Same deployment snapshot for every trace. Never choose a prompt based on
    # label['fault'] or injection config, as round 2's oracle snapshot did.
    from bench import agent
    return {"_BASE_SYSTEM": agent._BASE_SYSTEM, "MAX_STEPS": agent.MAX_STEPS,
            "TOOL_SPECS": copy.deepcopy(agent.TOOL_SPECS)}


def load_inputs():
    from bench.detector_view import detector_view
    rows = select_labels(list(dev_labels(ROOT / "data/nexusbench/labels.csv")))
    traces = dev_traces(ROOT / "data/nexusbench/traces.jsonl", {r["trace_id"] for r in rows})
    saved = json.loads((ROOT / "results/phase2_dev_predictions.json").read_text(encoding="utf-8"))
    # Deliberately project pred only; label_v1, source model, judge and injection
    # information cannot enter detector/critic inputs via saved result records.
    predictions = {tid: {"pred": saved["predictions"][tid]["pred"]} for tid in traces}
    views = {tid: detector_view(t.model_dump(mode="json")) for tid, t in traces.items()}
    evidence = {tid: from_detector(predictions[tid], views[tid]) for tid in traces}
    return rows, traces, predictions, views, evidence


def metrics(records, vectors):
    def block(indices):
        rows = [records[i] for i in indices]
        generated = [i for i in indices if records[i]["proposal"] is not None]
        llm_only = [i for i in generated if records[i]["proposal"]["provenance"]["source"] == "llm"]
        valid = [r for r in rows if r["c1_valid"]]
        latency = [r["wall_latency_ms"] for r in rows if r.get("wall_latency_ms") is not None]
        costs = sum(r["proposal"]["provenance"]["cost_usd"] for r in rows if r["proposal"])
        return {"selected_dev_failures": len(rows), "proposals": len(generated),
            "detector_misses": sum(r["detector_type"] == "NORMAL" for r in rows),
            "no_op_rejections": sum(r["proposal"]["no_op_patch"] for r in rows if r["proposal"]),
            "bad_reference_rejections": sum(bool(r["proposal"]["bad_references"]) for r in rows if r["proposal"]),
            "fix_tags": {tag: interval(sum(r["proposal"]["fix_tag"] == tag for r in rows if r["proposal"]), len(generated))
                         for tag in ("reverts_injection", "other_fix")},
            "latency_p50_ms": statistics.median(latency) if latency else None,
            "cost_usd": costs, "cost_per_proposal_usd": costs/len(generated) if generated else None,
            "C1_over_generated": interval(sum(r["c1_valid"] for r in rows), len(generated)),
            "C1_pipeline_coverage": interval(len(valid), len(rows)),
            "C2": interval(sum(r["dry_run_applied"] for r in valid), len(valid)),
            "fallback": interval(len(generated)-len(llm_only), len(generated)),
            "specificity_all_sources": distinctness([records[i]["proposal"]["patch_content"] for i in generated],
                                                    vectors[generated]),
            "specificity_llm_only": distinctness([records[i]["proposal"]["patch_content"] for i in llm_only],
                                                 vectors[llm_only]),
            "grounding_proxy": {"validated": False, "used_for_comparisons": False,
                                "review_kappa_sensitivity": [.20, .03225806451612906]},
            "C3": summarize_c3([r["c3"] for r in rows])}
    return {"overall": block(list(range(len(records)))),
            "per_class": {ft: block([i for i, r in enumerate(records) if r["failure_type"] == ft])
                          for ft in CLASSES}}


def run_experiment(rows, traces, predictions, views, evidence, *, legacy, providers,
                   ledger, config, embedder, output):
    """Injected dependencies keep runner tests entirely offline and fixture-based."""
    import numpy as np
    records = {arm: [] for arm in ARMS}
    status = "complete"
    error = None
    try:
        # Round-robin arms: a cap stop does not spend everything on the first arm.
        for row in rows:
            tid = row["trace_id"]
            for arm in ARMS:
                ledger.arm = arm
                ev, view = evidence[tid], critic_view(views[tid])
                before = {r["call_id"] for r in ledger.rows()}
                started = time.perf_counter()
                proposal, valid, applied = None, False, False
                if ev is not None:
                    provider = providers[arm]
                    alert = Alert(trace_id=view.trace_id, agent_name=view.agent_name,
                                  failure_type=predictions[tid]["pred"])
                    store = Store({view.trace_id: view})
                    if arm == "original":
                        provider.trace_id, provider.call_index = view.trace_id, 0
                        p, fallback, attempts = legacy.run(alert, store, provider)
                        valid = not fallback and bool(attempts) and attempts[-1]["passed"]
                        checks = inspect_patch(p, config)
                        rejection_reasons = []
                        try:
                            ConfigRegistry(config).apply(p)
                            applied = valid
                        except (ValueError, TypeError) as exc:
                            rejection_reasons.append(str(exc))
                        prov = provider.last_provenance.model_copy(update={
                            "source": "fallback" if fallback else "llm",
                            "prompt_hashes": legacy.hashes})
                        proposal = CriticProposal.model_validate({**p.model_dump(mode="json"),
                            "critic_arm": "original", "provenance": prov,
                            "no_op_patch": checks.no_op, "bad_references": checks.bad_references,
                            "rejection_reasons": rejection_reasons,
                            "valid_without_fallback": valid, "dry_run_applied": applied})
                    else:
                        proposal = run_critic(alert, store, llm_factory=lambda chosen=provider, **_: chosen,
                            evidence=ev, current_config=config, config={"critic_arm": arm})
                        valid, applied = proposal.valid_without_fallback, proposal.dry_run_applied
                calls = [r for r in ledger.rows() if r["call_id"] not in before]
                if proposal:
                    proposal.provenance.cost_usd = sum(c["cost_usd"] for c in calls)
                    for field in ("input_tokens", "output_tokens", "latency_ms"):
                        values = [c.get(field) for c in calls]
                        setattr(proposal.provenance, field, sum(values) if all(v is not None for v in values) else None)
                # Scoring happens after generation; raw traces and labels never enter Store.
                wall_latency_ms = (time.perf_counter()-started)*1000 if proposal else None
                if proposal:
                    injected, clean = snapshots(row)
                    tag = tag_fix(proposal, injected, clean)
                    proposal.fix_tag = tag["fix_tag"]
                    proposal.clean_config_diff = tag["clean_config_diff"]
                truth = truth_from_dev(row, traces[tid])
                anchors = evidence_anchors(ev) if ev is not None else {}
                record = {"trace_id": tid, "view_id": view.trace_id, "arm": arm,
                    "failure_type": row["label"], "detector_type": predictions[tid]["pred"],
                    "evidence_mode": "detector", "evidence": ev.model_dump(mode="json") if ev else None,
                    "proposal": proposal.model_dump(mode="json") if proposal else None,
                    "c1_valid": valid, "dry_run_applied": applied,
                    "wall_latency_ms": wall_latency_ms,
                    "grounding_proxy_unvalidated": grounding(proposal.patch_content, anchors) if proposal else None,
                    "c3": score_c3(proposal, truth, detector_type=predictions[tid]["pred"]),
                    "scoring_truth": truth.model_dump(mode="json"),
                    "call_ids": [c["call_id"] for c in calls]}
                records[arm].append(record)
                with (output / f"{arm}.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(record, ensure_ascii=False)+"\n")
    except BudgetExceeded:
        status = "budget_stopped"
    except Exception as exc:
        status, error = "failed", type(exc).__name__
        raise
    finally:
        summary = {"status": status, "error": error, "cap_usd": 1.0, "accounted_usd": ledger.spent,
                   "selected": len(rows), "arms": {}}
        for arm, arm_records in records.items():
            # Empty strings maintain row alignment for detector misses (excluded
            # from proposal specificity denominators).
            texts = [r["proposal"]["patch_content"] if r["proposal"] else "" for r in arm_records]
            vectors, _ = embedder.encode(texts) if texts else (np.zeros((0, 384)), [])
            summary["arms"][arm] = metrics(arm_records, vectors)
            # Include costs of interrupted proposals as well as completed ones.
            accounted = sum(c["cost_usd"] for c in ledger.rows() if c.get("arm") == arm)
            n = summary["arms"][arm]["overall"]["proposals"]
            summary["arms"][arm]["overall"].update(cost_usd=accounted,
                cost_per_proposal_usd=accounted/n if n else None)
        (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    preflight()
    rows, traces, predictions, views, evidence = load_inputs()
    from bench.tools import DRIFT_CUSTOMER
    from bench.world import build_world
    leak_audit = assert_no_evidence_leaks(evidence, views, OUT / "leak_assert.json",
        raw_canaries=tuple(u.canary for u in build_world().users), raw_drift_target=DRIFT_CUSTOMER)
    legacy, embedder, config = OriginalCritic(), MiniLMEmbeddings(), baseline_config()
    commit = git("rev-parse", "HEAD")
    OUT.mkdir(parents=True, exist_ok=True)
    protocol = {"implementation_commit": commit, "bench_revision": git("rev-parse", "bench-v1.1"),
        "date_utc": datetime.now(timezone.utc).isoformat(), "arms": ARMS, "cap_usd": 1.0,
        "seed": 20261110, "selection": [{"trace_id": r["trace_id"], "class": r["label"]} for r in rows],
        "trace_sha256": {tid: hashlib.sha256(t.model_dump_json().encode()).hexdigest() for tid, t in traces.items()},
        "prediction_source_sha256": hashlib.sha256((ROOT / "results/phase2_dev_predictions.json").read_bytes()).hexdigest(),
        "detector_view_sha256": hashlib.sha256((ROOT / "bench/detector_view.py").read_bytes()).hexdigest(),
        "original_source_sha256": legacy.hashes, "config": config,
        "evidence_mode": "detector", "oracle_enabled": False,
        "leak_assert": leak_audit,
        "hardening": "reject exact no-ops and explicit unregistered tool/argument references",
        "fix_tag": "scoring only: exact restoration of changed injected config leaves against clean snapshot",
        "embedding": {"model": EMBED_MODEL, "revision": EMBED_REVISION, "threshold": COSINE_THRESHOLD},
        "C3": "proposal_type_match compares the proposal label; type_match scores independent diagnosis only; explicit citations; unknown truth locations excluded and counted",
        "config_limit": "common baseline deployment snapshot; injected active prompt not inferred from labels",
        "miss_policy": "NORMAL predictions produce no proposal; retained in C3 and pipeline coverage",
        "execution": "sequential calls, round-robin arms; no task replay; no TEST deserialization"}
    # Exclusive creation locks out duplicate invocations, including partial/capped runs.
    with (OUT / "protocol.json").open("x", encoding="utf-8") as stream:
        json.dump(protocol, stream, indent=2)
    if args.env_file:
        from bench.llm import load_env
        load_env(str(args.env_file))
    ledger = Round3Ledger(OUT / "calls.jsonl", commit)
    providers = {"original": OriginalDeepSeek(ledger),
                 "v1_structured": DeepSeekProvider(ledger=ledger), "new": DeepSeekProvider(ledger=ledger)}
    summary = run_experiment(rows, traces, predictions, views, evidence, legacy=legacy,
        providers=providers, ledger=ledger, config=config, embedder=embedder, output=OUT)
    print(json.dumps({"status": summary["status"], "spend_usd": ledger.spent,
                      "summary": str(OUT / "summary.json")}))


if __name__ == "__main__":
    main()
