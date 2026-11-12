"""Offline report/verification of the reconciled Phase 4 critic handoff. No LLM calls."""
from collections import Counter
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "sdk")]

from services.critic.c3 import GroundTruth, score_c3  # noqa: E402
from services.critic.dev_adapter import CLASSES, dev_labels, dev_traces  # noqa: E402
from services.critic.evidence import FailureEvidence  # noqa: E402
from services.critic.experiments import interval  # noqa: E402
from services.critic.leak_assert import assert_no_evidence_leaks  # noqa: E402
from services.critic.phase4_handoff import ARMS, OUT, contract_modules, read_records, source  # noqa: E402


def fraction(value):
    k, n = value["successes"], value["total"]
    return f"{k}/{n} ({100*k/n:.1f}%)" if n else "0/0 (N/A)"


def main():
    from bench.detector_view import detector_view
    from bench.tools import DRIFT_CUSTOMER
    from bench.world import build_world
    summary = json.loads((OUT / "summary.json").read_text(encoding="utf-8"))
    assert summary["selected"] == 59 and set(summary["arms"]) == set(ARMS)
    sets = json.loads((OUT / "phase4_prereg_sets.json").read_text(encoding="utf-8"))
    reconciliation = json.loads((OUT / "phase4_reconciliation.json").read_text(encoding="utf-8"))
    migration = json.loads((OUT / "phase4_migration.json").read_text(encoding="utf-8"))
    loader_check = json.loads((OUT / "phase4_loader_validation.json").read_text(encoding="utf-8"))
    protocol = json.loads((OUT / "phase4_continuation_protocol.json").read_text(encoding="utf-8"))
    gate = json.loads((OUT / "phase4_leak_assert.json").read_text(encoding="utf-8"))
    failures = {f["trace_id"]: f for f in sets["failures"]}
    labels = {r["trace_id"]: r for r in dev_labels(io.StringIO(source(reconciliation["main_commit"], "data/nexusbench/labels.csv").decode("utf-8")))}
    traces = dev_traces(ROOT / "data/nexusbench/traces.jsonl", set(failures))
    views = {tid: detector_view(t.model_dump(mode="json")) for tid, t in traces.items()}
    records = {arm: read_records(OUT / f"{arm}.jsonl") for arm in ARMS}
    events = read_records(OUT / "calls.jsonl")
    calls = {r["call_id"]: r for r in events}
    total = sum(r["cost_usd"] for r in calls.values())
    assert total <= 1.0 and all(r["status"] == "settled" for r in calls.values())
    preserved = json.loads((OUT / "prior_selection/preservation_manifest.json").read_text())
    assert all(hashlib.sha256((OUT / "prior_selection" / name).read_bytes()).hexdigest() == digest
               for name, digest in preserved.items())
    _, loader = contract_modules(reconciliation["phase4_commit"])
    report = {"status": summary["status"], "main_commit": reconciliation["main_commit"],
        "phase4_commit": reconciliation["phase4_commit"], "generation_commit": protocol["implementation_commit"],
        "all_prior_files_preserved": True, "duplicate_exports": 0, "reused_outputs_changed": 0,
        "calls_resent_for_kept_pairs": 0, "real_leaks_remaining": 0,
        "total_spend_usd": total, "previous_spend_usd": migration["prior_spend_usd"],
        "additional_spend_usd": total-migration["prior_spend_usd"], "arms": {}}
    model_fields = ("patch_type", "target_component", "explanation", "patch_content", "confidence",
                    "estimated_impact", "root_cause_analysis", "diagnosed_failure_type", "cited_span_id", "cited_step", "provenance")
    for arm in ARMS:
        rows = records[arm]
        assert len({r["trace_id"] for r in rows}) == len(rows)
        assert all(r["trace_id"] in failures and r["arm"] == arm and r["evidence_mode"] == "detector" for r in rows)
        assert all(r["failure_type"] == labels[r["trace_id"]]["label"] for r in rows)
        assert all(score_c3(r["proposal"], GroundTruth.model_validate(r["scoring_truth"]), detector_type=r["detector_type"]) == r["c3"] for r in rows)
        input_evidence = {r["trace_id"]: FailureEvidence.model_validate(r["evidence"]) if r["evidence"] else None for r in rows}
        assert_no_evidence_leaks(input_evidence, views, OUT / f"phase4_export_leak_{arm}.json",
            raw_canaries=tuple(u.canary for u in build_world().users), raw_drift_target=DRIFT_CUSTOMER)
        originals = {r["trace_id"]: r for r in read_records(OUT / "prior_selection" / f"{arm}.jsonl")}
        kept = set(originals) & set(failures)
        kept_views = {originals[tid]["view_id"] for tid in kept}
        continued_calls = [r for r in calls.values() if r["arm"] == arm and r.get("git_commit") == protocol["implementation_commit"]]
        assert not any(r["trace_id"] in kept_views for r in continued_calls)
        for r in rows:
            if r["trace_id"] in kept:
                before = originals[r["trace_id"]]["proposal"]
                after = r["proposal"]
                assert (before is None) == (after is None)
                if before:
                    assert all(before.get(k) == after.get(k) for k in model_fields)
                assert r["call_ids"] == originals[r["trace_id"]]["call_ids"]
            if r["proposal"]:
                assert r["source"] == r["proposal"]["provenance"]["source"]
                assert r["provenance"] == r["proposal"]["provenance"]
                assert r["fix_tag"] == r["proposal"]["fix_tag"] in {"reverts_injection", "other_fix"}
        imported = loader.load_round3(str(OUT/f"{arm}.jsonl"), arm, {tid:f["fault"] for tid,f in failures.items()})
        assert Counter(p.status for p in imported.values()) == Counter(loader_check[arm]["statuses"])
        group = summary["arms"][arm]
        for name, pool in [("overall", rows), *[(ft, [r for r in rows if r["failure_type"] == ft]) for ft in CLASSES]]:
            block = group["overall"] if name == "overall" else group["per_class"][name]
            generated = [r for r in pool if r["proposal"]]
            block["fix_tags"] = {tag: interval(sum(r["fix_tag"] == tag for r in generated),len(generated))
                                 for tag in ("reverts_injection", "other_fix")}
        generated = [r for r in rows if r["proposal"]]
        cost = sum(r["proposal"]["provenance"]["cost_usd"] for r in generated)
        report["arms"][arm] = {"records": len(rows), "proposals": len(generated), "kept": len(kept),
            "new_records": len(rows)-len(kept), "excluded": migration["arms"][arm]["excluded"],
            "missing": sorted(set(failures)-{r["trace_id"] for r in rows}),
            "loader_statuses": dict(Counter(p.status for p in imported.values())),
            "retained_proposal_cost_usd": cost, "retained_cost_per_proposal_usd": cost/len(generated) if generated else None,
            "all_arm_cost_including_excluded_usd": sum(r["cost_usd"] for r in calls.values() if r["arm"] == arm),
            "continuation_calls": len(continued_calls)}
    summary["fix_tag_rule"] = "Phase 4 config.injection_tag, including normalized prompt aliases and removed injected segments"
    summary["grounding_proxy"] = {"validated": False, "used_for_comparisons": False, "review_kappa": [.20, .03225806451612906]}
    (OUT / "phase4_summary.json").write_text(json.dumps(summary, indent=2)+"\n", encoding="utf-8")
    (OUT / "phase4_verification.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    report_path = ROOT / "reports/phase3/round3.md"
    archived_report = OUT / "prior_selection/round3_before_phase4.md"
    if not archived_report.exists():
        shutil.copy2(report_path, archived_report)
    lines = ["# Phase 3 round 3: Phase 4 detector-evidence handoff", "",
        f"**Status: {summary['status']}.** The authoritative set is the 59 pre-registered Phase 4 failures, checked against origin/main's bench-v1.1 labels. Only `new` and `v1_structured`, with DETECTOR evidence, are exported for Phase 4. No oracle arm was run.", "",
        "## Failure-set reconciliation and preservation", "",
        f"Read `reports/phase4/prereg_sets.json` and `bench/heal/{{critic,config}}.py` by git show at `{reconciliation['phase4_commit']}`; no checkout or merge. Compared all 59 against origin/main `{reconciliation['main_commit']}`, whose labels Git object matches bench-v1.1. **0 mismatches** in the 59, including label, split, task, fault, provider/model and family checks.", "",
        "The legacy 60-row selection contains one stale row: `nb-b88ecbb93f704868`, PLAN_DRIFT in the selection, NORMAL in main. Phase 4 excludes it. The authoritative set has 12 HALLUCINATION, 12 TOOL_MISFIRE, 12 CONTEXT_BLEED, 11 PLAN_DRIFT and 12 LOOP_DETECTED failures. The legacy selection content is read from Phase 4's committed input copy; it was not tracked at 7d95b15.", "",
        "The previous run had already finished before the stop request, so no active generation remained. All prior files are preserved byte-for-byte in [prior_selection](round3/prior_selection/preservation_manifest.json). Out-of-set records are in `round3/excluded/`, unused. The original arm is historical and explicitly non-deployable; its 33 in-set and 27 excluded records are retained, and no more original-arm calls were made.", "",
        "| Detector arm | Kept completed records | Excluded records | Additional records | Final records | Proposals |",
        "|---|---:|---:|---:|---:|---:|"]
    for arm in ARMS:
        b=report["arms"][arm]
        lines.append(f"| {arm} | {b['kept']} | {b['excluded']} | {b['new_records']} | {b['records']} | {b['proposals']} |")
    lines += ["", "Completed misses, fallbacks and rejected proposals were kept, not resent. Verification found **0 calls for already completed trace/arm pairs**, no duplicate exports, and no changes to kept model outputs, provenance or call IDs. Reporting-only tags were normalized for Phase 4, with the original tag preserved as `phase3_exact_restore_tag`. See [reconciliation](round3/phase4_reconciliation.json), [migration](round3/phase4_migration.json), and [verification](round3/phase4_verification.json).", "",
        "## Corrected leak gate", "",
        "The initial injection-text ban was mis-specified and was corrected before any LLM call in commit fd80793. All 27 prior hits are verbatim observed text: 12 loop messages, 9 misfire errors and 6 drift notes (33 pattern matches). [The 27-hit diagnosis](leak_gate_diagnosis.md) lists the pattern, evidence field and detector-view match for each.", "",
        f"On the authoritative 59 inputs, the corrected gate checked **{gate['evidence_checked']} evidence objects and {gate['string_values_checked']} wire string values, with 0 real leaks**. Two detector misses produce no evidence. Reused packets and final exported packets also pass. Every evidence string, including the complete supporting span excerpt, is a literal substring of its official canonical detector_view serialization; embedded JSON is checked for prohibited keys and label values. Raw registry canaries and the raw drift target are forbidden. Observed notes/loading/errors are preserved, not redacted.", "",
        "Detector labels remain outside FailureEvidence in the Alert/prompt context; the evidence label field is null and contains no authored localization prose. Ground-truth labels, ownership/injection metadata and the raw injection registry never enter critic inputs. The registry is read only by the privileged checker/scorer. See [59-input assertion](round3/phase4_leak_assert.json) and final `phase4_export_leak_<arm>.json` assertions.", "",
        "## Arm table", "",
        "C1 is schema/validator validity without fallback over generated proposals. C2 is a successful hardened config-copy dry run among C1-valid proposals. Phase 4's loader adds its own deployed-config checks. These are mechanical checks, not evidence of repair. Exact/near specificity below sums within-class unique strings/components; near uses pinned MiniLM, chunk pooling and cosine >=0.9, with transitive components. Fallbacks are included; LLM-only and per-class results are in JSON.", "",
        "| Metric | New | v1 structured |", "|---|---:|---:|"]
    def add(label, values):
        lines.append("| "+label+" | "+" | ".join(values)+" |")
    overall = {a: summary["arms"][a]["overall"] for a in ARMS}
    add("C1", [fraction(overall[a]["C1_over_generated"]) for a in ARMS])
    add("C2 (conditional on C1)", [fraction(overall[a]["C2"]) for a in ARMS])
    for label,key in [("No-op rejections","no_op_rejections"),("Bad-reference rejections","bad_reference_rejections")]:
        add(label,[str(overall[a][key]) for a in ARMS])
    add("Fallbacks",[fraction(overall[a]["fallback"]) for a in ARMS])
    for label,key in [("Exact distinct (within class)","exact_unique"),("Near-distinct components (within class)","near_components")]:
        values=[]
        for a in ARMS:
            blocks=[b["specificity_all_sources"] for b in summary["arms"][a]["per_class"].values()]
            values.append(f"{sum(b[key] for b in blocks)}/{sum(b['n'] for b in blocks)}")
        add(label,values)
    add("Grounded string-match proxy",["UNVALIDATED; not used"]*2)
    for label,key in [("C3 proposal/envelope type match","proposal_type_match"),("C3 independent diagnosis type match","type_match"),("C3 strict step/span match","step_span_match")]:
        add(label,[fraction(overall[a]["C3"]["overall"][key]) for a in ARMS])
    add("p50 latency (seconds)",[f"{overall[a]['latency_p50_ms']/1000:.3f}" for a in ARMS])
    add("Cost attributable to retained proposals",[f"${report['arms'][a]['retained_proposal_cost_usd']:.9f}" for a in ARMS])
    add("Dollars per retained proposal",[f"${report['arms'][a]['retained_cost_per_proposal_usd']:.6f}" for a in ARMS])
    lines += ["", "Latency includes calls/retries and graph work, before scoring/embedding. Cost in the table is attributed to retained exported proposals; total authorized spend below ALSO includes excluded and original-arm history. No-op and bad-reference counts concern returned proposals; counts may overlap other rejection causes. Arbitrary natural-language semantics/dynamic tool dispatch are not proven safe by the deterministic reference grammar.", "",
        "Both arms use deepseek-flash, temperature 0.2, a maximum of 800 output tokens per call, and disabled thinking. v1_structured makes a structured diagnosis call followed by a structured patch call; new makes the structured patch call directly. Per-call usage, managed model versions/fingerprints and all retries are logged. Retained records span the initial and continuation batches; no model response was regenerated to improve a score.", "",
        "## C3 per class and detector-wrong split", "",
        "The envelope type is inherited from the detector and is not an independent diagnosis. The independent type is explicitly returned by the critic. Exact citation scoring uses zero-based positions in full_trace.spans, not actor-step numbers. A conflicting span/index fails. Truth conventions: final-answer root for hallucination, original tool error for misfire, first foreign memory read for bleed, first executed injected-target call for drift, and third repeated successful call for loop. These are operational origin conventions, not causal proof. Missing/fallback diagnoses fail; detector misses remain in pipeline denominators.", ""]
    for title,key in [("Independent diagnosis type match","type_match"),("Strict step/span match","step_span_match"),("Proposal/envelope type match (detector propagation)","proposal_type_match")]:
        lines += [f"### {title}","","| Class | New | v1 structured |","|---|---:|---:|"]
        for ft in CLASSES:
            add(ft,[fraction(overall[a]["C3"]["per_class"][ft][key]) for a in ARMS])
        lines.append("")
    lines += ["", "### Detector-wrong split", "", "Each cell is independent type match / strict step match; each has the shown common denominator.", "", "| Class | New | v1 structured |", "|---|---:|---:|"]
    for ft in CLASSES:
        values=[]
        for a in ARMS:
            b=overall[a]["C3"]["detector_wrong"]["per_class"][ft]
            values.append(f"{b['type_match']['successes']}/{b['n']} / {b['step_span_match']['successes']}/{b['n']}" if b["n"] else "N/A (no detector errors)")
        add(ft,values)
    lines += ["", "The only detector errors in this set are the two CONTEXT_BLEED traces predicted NORMAL. They have no critic call and count as misses in pipeline C3; there are no wrong-class alerted traces on which to measure a critic correcting the detector's class."]
    lines += ["", "## Reporting-only fault-reversal tags", "",
        "The exported fix_tag uses the exact Phase 4 config.injection_tag contract: normalize _BASE_SYSTEM and _GUESS_SYSTEM to system_prompt, compare with clean/deployed config, and tag restoration or removal of an injected string segment as reverts_injection. This differs from the earlier exact-key/whole-value-only Phase 3 tag; that value is retained in phase3_exact_restore_tag. Tags are computed after generation and never exposed to the critic. Other injectors alter backend/runtime data rather than this config. other_fix is a category, not proof of a valid or effective fix. Each cell is reverts_injection / other_fix, over returned proposals.", "",
        "| Class | New | v1 structured |", "|---|---:|---:|"]
    for ft in CLASSES:
        add(ft,[f"{summary['arms'][a]['per_class'][ft]['fix_tags']['reverts_injection']['successes']} / {summary['arms'][a]['per_class'][ft]['fix_tags']['other_fix']['successes']}" for a in ARMS])
    lines += ["", "## Phase 4 loader validation", "", "Validated with the actual loader read from the pinned Phase 4 commit; no Phase 4 agent execution or healing run occurred. Each JSONL has the expected trace_id, arm, evidence_mode, proposal, c1_valid and dry_run_applied fields, plus top-level and nested source/provenance/tag metadata. Detector misses are explicit no-proposal records. Fallbacks and failed dry runs remain no_patch, never fabricated successes.", "",
        "| Arm | Loader patch | Loader no_patch | Loader inapplicable | Missing records |", "|---|---:|---:|---:|---:|"]
    for a in ARMS:
        b=report["arms"][a]; c=b["loader_statuses"]
        lines.append(f"| {a} | {c.get('patch',0)} | {c.get('no_patch',0)} | {c.get('inapplicable',0)} | {len(b['missing'])} |")
    lines += ["", "The common critic registry is a baseline snapshot, not a label-selected injected prompt. Phase 4 maps prompt aliases onto the deployed config and makes its own applicability decision. Proposals were not regenerated to improve applicability, and no winner is selected.", "",
        "## Proxy status, spend and validation", "",
        "The literal grounded proxy is **UNVALIDATED**, with review kappa **0.20 / 0.03** when unclear is treated as ungrounded/grounded. It is not aggregated or used for arm comparisons. Review was model-reviewed and author-confirmed, revised after feedback, not independent human validation. Historical review agreement is diagnostic only.", "",
        f"**Total accounted spend: ${total:.9f} / $1.00**, including ${migration['prior_spend_usd']:.9f} already spent before alignment. Additional spend: ${report['additional_spend_usd']:.9f}. All {len(calls)} calls are settled; no reservation is unresolved. Excluded and original-arm costs remain in this total. No new original or oracle calls were made.", "",
        "| Active arm | All arm spend including excluded history | Retained-proposal attributable spend |", "|---|---:|---:|"]
    for a in ARMS:
        b=report["arms"][a]
        lines.append(f"| {a} | ${b['all_arm_cost_including_excluded_usd']:.9f} | ${b['retained_proposal_cost_usd']:.9f} |")
    original_cost=sum(c["cost_usd"] for c in calls.values() if c["arm"] == "original")
    lines += ["", f"Historical original-arm spend: ${original_cost:.9f}. Dollar accounting uses the existing conservative token-rate/reservation ledger, not an independently reconciled wallet statement. Source calls, commits and per-proposal call IDs remain auditable in calls.jsonl. Explicit API egress approval covered synthetic DEV data sent to DeepSeek, with the same aggregate cap.", "",
        "CI command `pytest tests/unit/ tests/e2e/ -v`: **347 passed, 1 existing auxiliary provenance skip**, including both TEST-integrity tests. Ruff clean. Tests cover main-label reconciliation, stream gating, trace/arm idempotence, no-op/reference checks, corrected leak checks, and the actual Phase 4 loader. [CI log](phase4_handoff_ci.log). TEST data was used only by the previously authorized integrity/CI checks, not critic selection/generation. No Docker, push, merge, tags, task replay or dataset edits occurred.", "",
        f"Handoff implementation commit: `{protocol['implementation_commit']}`. Original generation commit: `{json.loads((OUT/'prior_selection/protocol.json').read_text())['implementation_commit']}`. The authoritative export-tag metrics are [phase4_summary.json](round3/phase4_summary.json); raw generation summary remains in summary.json. [Final verification](round3/phase4_verification.json) confirms preserved files, unchanged kept model outputs and zero calls resent for kept pairs."]
    report_path.write_text("\n".join(lines)+"\n", encoding="utf-8")
    state={"status":summary["status"],"phase4_failures":59,"arms":report["arms"],"real_leaks":0,
           "total_spend_usd":total,"additional_spend_usd":report["additional_spend_usd"],
           "ci_passed":347,"ci_skipped":1,"grounding_proxy_validated":False}
    (OUT/"run_status.json").write_text(json.dumps(state,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,indent=2))


if __name__ == "__main__":
    main()
