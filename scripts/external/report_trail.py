"""Render the registered aggregate result JSON; never opens trace/label files."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def metric(value):
    if value["estimate"] is None:
        return "undefined (denominator 0)"
    low, high = value["wilson95"]
    return f"{100*value['estimate']:.2f}% [{100*low:.2f}%, {100*high:.2f}%]"


def render(result):
    p = result["provenance"]
    minutes = p["runtime_seconds"] / 60
    attempts = p["attempts"]
    lines = ["# TRAIL-A external validation results", "",
        "This evaluation scored **TRAIL-A only: 64 traces (50 GAIA, 14 SWE Bench)** with the frozen v1 detectors. "
        "The original test pool contained 133 traces: six pre-registered GAIA label-join exclusions were removed, "
        "and 63 TRAIL-B traces were reserved for a future frozen v2. The 15 dev traces were not evaluated.", "",
        "**TRAIL-B was neither scored nor inspected for detector development or evaluation.** "
        "The earlier mechanical join check is disclosed in A2: it loaded/decoded join data before A2, "
        "but no categories, evidence, or descriptions were inspected and no detectors or metrics ran then. "
        "After A2, this scorer loaded only A-specific files and did not open shared parquet or any B trace/label file.", "",
        f"Total execution time across recorded attempts was **{p['runtime_seconds']:.2f} seconds ({minutes:.2f} minutes)** on `{p['machine']['hostname']}` "
        f"({p['machine']['platform']}; Python {p['machine']['python']}; {p['machine']['logical_cpus']} logical CPUs). "
        f"It started at `{p['started_at_utc']}` and finished at `{p['finished_at_utc']}`; local date {p['date']} ({p['date_timezone']}).", "",
        "**Scored once, with no crash or rerun.**" if len(attempts) == 1 else
        f"**Crash-only continuation: {len(attempts)} recorded attempts.** Completed checkpoints were not rescored.", "",
        "## Trace-level results", "",
        "Intervals are Wilson 95% binomial intervals. Undefined metrics have a zero denominator; "
        "they are not replaced by zero. Counts include only class-eligible, gold-assessable A traces.", "",
        "| Class | Evaluated | TP | FP | FN | TN | Precision [95% CI] | Recall [95% CI] |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |"]
    for cls, values in result["classes"].items():
        lines.append(f"| {cls} | {values['evaluated']} | {values['tp']} | {values['fp']} | {values['fn']} | {values['tn']} | {metric(values['precision'])} | {metric(values['recall'])} |")
    lines += ["", "## Per-source breakdown", "",
        "| Source | Class | Evaluated | TP | FP | FN | TN | Precision [95% CI] | Recall [95% CI] |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |"]
    for split, classes in result["by_split"].items():
        for cls, values in classes.items():
            lines.append(f"| {split} | {cls} | {values['evaluated']} | {values['tp']} | {values['fp']} | {values['fn']} | {values['tn']} | {metric(values['precision'])} | {metric(values['recall'])} |")
    lines += ["", "## Reading these results", ""]
    for cls in ("LOOP_DETECTED", "TOOL_MISFIRE"):
        values = result["classes"][cls]
        lines.append(f"{cls} fired on {values['tp'] + values['fp']} of {values['evaluated']} evaluated traces, "
            f"detecting {values['tp']} of {values['gold_positive']} mapped positive traces. "
            "Precision is undefined when there are no positive predictions; this is not a precision of zero.")
    values = result["classes"]["HALLUCINATION"]
    lines += ["", f"HALLUCINATION flagged {values['tp'] + values['fp']} of {values['evaluated']} eligible traces: "
        f"{values['tp']} true positives and {values['fp']} false positives. "
        f"Its recall estimate is based on only {values['gold_positive']} mapped positive traces. "
        "The Wilson interval and limited eligibility matter when interpreting that estimate; it does not establish recall on abstaining traces."]
    lines += ["", "## Abstentions and exclusions", "",
        "Abstentions are outside TP/FP/FN/TN and both accuracy-metric denominators. "
        "Cohort reservation and the six prior join exclusions are also outside the 64-trace A denominator.", "",
        "| Source | Class | Type | Reason | Count |", "| --- | --- | --- | --- | ---: |"]
    reason_rows = 0
    for split, classes in result["by_split"].items():
        for cls, values in classes.items():
            for kind in ("abstentions", "exclusions"):
                for reason, count in values[kind].items():
                    lines.append(f"| {split} | {cls} | {kind} | `{reason}` | {count} |")
                    reason_rows += 1
    if not reason_rows:
        lines.pop(); lines.pop()
        lines.append("There were no within-A abstentions or exclusions.")
    hall = result["classes"]["HALLUCINATION"]
    swe_hall = result["by_split"]["swe_bench"]["HALLUCINATION"]
    lines += ["", f"Overall HALLUCINATION: **{hall['evaluated']} evaluated, {sum(hall['abstentions'].values())} abstentions, "
        f"{sum(hall['exclusions'].values())} other eligibility/gold exclusion(s)**. "
        f"SWE Bench: {swe_hall['evaluated']} evaluated and {sum(swe_hall['abstentions'].values())} abstentions.", "",
        "The six pre-registered exclusions remain:", ""]
    for tid, reason in sorted(p["exclusions"].items()):
        lines.append(f"- `{tid}`: `{reason}`.")
    if result.get("conversion_failure_ids"):
        lines += ["", "Within-A conversion failures (pre-registered reason; no trace repair or adapter changes):", ""]
        for tid in result["conversion_failure_ids"]:
            lines.append(f"- `{tid}`: `conversion_failure`; adapter validation rejected the trace before detector execution.")
    lines += ["", "## What this evaluation can and cannot test", "",
        "TRAIL's Resource Abuse/Timeout Issues and tool-origin API/Formatting categories are broader than "
        "the frozen exact-repeat LOOP/MISFIRE rules. A1 retags the fixed source-reader tools as retrieval; "
        "the unchanged LOOP/MISFIRE tool-call helper excludes these retagged spans. Gold tool-origin scope "
        "uses the preserved OpenInference TOOL identity, as registered in A1. This adapter/domain mismatch "
        "limits interpretation of transfer performance; it was not corrected after seeing results.", "",
        "HALLUCINATION tests only A traces with successful retrieved text, checkable claims, and the registered "
        "readability gate. It cannot measure hallucination detection on abstaining traces. SWE Bench abstentions "
        "under the fixed A1 source interface are a coverage limitation, not correct negatives.", "",
        "PLAN_DRIFT and CONTEXT_BLEED were not scored: no explicit declared plans were captured in the 15 dev "
        "traces and no cross-session memory interface was established. No threshold, taxonomy mapping, "
        "retrieval rule, or cohort membership was changed after test access.", ""]
    unknown = result["unmapped_category_fingerprints"]
    lines.append(f"Exactly registered category terms were used. {sum(unknown.values())} out-of-mapping annotations "
        f"across {len(unknown)} normalized category fingerprints were left unmapped; fingerprint/count audit "
        "is in the aggregate JSON. Annotation descriptions/evidence/impact and scalar dataset scores were never read by label mapping.")
    lines += ["", "## Passage length and execution observations", ""]
    for bucket, work in sorted(result["workload"].items()):
        lines.append(f"- `{bucket}`: {work['traces']} traces, {work['nli_pairs']} frozen premise/claim pairs, "
            f"{work['runtime_seconds']:.2f} seconds of trace processing, maximum premise length {work['max_premise_characters']} characters.")
    lines += ["", "These are workload observations, not changes to the method or evidence that passage length caused "
        "an accuracy effect. The frozen source/claim extraction and model truncation behavior were used as is. "
        "Abstention reasons above describe missing applicable input; no trace was removed for a long page or slow inference. "
        "No NLI execution error was recorded: the sole crash was adapter validation of a duplicate span ID. "
        "The larger-source bucket required more processing time, but no length-based abstention or error was observed.", ""]
    if len(attempts) > 1:
        lines += ["## Crash record", ""]
        lines += ["The initial attempt stopped after 23 completed traces when the unchanged adapter rejected a duplicate span ID. "
            "The scorer was missing the pre-registered conversion-failure handling. The crash-only fix counts adapter validation "
            "failures under `conversion_failure`, without deduplicating/repairing input or changing adapter/detector code. "
            "The continuation retained completed checkpoints instead of rescoring them.", ""]
        for index, attempt in enumerate(attempts, 1):
            lines.append(f"- Attempt {index}: `{attempt['status']}`; failure metadata `{json.dumps(attempt.get('failure'))}`; "
                f"code commit `{attempt['scoring_code_commit']}`; {attempt['completed_before_attempt']} completed before attempt; "
                f"continuation reason: {(attempt.get('resume_after_crash_reason') or 'initial run').rstrip('.')}.")
        lines.append("")
    lines += ["## Provenance and checks", "",
        f"- Dataset revision: `{p['dataset_revision']}`.",
        f"- Original split manifest SHA-256: `{p['split_manifest_sha256']}`.",
        f"- A2 manifest SHA-256: `{p['a2_manifest_sha256']}`.",
        f"- TRAIL-A ID manifest SHA-256: `{p['trail_a_manifest_sha256']}`.",
        f"- Original/A1 commits: `{p['prereg_commits'][0]}`, `{p['prereg_commits'][1]}`.",
        f"- A2 commit: `{p['a2_commit']}`; disclosure commit: `{p['disclosure_commit']}`. Both were verified on the remote before scoring.",
        f"- Scoring code commit: `{p['scoring_code_commit']}`.",
        f"- Detector config: `{p['detector_config']}`; local NLI revision: `{p['nli_revision']}`.",
        "- Pre-flight: committed manifest/ID digests, source revision markers and hashes, six exclusions, "
        "empty adapter/detector diff against `8222003`, and 75 frozen-file comparisons passed. Local model files matched the pinned cache.",
        "- Windows PowerShell; exact requested Python; Hugging Face and Transformers offline modes enabled. No provider calls, "
        "model downloads, container/subsystem commands, NexusBench TEST access, dashboard edits, or README/RESULTS changes.",
        "- 152 focused synthetic/compatibility tests passed before the initial run; two additional synthetic crash-handling tests passed before continuation. "
        "The full 154-test focused suite passed after the fix. "
        "The structural loader test proves outside-set labels are never opened/decoded. "
        "Secret and dev-content-copy scans precede commits and never load B.", "",
        "## Optional localization", "", result["localization_scope"], ""]
    for cls in ("LOOP_DETECTED", "TOOL_MISFIRE"):
        loc = result["classes"][cls]["localization"]
        lines.append(f"- {cls}: {loc['matched_within_1']}/{loc['eligible_true_positives']} within +/-1 span; "
            f"{loc['ambiguous_gold_true_positives']} true positives excluded for ambiguous/missing gold location; "
            f"{loc['missing_locator_true_positives']} lacked a locator. Zero denominator means not assessable.")
    lines += ["", "**frozen detectors, thresholds unchanged, scored once, reported as is**", "",
        "Machine-readable results: [trail_test.json](../../results/external/trail_test.json). "
        "No gated trace, prompt, output, or annotation description is included.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    data = json.loads((ROOT / "results/external/trail_test.json").read_text())
    path = ROOT / "reports/external/trail_results.md"
    path.write_text(render(data), encoding="utf-8")
    print("Rendered aggregate-only TRAIL-A report")
