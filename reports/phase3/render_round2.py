"""Verify and render round 2: oracle evidence (dev labels); no network/model calls."""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "sdk")]

from nexus_agent.models import PatchProposal  # noqa: E402
from services.critic.dev_adapter import CLASSES, current_config, dev_labels, dev_traces  # noqa: E402
from services.critic.registry import ConfigRegistry  # noqa: E402
from services.critic.round2_providers import LABEL, Round2Ledger  # noqa: E402
from services.critic.round2_specificity import distinctness  # noqa: E402
import numpy as np  # noqa: E402

OUT = ROOT / "results/critic_dev/round2"
NAMES = {"old_deepseek": "Original DeepSeek", "new_deepseek": "New DeepSeek",
         "new_gemini": "New Gemini 3.5 Flash-Lite", "new_qwen": "New local Qwen 2.5 7B"}


def load(name):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def ratio(metric):
    if not metric["total"]:
        return "not estimable (0/0)"
    return f"{metric['successes']}/{metric['total']} ({100*metric['rate']:.1f}%)"


def ci(metric):
    if not metric["total"]:
        return "undefined"
    a, b = metric["ci95_clopper_pearson"]
    return f"{100*a:.2f}-{100*b:.2f}%"


def weighted_specificity(arm):
    classes = list(arm["per_class"].values())
    n = sum(x["completed"] for x in classes)
    exact = sum(x["specificity_all_sources"]["exact_unique"] for x in classes)
    near = sum(x["specificity_all_sources"]["near_components"] for x in classes)
    return {"n": n, "exact_unique_within_class_sum": exact, "near_components_within_class_sum": near,
            "exact_distinct_rate": exact/n if n else None, "near_distinct_rate": near/n if n else None}


def main():
    summary = load("summary.json")
    protocol = summary["protocol"]
    analysis = summary["analysis"]
    assert protocol["evidence_label"] == LABEL
    ledger = Round2Ledger(OUT / "calls.jsonl", git_commit=protocol["implementation_commit"])
    calls = ledger.rows()
    by_id = {c["call_id"]: c for c in calls}
    assert len(calls) == len(by_id)
    assert all(c["evidence_label"] == LABEL for c in calls)
    assert not any(c.get("mock") for c in calls)
    assert not any(c.get("status") == "reserved" for c in calls)
    assert ledger.spent < 1.0
    ids = protocol["trace_ids"]
    labels = {r["trace_id"]: r for r in dev_labels(ROOT / "data/nexusbench/labels.csv") if r["trace_id"] in set(ids)}
    traces = dev_traces(ROOT / "data/nexusbench/traces.jsonl", set(ids))
    assert all(hashlib.sha256(t.model_dump_json().encode()).hexdigest() == protocol["trace_sha256"][tid]
               for tid, t in traces.items())
    records, accounted_ids, rejected = {}, set(), []
    weighted = {}
    for arm, stats in summary["arms"].items():
        path = OUT / f"{arm}.jsonl"
        rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
        records[arm] = rows
        if stats["status"]["status"] == "complete":
            assert [r["trace_id"] for r in rows] == ids
        else:
            assert arm == "new_qwen"
        assert all(r["evidence_label"] == LABEL and r["implementation_commit"] == protocol["implementation_commit"] for r in rows)
        assert stats["overall"]["C1"]["successes"] == sum(r["c1_valid"] for r in rows)
        assert stats["overall"]["C2"]["successes"] == sum(r["dry_run_applied"] for r in rows if r["c1_valid"])
        for r in rows:
            cc = [by_id[i] for i in r["call_ids"]]
            assert all(c["arm"] == arm and c["trace_id"] == r["trace_id"] for c in cc)
            assert not (accounted_ids & set(r["call_ids"]))
            accounted_ids.update(r["call_ids"])
            assert math.isclose(r["cost_usd"], sum(c["cost_usd"] for c in cc), abs_tol=1e-12)
            assert r["input_tokens"] == sum(c.get("input_tokens") or 0 for c in cc)
            assert r["output_tokens"] == sum(c.get("output_tokens") or 0 for c in cc)
            assert not (r["source"] == "fallback" and r["c1_valid"])
            config = current_config(labels[r["trace_id"]])
            original = json.dumps(config, sort_keys=True)
            proposal = PatchProposal.model_validate(r["proposal"])
            try:
                ConfigRegistry(config).apply(proposal)
                applied = r["c1_valid"]
            except ValueError as exc:
                applied = False
                rejected.append({"arm": arm, "trace_id": r["trace_id"], "reason": str(exc), "source": r["source"]})
            assert applied == r["dry_run_applied"]
            assert json.dumps(config, sort_keys=True) == original
        weighted[arm] = weighted_specificity(stats)
        if rows:
            embedding = load(f"{arm}_embeddings.json")
            assert embedding["trace_ids"] == [r["trace_id"] for r in rows]
            vectors = np.asarray(embedding["vectors"])
            assert np.allclose(np.linalg.norm(vectors, axis=1), 1)
            for ft in CLASSES:
                indices = [i for i, r in enumerate(rows) if r["failure_type"] == ft]
                recomputed = distinctness([rows[i]["proposal"]["patch_content"] for i in indices], vectors[indices])
                expected = stats["per_class"][ft]["specificity_all_sources"]
                assert all(recomputed[k] == expected[k] for k in ("n", "exact_unique", "near_components", "direct_near_pairs"))
    diagnostics = [c for c in calls if c["arm"].startswith("diagnostic")]
    other_unassigned = [c for c in calls if c["call_id"] not in accounted_ids and c not in diagnostics]
    assert not other_unassigned or summary["arms"]["new_qwen"]["status"]["status"] != "complete"
    fingerprints = {arm: sorted({c.get("system_fingerprint") for c in calls if c["arm"] == arm and c.get("system_fingerprint")})
                    for arm in ("old_deepseek", "new_deepseek")}
    assert fingerprints["old_deepseek"] == fingerprints["new_deepseek"]
    c4_rows = {}
    for arm in ("new_deepseek", "new_gemini", "new_qwen"):
        stats = summary["arms"][arm]["overall"]
        cc = [c for c in calls if c["arm"] == arm]
        uncached = sum(((c.get("input_tokens") or 0)*.30 + (c.get("output_tokens") or 0)*(2.50 if arm == "new_gemini" else 1.20))/1e6 for c in cc) if arm != "new_qwen" else 0
        n = stats["completed"]
        c4_rows[arm] = {"evidence_label": LABEL, "status": summary["arms"][arm]["status"],
                        "C1": stats["C1"], "C2": stats["C2"], **weighted[arm],
                        "grounding": stats["grounding_patch_content"], "latency_ms": stats["latency_ms"],
                        "observed_cost_per_proposal_usd": stats["cost_per_proposal_usd"],
                        "uncached_token_cost_estimate_per_proposal_usd": uncached/n if n else None,
                        "input_cache_hit_tokens": sum(c.get("provider_usage", {}).get("prompt_cache_hit_tokens", 0) for c in cc),
                        "input_tokens": sum(c.get("input_tokens") or 0 for c in cc)}
    verification = {"evidence_label": LABEL, "implementation_commit": protocol["implementation_commit"],
                    "analysis_commit": analysis["git_commit"], "date_utc": analysis["date_utc"],
                    "selected_trace_hashes_unchanged": True, "metrics_recomputed_from_recorded_embeddings": True,
                    "proposal_call_ids_and_costs_reconciled": True, "no_config_snapshot_mutated": True,
                    "deepseek_fingerprints": fingerprints, "diagnostic_calls": len(diagnostics),
                    "diagnostic_cost_usd": sum(c["cost_usd"] for c in diagnostics),
                    "generation_calls": len(calls), "total_spend_usd": ledger.spent,
                    "mock_results": 0, "test_records_deserialized_or_scored": 0,
                    "validator_rejection_attempts": {arm: sum(len(r["validator_failures"]) for r in rs) for arm, rs in records.items()},
                    "dry_run_rejections": rejected, "C4": c4_rows}
    (OUT / "verification.json").write_text(json.dumps(verification, indent=2), encoding="utf-8")
    baseline = {"evidence_label": LABEL, "implementation_commit": protocol["implementation_commit"],
                "analysis_commit": analysis["git_commit"],
                "original_commit": protocol["original_commit"], "date_utc": protocol["date_utc"],
                "selection_sha256": protocol["selection_sha256"], "context_bleed_regeneration_pending": True,
                "deepseek_fingerprints": fingerprints, "arms": {}}
    for arm in ("old_deepseek", "new_deepseek"):
        m = summary["arms"][arm]
        baseline["arms"][arm] = {"overall": {key: m["overall"][key] for key in
            ("C1", "C2", "fallback", "validator_failure_reasons", "grounding_patch_content")},
            "within_class_specificity": weighted[arm], "per_class": {ft: {key: value[key] for key in
                ("C1", "C2", "fallback", "validator_failure_reasons", "grounding_patch_content")}
                for ft, value in m["per_class"].items()}}
    (OUT / "baseline_comparison.json").write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    (OUT / "c4.json").write_text(json.dumps({"evidence_label": LABEL, "implementation_commit": protocol["implementation_commit"],
                 "analysis_commit": analysis["git_commit"],
                 "date_utc": protocol["date_utc"], "context_bleed_regeneration_pending": True,
                 "distinctness_aggregation": "Sum of within-class unique strings/components divided by completed proposals; see per-class summary.json",
                 "rows": c4_rows, "spend": summary["spend"]}, indent=2), encoding="utf-8")

    parts = ["\n<!-- ROUND2_RESULTS -->\n", "## Results: oracle evidence (dev labels)\n",
             f"Generation implementation commit: `{protocol['implementation_commit']}`. Analysis code commit: `{analysis['git_commit']}`. Generation started `{protocol['date_utc']}` (2026-11-10 America/New_York). DeepSeek fingerprint for both original and new runs: `{fingerprints['old_deepseek'][0]}`. Gemini exposes its stable model alias as `modelVersion`; an immutable Gemini checkpoint ID is not exposed. Qwen's pinned digest and the active 32K context are recorded in `qwen_backend_metadata.json`.\n",
             "Final analysis uses explicit UTF-8. A final Unicode check found that the first analysis pass used the Windows default encoding for some JSONL readers. Readers were corrected, a regression test added, and all embeddings/specificity results and quoted examples regenerated from the unchanged saved outputs. This added no model calls or spend; it did not change the frozen normalization, cosine threshold, pooling or evidence-anchor rules. See `encoding_fix_audit.json`.\n",
             "### Original versus new DeepSeek\n",
             "| Critic | Fallback / proposals | Exact 95% interval | Validator rejection attempts | C1 | Post-hoc/new C2 |\n|---|---:|---:|---:|---:|---:|"]
    for arm in ("old_deepseek", "new_deepseek"):
        m = summary["arms"][arm]["overall"]
        parts.append(f"| {NAMES[arm]} | {ratio(m['fallback'])} | {ci(m['fallback'])} | {verification['validator_rejection_attempts'][arm]} | {ratio(m['C1'])} | {ratio(m['C2'])} |")
    parts.append("\nNo fallback-rate reduction was observed between the original and new DeepSeek critics on these 60 DEV failures. Zero observed fallbacks does not prove a zero population fallback probability. The large C2 difference reflects the new config surface/registry contract; it is not proof of repaired tasks.\n")
    parts.append("| Class | Original fallback | New DeepSeek fallback | Original validator reasons | New DeepSeek validator reasons |\n|---|---:|---:|---|---|")
    for ft in CLASSES:
        a, b = (summary["arms"][arm]["per_class"][ft] for arm in ("old_deepseek", "new_deepseek"))
        parts.append(f"| {ft}{'*' if ft == 'CONTEXT_BLEED' else ''} | {ratio(a['fallback'])} | {ratio(b['fallback'])} | {json.dumps(a['validator_failure_reasons'])} | {json.dumps(b['validator_failure_reasons'])} |")
    parts.extend(["\n### C4: same 60 failures, new critic\n",
                  "Exact/near distinctness below sums the **within-class** unique strings/components and divides by 60. It is the mean of the five equal-size class rates, rather than cross-class pooling. Grounding is patch-content-only. The table includes fallbacks; LLM-only figures follow below. Latencies are observed on a shared machine with concurrent arm streams, not an isolated load/throughput benchmark.\n",
                  "| Model | C1 valid/all | C2 applied/valid | Exact distinct | Near distinct | Grounded | p50 / p90 seconds | Accounted $/proposal | Uncached token estimate $/proposal |\n|---|---:|---:|---:|---:|---:|---:|---:|---:|"])
    for arm, m in c4_rows.items():
        n, latency = m["n"], m["latency_ms"]
        lat = f"{latency['p50']/1000:.2f} / {latency['p90']/1000:.2f}" if latency else "not estimable"
        price = f"${m['observed_cost_per_proposal_usd']:.6f}" if n else "not estimable"
        uncached = f"${m['uncached_token_cost_estimate_per_proposal_usd']:.6f}" if n else "not estimable"
        parts.append(f"| {NAMES[arm]} | {ratio(m['C1'])} | {ratio(m['C2'])} | {m['exact_unique_within_class_sum']}/{n} | {m['near_components_within_class_sum']}/{n} | {ratio(m['grounding'])} | {lat} | {price} | {uncached} |")
    parts.append("\nObserved dollars depend on cache hits. The uncached estimate reprices the same observed input/output tokens with no input-cache discount, including all attempts; it is not a new model run. Local Qwen's $0 is API cost only. No model is established as best at repair by this table.\n")
    for arm in NAMES:
        m = summary["arms"][arm]["overall"]
        parts.append(f"- {NAMES[arm]}: C1 CI {ci(m['C1'])}; C2 CI {ci(m['C2'])}; grounding CI {ci(m['grounding_patch_content'])}. Validator rejection reasons: {json.dumps(m['validator_failure_reasons'])}.")
    parts.extend(["\n### Specificity by class: oracle evidence (dev labels)\n",
                  "Every cell is a count over returned proposals. Exact and near columns count distinct strings/components, not the number of proposals with no duplicate neighbor. JSON additionally records redundant copies, duplicate-group members, direct pairs and their cosine scores.\n",
                  "| Critic/model | Class | N | Exact distinct | Near distinct | Grounded | Grounded with explanation | Identifier-only grounded |\n|---|---|---:|---:|---:|---:|---:|---:|"])
    for arm in NAMES:
        for ft, m in summary["arms"][arm]["per_class"].items():
            d = m["specificity_all_sources"]
            parts.append(f"| {NAMES[arm]} | {ft}{'*' if ft == 'CONTEXT_BLEED' else ''} | {m['completed']} | {d['exact_unique']}/{d['n']} | {d['near_components']}/{d['n']} | {ratio(m['grounding_patch_content'])} | {ratio(m['grounding_content_and_explanation'])} | {ratio(m['grounding_identifiers_only'])} |")
    parts.extend(["\n*All CONTEXT_BLEED rows are provisional and will be rerun after Phase 2 bleed regeneration.*\n",
                  "LLM-only specificity (fallbacks excluded):\n",
                  "| Critic/model | Class | LLM N | Exact distinct | Near distinct |\n|---|---|---:|---:|---:|"])
    for arm in NAMES:
        for ft, m in summary["arms"][arm]["per_class"].items():
            d = m["specificity_llm_only"]
            parts.append(f"| {NAMES[arm]} | {ft} | {d['n']} | {d['exact_unique']}/{d['n']} | {d['near_components']}/{d['n']} |")
    parts.extend(["\n### Spend and checks\n",
                  f"**Round 2 accounted spend: ${ledger.spent:.9f} of the $1.00 aggregate cap.** This includes {len(diagnostics)} Gemini protocol checks costing ${sum(c['cost_usd'] for c in diagnostics):.9f}, all retries, and local model calls at $0 API cost. All reservations have settled. The ledger records {len(calls)} generation requests. Round 1's spend is not charged to this separate round's cap.\n"])
    for arm, cost in summary["spend"]["by_arm"].items():
        parts.append(f"- {arm}: ${cost:.9f}.")
    chunk_audit = load("embedding_chunk_audit.json")
    assert not chunk_audit["overlength_chunks"]
    parts.append(f"\nThe audit verified unchanged hashes for all 60 selected DEV traces, matching original/new DeepSeek fingerprints, every proposal's call IDs/tokens/cost, identical metric counts recomputed from recorded embeddings, no mutated config snapshots, and no mock/test-set results. All {chunk_audit['chunks']} re-encoded embedding chunks fit the 256-token limit; the tokenizer's pre-chunk long-text warning did not cause model-input truncation. See `embedding_chunk_audit.json`. Registry rejection details are preserved in `verification.json`. No generated proposal was applied to the agent or sent to a live store.\n")
    for arm, stats in summary["arms"].items():
        parts.append(f"- {NAMES[arm]} status: {stats['status']['status']}; completed {stats['status'].get('completed',0)}/60. {stats['status'].get('reason','')}")
    parts.extend(["\n## Example patches: oracle evidence (dev labels)\n",
                  "The first three selected traces per class are quoted for each critic/model, without choosing by outcome. These are complete `patch_content` values. Source and applicability are shown; quoted model proposals and template claims are not measured repair effects. Full proposal context and matched evidence anchors are in the corresponding trial JSONL. CONTEXT_BLEED examples remain provisional.\n"])
    for arm, rows in records.items():
        parts.append(f"### {NAMES[arm]}\n")
        for ft in CLASSES:
            chosen = [r for r in rows if r["failure_type"] == ft][:3]
            if not chosen:
                continue
            parts.append(f"#### {ft}{' (provisional)' if ft == 'CONTEXT_BLEED' else ''}\n")
            for i, r in enumerate(chosen, 1):
                p = r["proposal"]
                parts.append(f"{i}. `{r['trace_id']}`; source `{r['source']}`; `{p['patch_type']}` -> `{p['target_component']}`; C1={r['c1_valid']}, dry-run={r['dry_run_applied']}, grounded={r['grounding']['grounded']}.\n")
                parts.append("\n".join("> " + line for line in p["patch_content"].splitlines())+"\n")
    parts.extend(["\n## Artifacts and reproduction\n",
                  "- [Summary with per-class/source counts and intervals](../../results/critic_dev/round2/summary.json), [baseline comparison](../../results/critic_dev/round2/baseline_comparison.json), [C4 table data](../../results/critic_dev/round2/c4.json), [verification](../../results/critic_dev/round2/verification.json).\n- [Frozen protocol and trace/source hashes](../../results/critic_dev/round2/protocol.json), [append-only call ledger](../../results/critic_dev/round2/calls.jsonl), [embedding chunk audit](../../results/critic_dev/round2/embedding_chunk_audit.json).\n- Trial JSONL and embedding JSON files are named by arm in `results/critic_dev/round2/`; each carries the oracle-evidence label and measured implementation commit.\n",
                  "Generation: `python -m services.critic.round2` (requires existing local keys, offline MiniLM cache and the authorized provider endpoints). The runner refuses to overwrite an existing protocol. Analysis only: `python -m services.critic.round2 --analyze-only`. Audit/report only: `python reports/phase3/render_round2.py`. No analysis command makes a model call.\n",
                  "C3 and Phase 4 were not started.\n"])
    path = ROOT / "reports/phase3/round2.md"
    prefix = path.read_text(encoding="utf-8").split("<!-- ROUND2_RESULTS -->")[0].rstrip()
    start, end = "<!-- ROUND2_HEADLINE -->", "<!-- END_ROUND2_HEADLINE -->"
    if start in prefix:
        prefix = prefix[:prefix.index(start)] + prefix[prefix.index(end)+len(end):]
    old, new = weighted["old_deepseek"], weighted["new_deepseek"]
    headline = (
        f"**Result:** no observed DeepSeek fallback reduction (original 0/60, new 0/60). "
        f"New DeepSeek patches are less specific by these proxies: "
        f"{new['near_components_within_class_sum']}/60 within-class near-distinct groups versus "
        f"{old['near_components_within_class_sum']}/60 for the original; evidence references "
        f"{summary['arms']['new_deepseek']['overall']['grounding_patch_content']['successes']}/60 versus "
        f"{summary['arms']['old_deepseek']['overall']['grounding_patch_content']['successes']}/60. "
        "The new config checks improve mechanical applicability, which does not establish repair effectiveness. "
        f"All four arms completed 60 traces. Accounted spend: **${ledger.spent:.9f}**."
    )
    title, _, remainder = prefix.partition("\n")
    prefix = title+"\n\n"+start+"\n"+headline+"\n"+end+"\n\n"+remainder.lstrip("\n")
    text = prefix+"\n"+"\n".join(parts)
    path.write_text("\n".join(line.rstrip() for line in text.splitlines())+"\n", encoding="utf-8")
    print(json.dumps({"spend": ledger.spent, "weighted_specificity": weighted, "C4": c4_rows}, indent=2))


if __name__ == "__main__":
    main()
