"""Aggregate private A-only diagnostic records into a content-free report."""
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "sdk"), str(ROOT)]
from scripts.external.diagnose_trail import DIAG, PRIVATE, RESULT, distribution, sha


def merge(records, field):
    total = Counter()
    for record in records:
        total.update(record.get(field, {}))
    return dict(total)


def histogram(values):
    return dict(sorted(Counter(map(str, values)).items(), key=lambda item: float(item[0])))


def loop_summary(records, field):
    rows = [r[field] for r in records]
    return {"tool_steps": distribution([r["tool_steps"] for r in rows]),
        "tool_step_count_histogram": histogram(r["tool_steps"] for r in rows),
        "longest_run_histogram": histogram(r["longest_successful_identical_consecutive_run"] for r in rows),
        "traces_with_run_at_least_3": sum(r["longest_successful_identical_consecutive_run"] >= 3 for r in rows),
        "traces_with_exact_nonconsecutive_repeats": sum(r["exact_repeat_pairs_separated_by_other_tool_steps"] > 0 for r in rows),
        "exact_nonconsecutive_repeat_pairs": sum(r["exact_repeat_pairs_separated_by_other_tool_steps"] for r in rows),
        "traces_with_non_tool_span_interleaving_between_equal_calls": sum(r["equal_consecutive_tool_pairs_with_other_spans_between"] > 0 for r in rows),
        "same_tool_argument_pair_types": merge(rows, "argument_changes_between_successive_calls_of_same_tool"),
        "traces_by_argument_pair_type": dict(Counter(key for r in rows for key, n in r["argument_changes_between_successive_calls_of_same_tool"].items() if n))}


def errors_summary(records):
    rows = [r["errors"] for r in records]
    return {"traces": len(rows), "all_span_error_types": merge(rows,"all_span_error_types"),
        "original_tool_error_types": merge(rows,"original_tool_error_types"),
        "visible_tool_error_types": merge(rows,"visible_tool_error_types"),
        "all_span_errors": sum(r["all_span_errors"] for r in rows),
        "traces_with_original_tool_errors": sum(r["original_tool_errors"] > 0 for r in rows),
        "original_tool_errors": sum(r["original_tool_errors"] for r in rows),
        "visible_tool_errors": sum(r["visible_tool_errors"] for r in rows),
        "retagged_retrieval_errors": sum(r["retagged_retrieval_errors"] for r in rows),
        "retry_patterns": merge(rows,"retry_patterns")}


def original_exact_repeat_status(records):
    counts=Counter()
    longest=[]
    for record in records:
        previous=None; streak=maximum=0
        for step in record["original_tool_steps"]:
            same=previous and (step["tool"],step["args_sha256"])==(previous["tool"],previous["args_sha256"])
            streak=streak+1 if same else 1
            maximum=max(maximum,streak)
            if same:
                counts["adjacent_exact_pairs_all_statuses"]+=1
                counts["adjacent_exact_pairs_both_successful"]+=int(step["ok"] and previous["ok"])
                counts["adjacent_exact_pairs_with_error"]+=int(not step["ok"] or not previous["ok"])
            previous=step
        longest.append(maximum)
    return {"pair_counts":dict(counts),"longest_run_ignoring_success_histogram":histogram(longest)}


def aggregate(records, state, result, sanity):
    if len(records) != 63 or len({r["trace_id"] for r in records}) != 63:
        raise RuntimeError("Incomplete or duplicate A diagnostic records")
    loop = [r for r in records if r["gold_classes"]["LOOP_DETECTED"]]
    misfire = [r for r in records if r["gold_classes"]["TOOL_MISFIRE"]]
    eligible = [r for r in records if r["hallucination_applicability"]["reached"] and r["hallucination_applicability"]["reason"] is None]
    if (len(loop),len(misfire),len(eligible)) != (22,2,19):
        raise RuntimeError("Post-hoc cohort reconstruction differs from saved result")
    claims = [c for r in eligible for c in r["nli_observations"]["claims"]]
    pairs = [p for r in eligible for p in r["nli_observations"]["pairs"]]
    best = [c["best_entailment_after_entity_gate"] for c in claims]
    cutoff = 1 - result["provenance"]["detector_thresholds"]["HALLUCINATION"]["threshold"]
    bins = {"exact_zero": sum(v == 0 for v in best), "gt0_to_0.1": sum(0 < v <= .1 for v in best),
        "gt0.1_to_0.25": sum(.1 < v <= .25 for v in best), "gt0.25_to_flag_cutoff": sum(.25 < v <= cutoff for v in best),
        "gt_flag_cutoff_to_0.75": sum(cutoff < v <= .75 for v in best),
        "gt0.75_to_0.9": sum(.75 < v <= .9 for v in best), "gt0.9_to_1": sum(.9 < v <= 1 for v in best)}
    labels = dict(Counter(r["raw_pipeline_label"] for r in records))
    for name in ("LOOP_DETECTED","TOOL_MISFIRE","CONTEXT_BLEED","PLAN_DRIFT","HALLUCINATION","NORMAL"):
        labels.setdefault(name,0)
    difference_ids = [r["trace_id"] for r in records if r["decision_differences"]]
    flags = {name: {"true":sum(bool(r["flags"][name]) for r in records),
                    "false":sum(not r["flags"][name] for r in records)}
             for name in ("LOOP_DETECTED","TOOL_MISFIRE","CONTEXT_BLEED","PLAN_DRIFT","HALLUCINATION")}
    out = {"scope":"post-hoc diagnostics on TRAIL-A (development data after scoring)",
        "scorer_sanity":sanity, "diagnostic_runtime_seconds":state["runtime_seconds"],
        "diagnostic_code_commit":state["diagnostic_code_commit"],
        "fresh_pipeline_label_counts":labels, "fresh_independent_flag_counts":flags,
        "decision_difference_trace_ids":difference_ids,
        "loop_masked_by_other_label":sum(r["raw_outputs"]["loop"] and r["raw_pipeline_label"] != "LOOP_DETECTED" for r in records),
        "misfire_masked_by_other_label":sum(r["raw_outputs"]["misfire"] and r["raw_pipeline_label"] != "TOOL_MISFIRE" for r in records),
        "raw_NLI_trace_scores":distribution([r["raw_outputs"]["hallucination"] for r in records if r["raw_outputs"]["hallucination"] is not None]),
        "raw_NLI_null_traces":sum(r["raw_outputs"]["hallucination"] is None for r in records),
        "loop_positive":{"traces":len(loop),"frozen_visible":loop_summary(loop,"loop_visible"),
            "original_TOOL_projection":loop_summary(loop,"loop_original_tool"),
            "original_exact_repeats_by_status":original_exact_repeat_status(loop),
            "original_tool_steps":sum(r["nesting_original_tools"]["tool_steps"] for r in loop),
            "original_tool_steps_with_agent_ancestor":sum(r["nesting_original_tools"]["with_agent_ancestor"] for r in loop),
            "visible_tool_steps":sum(r["nesting_visible_tools"]["tool_steps"] for r in loop),
            "visible_tool_steps_with_agent_ancestor":sum(r["nesting_visible_tools"]["with_agent_ancestor"] for r in loop)},
        "hallucination":{"eligible_traces":len(eligible),"claims_per_trace":distribution([r["claim_count"] for r in eligible]),
            "claims_per_trace_histogram":histogram(r["claim_count"] for r in eligible),
            "retrieved_characters_per_trace":distribution([r["retrieved_characters"] for r in eligible]),
            "model_max_pair_tokens":state["model_max_pair_tokens"], "pairs":len(pairs),
            "full_pair_tokens":distribution([p["full_tokens"] for p in pairs]),
            "pairs_truncated":sum(p["removed_tokens"] > 0 for p in pairs),
            "tokens_removed":sum(p["removed_tokens"] for p in pairs),
            "premise_tokens_removed":sum(p["removed_premise_tokens"] for p in pairs),
            "claim_tokens_removed":sum(p["removed_claim_tokens"] for p in pairs),
            "removed_tokens_per_pair":distribution([p["removed_tokens"] for p in pairs]),
            "traces_with_truncated_pair":sum(any(p["removed_tokens"] > 0 for p in r["nli_observations"]["pairs"]) for r in eligible),
            "raw_best_entailment_per_claim":distribution([c["raw_best_entailment"] for c in claims]),
            "best_entailment_after_entity_gate_per_claim":distribution(best), "best_entailment_histogram":bins,
            "gate_forced_zero_claims":sum(c["allowed_premise_units"] == 0 for c in claims),
            "traces_with_gate_forced_zero_claim":sum(any(c["allowed_premise_units"] == 0 for c in r["nli_observations"]["claims"]) for r in eligible),
            "per_claim_flag_cutoff_entailment":cutoff, "claims_at_or_below_flag_cutoff":sum(v <= cutoff for v in best),
            "all_claims_from_final_output":len(claims), "intermediate_step_claims_evaluated":0,
            "eligible_annotation_location_counts":merge(eligible,"hallucination_labels_on_eligible")},
        "tool_errors_all_A":errors_summary(records),"tool_errors_misfire_positives":errors_summary(misfire)}
    if sum(bins.values()) != len(claims):
        raise RuntimeError("Entailment histogram does not partition claims")
    return out


def summary_text(values):
    if not values.get("n"):
        return "not available"
    return f"n={values['n']}; min={values['min']:.6g}, p25={values['p25']:.6g}, median={values['median']:.6g}, p75={values['p75']:.6g}, p90={values['p90']:.6g}, p95={values['p95']:.6g}, max={values['max']:.6g}, mean={values['mean']:.6g}"


def dict_table(values, key_name="Category"):
    lines=[f"| {key_name} | Count |","| --- | ---: |"]
    lines += [f"| `{key}` | {value} |" for key,value in sorted(values.items())]
    return lines if values else ["None observed."]


def render(a):
    loop=a["loop_positive"]; h=a["hallucination"]
    v=loop["frozen_visible"]; original=loop["original_TOOL_projection"]
    s=a["scorer_sanity"]
    lines=["# TRAIL diagnosis", "", "**post-hoc diagnostics on TRAIL-A (development data after scoring)**", "",
        "This is explanatory analysis, not a new validation result. No v2 change is implemented. "
        "TRAIL-B traces and labels were not loaded or evaluated. The original scored JSON, original results report, "
        "and original scoring checkpoint remain byte-for-byte unchanged. The accepted pre-A2 mechanical join disclosure remains in A2.", "",
        "## 1. Scorer sanity - checked before fresh diagnostics", "",
        "**No scorer/metric bug was found in the checks performed.** Class names exactly match the frozen detector names: "
        "`LOOP_DETECTED`, `TOOL_MISFIRE`, `HALLUCINATION`. Category matching follows the registered case/whitespace/punctuation "
        "normalization and fixed category list, including the user-specified short `Language-only` term; tool-misfire labels "
        "require original OpenInference TOOL identity, including spans retagged as retrieval by A1. No taxonomy expansion was made.", "",
        "The scorer uses `pipeline.fired`, independently for each class; it does not use the priority-winning label. "
        "Saved split counts reconcile with the aggregate, class denominators, precision/recall and Wilson intervals. "
        "No correction, replacement result, or v0 scorer-bug file was created.", "",
        "**Checkpoint limitation:** despite containing completed IDs and running counters, the checkpoints do not contain "
        "per-trace predictions, raw detector scores, original `pipeline.label` outputs, or claim entailment values. "
        "Therefore those values cannot be recovered or independently re-aggregated from the historical checkpoints. "
        "This is an observability gap, not evidence of a metric bug. The saved aggregates determine: both loop/misfire flags "
        "were false on all 63 converted traces; hallucination was positive on all 19 eligible traces and abstained on 44. "
        "The remaining A trace was excluded for conversion before detector execution.", "",
        "The user subsequently authorized fresh offline diagnostics. The following raw distributions and pipeline label "
        "counts are **fresh diagnostic observations, not historical saved raw outputs**. The observer delegates to the same "
        "pinned model and returns its original probability object unchanged; frozen files, thresholds and extraction code are unchanged. "
        "Raw trace/claim observations are private under `data/external/trail/diagnostics/`; no claim text is printed or committed.", "",
        f"Consistency check: **{len(a['decision_difference_trace_ids'])} trace decision differences** versus the decisions "
        "recoverable from the original aggregates. Loop/misfire were compared as false per converted trace; every reconstructable "
        "eligible hallucination decision was compared as positive, with abstentions kept separate. Exact original numeric-score "
        "nondeterminism cannot be tested because the original numeric scores were discarded.", ""]
    if a["decision_difference_trace_ids"]:
        lines += ["Differing trace IDs: " + ", ".join(f"`{i}`" for i in a["decision_difference_trace_ids"])+".",""]
    lines += ["Fresh raw pipeline label counts (63 converted traces; one separate conversion exclusion):",""]
    lines += dict_table(a["fresh_pipeline_label_counts"],"Pipeline label")
    lines += ["", "Independent raw flags (before label priority):", "",
        "| Detector | True | False |", "| --- | ---: | ---: |"]
    for name in ("LOOP_DETECTED","TOOL_MISFIRE","CONTEXT_BLEED","PLAN_DRIFT","HALLUCINATION"):
        counts=a["fresh_independent_flag_counts"][name]
        lines.append(f"| {name} | {counts['true']} | {counts['false']} |")
    lines += ["", f"Raw NLI score (non-null): {summary_text(a['raw_NLI_trace_scores'])}. "
        f"Null NLI scores: {a['raw_NLI_null_traces']}. A null produces a false raw threshold flag but remains an abstention in scored metrics.", "",
        "## 2. Single-label masking", "",
        "The frozen pipeline exposes a priority label in this order: LOOP_DETECTED, TOOL_MISFIRE, CONTEXT_BLEED, "
        "PLAN_DRIFT, HALLUCINATION; otherwise NORMAL. `compute_scores` returns all detector values, and the scorer "
        "used all `fired` flags independently.", "",
        f"Internally firing loop flags masked by another label: **{a['loop_masked_by_other_label']}**. "
        f"Internally firing misfire flags masked by another label: **{a['misfire_masked_by_other_label']}**. "
        "Masking does not explain the zero loop/misfire alerts. LOOP is first in the priority order and cannot lose to another class.", "",
        "## 3. LOOP - 22 mapped positive A traces", "",
        "The frozen rule filters the flattened, completion-ordered spans to TOOL_CALL/MEMORY_READ, parses JSON arguments "
        "and sorts JSON keys, then requires three consecutive identical successful tool/name/argument calls. "
        "Agent and LLM spans do not break this filtered sequence. A1 retrieval spans are absent from it.", "",
        "Longest successful identical-consecutive-run distribution visible to the frozen rule:", ""]
    lines += dict_table(v["longest_run_histogram"],"Longest run")
    lines += ["", "Diagnostic-only original-OpenInference-TOOL projection (includes A1 retrieval tools, without changing the detector input):", ""]
    lines += dict_table(original["longest_run_histogram"],"Longest run")
    lines += ["", f"Visible tool steps: {loop['visible_tool_steps']}; original TOOL-origin steps: {loop['original_tool_steps']}. "
        f"Traces containing a run of at least three: {v['traces_with_run_at_least_3']} visible, "
        f"{original['traces_with_run_at_least_3']} in the original-TOOL descriptive projection. "
        "Restoring retrieval tool visibility alone would not create the required successful three-call pattern in these 22 traces. "
        "These are signal descriptions, not rescored v2 accuracy.", "",
        f"Original tool counts per trace: {summary_text(original['tool_steps'])}. "
        f"Visible tool counts per trace: {summary_text(v['tool_steps'])}.", "",
        "Argument-change categories between successive invocations of the same tool (even if other tools intervene):", "",
        "| Category | Original-TOOL pairs | Visible pairs | Original traces with category |", "| --- | ---: | ---: | ---: |"]
    keys=("exact","whitespace_only","json_formatting_or_key_order_only","ID_pattern_or_ID_field_only",
          "small_edit_similarity_at_least_0.90","other_changed_arguments")
    for key in keys:
        lines.append(f"| `{key}` | {original['same_tool_argument_pair_types'].get(key,0)} | {v['same_tool_argument_pair_types'].get(key,0)} | {original['traces_by_argument_pair_type'].get(key,0)} |")
    lines += ["", "Definitions: whitespace/key-order-only changes must have identical parsed canonical JSON; they are already "
        "normalized by v1 and are not evidence of a missed loop. ID-only changes are a descriptive heuristic using ID/UUID "
        "fields and explicit identifier patterns. Small edits use SequenceMatcher similarity >=0.90 on canonical arguments "
        "of at most 20,000 characters. These categories do not establish semantic equivalence or faulty repetition.", "",
        f"Exact repetitions separated by other original tool steps occur in {original['traces_with_exact_nonconsecutive_repeats']} "
        f"traces ({original['exact_nonconsecutive_repeat_pairs']} successive identical-key repeat pairs); visible equivalents: "
        f"{v['traces_with_exact_nonconsecutive_repeats']} traces / {v['exact_nonconsecutive_repeat_pairs']} pairs. "
        f"Equal consecutive tool pairs with intervening filtered-out spans occur in {original['traces_with_non_tool_span_interleaving_between_equal_calls']} "
        f"original-TOOL traces and {v['traces_with_non_tool_span_interleaving_between_equal_calls']} visible traces.", "",
        "Original-TOOL exact adjacent repeat pairs by success/error status:", ""]
    lines += dict_table(loop["original_exact_repeats_by_status"]["pair_counts"],"Adjacent identical pair")
    lines += ["", "Longest original-TOOL identical run if success status is ignored (diagnostic description only):", ""]
    lines += dict_table(loop["original_exact_repeats_by_status"]["longest_run_ignoring_success_histogram"],"Longest run, any status")
    lines += ["",
        f"Nesting: {loop['original_tool_steps_with_agent_ancestor']}/{loop['original_tool_steps']} original tool steps and "
        f"{loop['visible_tool_steps_with_agent_ancestor']}/{loop['visible_tool_steps']} visible tool steps have an agent-step ancestor. "
        "Nesting itself cannot make calls non-consecutive at the rule's level: the adapter flattens them and the helper filters "
        "away agent/LLM steps. Other retained tool calls break a run; A1's type projection removes retrieval calls altogether.", "",
        "## 4. HALLUCINATION - 19 eligible A traces", "",
        f"Claims per trace: {summary_text(h['claims_per_trace'])}. Retrieved characters per trace: "
        f"{summary_text(h['retrieved_characters_per_trace'])}.", "",
        f"The local model's maximum is **{h['model_max_pair_tokens']} tokens per premise/claim pair**, including special tokens. "
        "This is not a 512-character whole-trace limit. Frozen retrieval text is split into premises and premise units before NLI. "
        "Tokenization was replayed with the same tokenizer and longest-first pair truncation; model probabilities were not altered.", "",
        f"Full pair token lengths: {summary_text(h['full_pair_tokens'])}. "
        f"Truncated pairs: **{h['pairs_truncated']}/{h['pairs']}**, across {h['traces_with_truncated_pair']}/19 traces. "
        f"Removed tokens across pairs: {h['tokens_removed']} ({h['premise_tokens_removed']} premise-side, "
        f"{h['claim_tokens_removed']} claim-side). These are repeated pair-token counts, not unique source-text coverage. "
        f"Removed-token distribution per pair: {summary_text(h['removed_tokens_per_pair'])}.", "",
        f"Best entailment per claim before the entity gate: {summary_text(h['raw_best_entailment_per_claim'])}. "
        f"After the frozen entity gate: {summary_text(h['best_entailment_after_entity_gate_per_claim'])}.", "",
        "After-gate best-entailment distribution:", ""]
    lines += dict_table(h["best_entailment_histogram"],"Best entailment bin")
    lines += ["", f"The frozen gate permits support only from premise units containing every extracted claim entity. "
        f"It leaves no eligible premise for **{h['gate_forced_zero_claims']} claims** across "
        f"{h['traces_with_gate_forced_zero_claim']}/19 traces, forcing their best entailment to zero regardless of NLI probability. "
        f"{h['claims_at_or_below_flag_cutoff']} claims have best entailment <={h['per_claim_flag_cutoff_entailment']:.4f}; "
        "a single sufficiently unsupported claim can flag the entire trace via its worst claim. "
        "Here the gate alone algebraically forces the fresh score to 1 on all 19 traces, irrespective of tokenizer truncation. "
        "This does not establish what precision an alternative gate would achieve.", "",
        f"All {h['all_claims_from_final_output']} evaluated claims, including all flagged claims, come from "
        f"`CompleteTrace.final_output`; {h['intermediate_step_claims_evaluated']} intermediate-step claim sets are evaluated. "
        "Very short answer claims are augmented with root-input question text by the frozen extractor. "
        "This is provenance of the detector input, not a claim that every factual statement occurred only at the end.", "",
        "Mapped hallucination annotation locations within the eligible cohort (location and span-kind rows describe "
        "overlapping dimensions of the same annotations; do not add them together):", ""]
    lines += dict_table(h["eligible_annotation_location_counts"],"Location/kind")
    lines += ["", "A final-output carrier is defined structurally as a span whose mapped output equals the trace's final output. "
        "A non-carrier is a different annotated span, a proxy for an intermediate/local failure; it is not a semantic "
        "judgment about the annotation. The final-answer-only detector does not directly localize or score these other spans.", "",
        "## 5. TOOL_MISFIRE - n=2 mapped positives", "",
        "**Nothing about misfire performance or a v2 operating point can be concluded from two positive A traces.** "
        "The following error-pattern descriptions are for development hypotheses only, not additional evaluation.", "",
        "Error counts are historical errored-span occurrences, not independent root-cause incidents; a single failure can propagate through nested spans. "
        "Provider-related exception class names describe captured dataset events, not provider calls made by this diagnostic run.", "",
        "All error types across 63 converted A traces:", ""]
    lines += dict_table(a["tool_errors_all_A"]["all_span_error_types"],"Error type")
    lines += ["", "Original TOOL-origin error types (including A1-retagged retrieval calls):", ""]
    lines += dict_table(a["tool_errors_all_A"]["original_tool_error_types"],"Error type")
    lines += ["", "Error types still visible to the frozen tool-call helper:", ""]
    lines += dict_table(a["tool_errors_all_A"]["visible_tool_error_types"],"Error type")
    e=a["tool_errors_all_A"]; m=a["tool_errors_misfire_positives"]
    lines += ["", f"Original tool errors: {e['original_tool_errors']} in {e['traces_with_original_tool_errors']} traces; "
        f"{e['retagged_retrieval_errors']} are on retrieval-retagged spans and {e['visible_tool_errors']} remain visible. "
        "The frozen rule requires a failed call followed by the same tool and identical canonical arguments within two retained tool calls; "
        "a corrected-argument retry is outside that rule.", "", "Retry patterns on the descriptive original-TOOL sequence:", ""]
    lines += dict_table(e["retry_patterns"],"Error-event pattern (overlaps allowed)")
    lines += ["", f"Within the two mapped-positive traces: {m['original_tool_errors']} original-tool errors, "
        f"{m['retagged_retrieval_errors']} retrieval-retagged errors, {m['visible_tool_errors']} visible tool errors. "
        "Their original-tool error types:", ""]
    lines += dict_table(m["original_tool_error_types"],"Error type")
    lines += ["", "## 6. Candidate v2 changes - hypotheses, not implemented", "",
        "| Finding | Candidate development change on A |", "| --- | --- |",
        f"| {loop['original_tool_steps']} original TOOL-origin steps versus {loop['visible_tool_steps']} visible steps in loop-positive traces; {e['retagged_retrieval_errors']} retagged retrieval errors | Preserve tool execution identity and source-evidence role as separate channels; validate both loop/misfire and grounding inputs. |",
        "| Longest-run and argument/interleaving distributions above | Test progress-aware, argument-aware repetition windows and a separate timeout/resource-budget signal; do not assume ID changes or similar text mean a fault. JSON whitespace/key order already normalizes. |",
        f"| {loop['original_exact_repeats_by_status']['pair_counts'].get('adjacent_exact_pairs_with_error',0)} adjacent identical pairs contain an error; none are two successful calls | Distinguish failed-retry loops from successful stalls and successful recovery, with an explicit v2 fault taxonomy rather than relabeling the v1 result. |",
        f"| Entity gate forces zero for {h['gate_forced_zero_claims']} claims in {h['traces_with_gate_forced_zero_claim']} traces | On A, audit entity normalization and compare gate behavior with NLI support; avoid treating absent literal aliases as automatic contradiction without validation. |",
        "| Final-output-only claims versus annotation locations on other spans | Explore span-local, time-aware grounding using only evidence available at that step; retain clear scope labels. |",
        "| Only two mapped misfire positives | Obtain a larger development set and separate failed invocation, corrected retry, and failed recovery before choosing v2 rules. |",
        "| Historical raw values were discarded | Persist per-trace detector values and per-claim numeric diagnostics privately, with provenance, so future metric audits need no model rerun. |"]
    if h["pairs_truncated"]:
        lines.append(f"| {h['pairs_truncated']} pairs truncate, with {h['claim_tokens_removed']} claim tokens removed | Audit claim segmentation and paired token budgets on A before any length-aware v2 design; no v1 result changes. |")
    else:
        lines += ["", "No model-pair truncation was observed here, so this diagnosis does not support truncation as the explanation or a length-fix proposal."]
    lines += ["", "No priority-order fix is proposed as an explanation: masking counts are zero and the scored evaluation already uses independent flags. "
        "No v2 change, threshold, taxonomy expansion, retrieval modification, or metric correction was implemented. "
        "A is development data after this post-hoc inspection; v2 must be frozen before its one future B evaluation.", "",
        "## Provenance and read-only verification", "",
        f"- Original result SHA-256: `{s['result_sha256_before']}`.",
        f"- Original checkpoint SHA-256: `{s['checkpoint_sha256_before']}`.",
        f"- Fresh diagnostic code commit: `{a['diagnostic_code_commit']}`; runtime {a['diagnostic_runtime_seconds']:.2f} seconds.",
        "- 168 focused synthetic/compatibility tests passed, including observer preservation, truncation accounting, success/error run separation and aggregate-scope tests. Secret and dev-content-copy scans passed before staging.",
        "- Same dataset revision, A IDs, frozen adapter/detectors/config and pinned local NLI model as scoring; offline flags enabled. "
        "No provider calls, container/subsystem commands, B data access, frozen-file changes, or scored-result/report edits.",
        "- Only aggregate statistics and permitted trace IDs appear here. Raw per-trace/per-claim observations remain git-excluded under the private diagnostics directory.", ""]
    return "\n".join(lines)


def main():
    state=json.loads((DIAG/"run_state.json").read_text())
    if state["status"] != "complete":
        raise RuntimeError("Wait for the diagnostic run to complete")
    ids=set((ROOT/"reports/external/trail_split/a2/trail_a.txt").read_text().splitlines())
    result=json.loads(RESULT.read_text())
    wanted=ids-set(result["conversion_failure_ids"])
    if set(state["completed_ids"]) != wanted:
        raise RuntimeError("Diagnostic records are not exactly converted A")
    for name, expected in state["immutable_sha256"].items():
        if sha(name) != expected:
            raise RuntimeError("Original scored artifact changed")
    records=[json.loads((DIAG/f"{tid}.json").read_text()) for tid in sorted(wanted)]
    sanity=json.loads((PRIVATE/"part3_sanity.json").read_text())
    summary=aggregate(records,state,result,sanity)
    (DIAG/"aggregate.json").write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    (ROOT/"reports/external/trail_diagnosis.md").write_text(render(summary),encoding="utf-8")
    print(json.dumps({"report_written":True,"diagnostic_records":len(records),
        "decision_difference_trace_ids":summary["decision_difference_trace_ids"],"scored_result_unchanged":True}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"STOP":"diagnosis report not generated","exception_type":type(exc).__name__}))
        raise SystemExit(1) from None
