"""Render registered B aggregate results; never open B traces or annotations."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.external.report_trail import metric


def rows(mapping):
    output = ["| Version | Class | Cohort | Evaluated | Gold + cohort / evaluated | TP / FP / FN / TN | Precision [Wilson 95%] | Recall [Wilson 95%] |",
        "| --- | --- | ---: | ---: | --- | --- | --- | --- |"]
    for version in ("v1", "v2"):
        for cls in ("LOOP_DETECTED", "TOOL_MISFIRE", "HALLUCINATION"):
            v = mapping[version]["classes"][cls]
            output.append(f"| {version} | {cls} | {v['cohort_denominator']} | {v['evaluated']} | {v['gold_positive_in_cohort_assessable']} / {v['gold_positive']} | {v['tp']} / {v['fp']} / {v['fn']} / {v['tn']} | {metric(v['precision'])} | {metric(v['recall'])} |")
    return output


def render(result, a):
    p = result["provenance"]
    primary = result["mappings"]["primary"]
    old = primary["v1"]["classes"]["LOOP_DETECTED"]
    new = primary["v2"]["classes"]["LOOP_DETECTED"]
    lines = ["# TRAIL-B frozen v1-vs-v2 results", "",
        f"**Primary hypothesis, LOOP on TRAIL-B:** v1 detected **{old['tp']}/{old['gold_positive']}** mapped positive traces "
        f"(precision {metric(old['precision'])}; recall {metric(old['recall'])}). "
        f"V2 detected **{new['tp']}/{new['gold_positive']}** "
        f"(precision {metric(new['precision'])}; recall {metric(new['recall'])}). "
        f"V1 had {old['fp']} false positives; v2 had {new['fp']}. "
        "These are independent per-class flags under the original primary mapping; intervals are Wilson 95%.", "",
        "The registered development expectation for LOOP was approximately 0.8 precision and 0.4 recall. "
        "B estimates and uncertainty are reported as observed; no detector, threshold, mapping, eligibility or exclusion change followed B access. "
        "This report makes no unregistered significance claim or pooled accuracy claim.", "",
        "TRAIL-B contains **63 traces (49 GAIA, 14 SWE Bench)**. Both frozen versions were evaluated on the same cohort "
        "using the same TRAIL-A scorer helpers for gold mapping, independent flags, confusion counts and Wilson intervals. "
        "V1 is phase2-detectors-frozen; v2 is detectors-v2 at 5660480 with C5 final answer only. "
        "The six earlier unjoinable GAIA exclusions remain outside B.", "",
        "## Primary mapping", "",
        "Original mapping: Resource Abuse/Timeout -> LOOP alone; tool-origin API/Formatting -> MISFIRE; "
        "Language-only/Tool-related hallucination -> HALLUCINATION on applicable traces. "
        "The cohort gold-positive count includes assessable positives on abstaining traces; evaluated positives exclude abstentions/exclusions. "
        "Conversion failures cannot be assigned gold labels and are not included in either positive count.", ""]
    lines += rows(primary)
    lines += ["", "## C3 secondary analysis", "",
        "C3 changes only the v2 Resource Abuse/Timeout prediction to LOOP OR TOOL_MISFIRE. "
        "V1's primary mapping, all gold labels and other classes stay unchanged. "
        "C3 was secondary before scoring and is not promoted based on the outcome; its development counts equalled the original mapping.", ""]
    lines += rows(result["mappings"]["C3_secondary"])
    lines += ["", "## Claims hierarchy", ""]
    misfire = primary["v2"]["classes"]["TOOL_MISFIRE"]
    n = misfire["gold_positive_in_cohort_assessable"]
    if n < 5:
        lines.append(f"**TOOL_MISFIRE is descriptive only: {n} assessable gold-positive B traces, fewer than five. No claim is made.** "
            "The tables give its observed counts and intervals; they do not establish transfer accuracy.")
    else:
        lines.append(f"TOOL_MISFIRE has {n} assessable gold-positive B traces. Reaching five does not itself establish a claim; "
            "the observed counts and intervals are reported without a significance or generalization assertion.")
    lines += ["", "**HALLUCINATION is reported without an improvement claim.** Development precision was 24%, recall 100%, "
        "with saturated predictions and performance expected near the eligible-cohort base rate. "
        "The B report retains all abstentions outside metric denominators and makes no recall claim on abstaining traces.", ""]
    for version in ("v1", "v2"):
        h = primary[version]["classes"]["HALLUCINATION"]
        prevalence = f"{100*h['gold_positive']/h['evaluated']:.2f}%" if h["evaluated"] else "undefined"
        lines.append(f"- {version}: {h['evaluated']} eligible traces, {h['tp']+h['fp']} flagged; "
            f"eligible mapped-positive base rate {prevalence}, precision {metric(h['precision'])}, recall {metric(h['recall'])}. "
            f"Of {h['gold_positive_in_cohort_assessable']} assessable cohort positives, only {h['gold_positive']} are evaluated; "
            f"{h['gold_positive_in_cohort_assessable']-h['gold_positive']} lie outside that denominator.")
    lines += ["", "## GAIA / SWE Bench breakdown", "",
        "| Mapping | Source | Version | Class | Cohort / evaluated | Gold + cohort / evaluated | TP / FP / FN / TN | Precision [Wilson 95%] | Recall [Wilson 95%] |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for mapping in ("primary", "C3_secondary"):
        versions = result["mappings"][mapping]
        for version, payload in versions.items():
            for split, classes in payload["by_split"].items():
                for cls, v in classes.items():
                    lines.append(f"| {mapping} | {split} | {version} | {cls} | {v['cohort_denominator']} / {v['evaluated']} | {v['gold_positive_in_cohort_assessable']} / {v['gold_positive']} | {v['tp']} / {v['fp']} / {v['fn']} / {v['tn']} | {metric(v['precision'])} | {metric(v['recall'])} |")
    lines += ["", "## Abstentions and exclusions", "",
        "Abstentions are counted separately, never as negatives or positives. "
        "Evaluated + abstentions + exclusions equals the cohort denominator for every version/class/source. "
        "The same reasons and denominators apply in both mappings.", "",
        "| Version | Source | Class | Type | Reason | Count |", "| --- | --- | --- | --- | --- | ---: |"]
    reasons = 0
    for version, payload in primary.items():
        for split, classes in payload["by_split"].items():
            for cls, v in classes.items():
                for kind in ("abstentions", "exclusions"):
                    for reason, count in v[kind].items():
                        lines.append(f"| {version} | {split} | {cls} | {kind} | `{reason}` | {count} |")
                        reasons += 1
    if not reasons:
        lines.append("| both | all | all | none | none | 0 |")
    for version in ("v1", "v2"):
        h = primary[version]["classes"]["HALLUCINATION"]
        lines += ["", f"{version} HALLUCINATION: {h['evaluated']} evaluated, {sum(h['abstentions'].values())} abstentions, "
            f"{sum(h['exclusions'].values())} exclusions within the 63-trace cohort."]
    if result["conversion_failure_ids"]:
        lines += ["", "Conversion failures (no repair; no detector execution):", ""]
        lines += [f"- `{tid}`: `conversion_failure`." for tid in result["conversion_failure_ids"]]
    unknown = result["unmapped_category_fingerprints"]
    lines += ["", f"{sum(unknown.values())} out-of-mapping annotations across {len(unknown)} normalized category fingerprints "
        "were left unmapped under the original exact category rules. Annotation evidence/descriptions/impact and dataset scalar scores were not used.", "",
        "PLAN_DRIFT and CONTEXT_BLEED are not scored: TRAIL's declared-plan/cross-session-memory signals were not established. "
        "HALLUCINATION evaluates captured final-answer claims with successful readable retrieved text, not all intermediate-span errors. "
        "Abstaining sources are coverage limits, never correct negatives.", "",
        "## Historical v1 TRAIL-A context", "",
        "The previously scored v1 A result below is unchanged. It uses a different cohort and is context only; "
        "the B v1-v2 tables above provide the same-data comparison.", "",
        "| Class | A cohort / evaluated | TP / FP / FN / TN | Precision [Wilson 95%] | Recall [Wilson 95%] |",
        "| --- | --- | --- | --- | --- |"]
    for cls, v in a["classes"].items():
        lines.append(f"| {cls} | 64 / {v['evaluated']} | {v['tp']} / {v['fp']} / {v['fn']} / {v['tn']} | {metric(v['precision'])} | {metric(v['recall'])} |")
    lines += ["", "A had one conversion exclusion. HALLUCINATION evaluated 19 A traces and abstained on 44. "
        "The 15 original dev traces and all A development comparisons are outside the B evaluation.", "",
        "## Guardrail disclosure: v1 stays live", "",
        "Before B scoring, A3 disclosed NexusBench DEV independent-flag macro recall unchanged at 0.953333. "
        "Five-class priority-label macro recall fell 0.953333 -> 0.929804, a 0.023529 drop beyond the 0.02 limit, "
        "because v2 LOOP masks four MISFIRE decisions. False alerts stayed 8.474576 per 1,000 NORMAL. "
        "**V2 is not a live-default candidate; v1 stays live.** No reselection or tuning followed this breach. "
        "NexusBench TEST was not decoded or evaluated.", "",
        "## Pre-flight, execution and provenance", "",
        f"Pre-flight PASS: B ID-list SHA-256 `{p['B_manifest_sha256']}`; dataset revision `{p['dataset_revision']}`; "
        f"v2 code/config identical to `{p['v2_commit']}`; shared v1 freeze and unchanged live paths passed; "
        f"local NLI revision `{p['nli_revision']}` verified byte-for-byte against the pinned cache. "
        "The loader reuses score_trail.load_requested and filters requested IDs before either file open or label JSON decode; synthetic tests cover outside-ID rejection. "
        "The 126 B-specific source files and 63 joins were verified before inference; shared parquet was not opened.", "",
        "The earlier pre-A2 mechanical join check decoded all 148 rows, including future B rows, but inspected no label categories, "
        "evidence or descriptions and ran no detectors or metrics. It was disclosed in d19cb86 and A3. "
        "B was first used for detector evaluation only after the reviewed A3 was committed and pushed.", "",
        f"**Scored once**, with 63 per-trace checkpoints for each version. Runtime **{p['runtime_seconds']:.2f}s** "
        f"({p['runtime_seconds']/60:.2f} minutes), local date {p['date']} ({p['date_timezone']}); "
        f"started `{p['started_at_utc']}`, finished `{p['finished_at_utc']}`. "
        f"Per-version detector runtime: v1 {p['per_version_runtime_seconds']['v1']:.2f}s; v2 {p['per_version_runtime_seconds']['v2']:.2f}s. "
        f"Machine `{p['machine']['hostname']}`, {p['machine']['platform']}, Python {p['machine']['python']}, {p['machine']['logical_cpus']} logical CPUs.", ""]
    lines += ["Shared exact pair memoization and the frozen C4 short-circuit affect per-version timings; "
        "these timings are not a general speed benchmark.", ""]
    if not p["crash_continuation"]:
        lines.append("**No crash, continuation or rerun.**")
    else:
        lines.append("**Crash-only continuation recorded; completed per-version checkpoints were not rescored.**")
        for i, attempt in enumerate(p["attempts"], 1):
            lines.append(f"- Attempt {i}: {attempt['status']}; code `{attempt['scoring_code_commit']}`; "
                f"failure {attempt.get('failure', 'none')}; crash fix/continuation reason: {attempt.get('resume_after_crash_fix_and_reason') or 'initial attempt'}. "
                f"Completed version checkpoints before attempt: {attempt['completed_version_checkpoints_before']}.")
    lines += ["", f"Scoring code commit: `{p['scoring_code_commit']}`. V2 frozen commit: `{p['v2_commit']}`.", "",
        "Pre-registration commits:", ""]
    lines += [f"- {name}: `{commit}`." for name, commit in p["prereg_commits"].items()]
    lines += ["", "All inference used the pinned local model offline (HF_HUB_OFFLINE=1; TRANSFORMERS_OFFLINE=1). "
        "No provider calls, Docker/WSL commands, model downloads, live-default changes or frozen v1 modifications occurred. "
        "Exact pinned-model pair memoization reuses original probabilities; no detector scores were approximated. "
        "Raw checkpoints/cache/logs remain under excluded data/external/trail/b_scoring/. "
        "This report and aggregate JSON contain no gated trace content, prompts, outputs or annotation descriptions.", "",
        "Frozen detectors, thresholds unchanged, scored once, reported as is.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    result = json.loads((ROOT / "results/external/trail_b_scored.json").read_text())
    a = json.loads((ROOT / "results/external/trail_a_scored.json").read_text())
    (ROOT / "reports/external/trail_b_results.md").write_text(render(result, a), encoding="utf-8")
    print(json.dumps({"B_aggregate_report_written": True, "trace_or_label_files_opened": 0}))
