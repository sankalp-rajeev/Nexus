# TRAIL-A external validation results

This evaluation scored **TRAIL-A only: 64 traces (50 GAIA, 14 SWE Bench)** with the frozen v1 detectors. The original test pool contained 133 traces: six pre-registered GAIA label-join exclusions were removed, and 63 TRAIL-B traces were reserved for a future frozen v2. The 15 dev traces were not evaluated.

**TRAIL-B was neither scored nor inspected for detector development or evaluation.** The earlier mechanical join check is disclosed in A2: it loaded/decoded join data before A2, but no categories, evidence, or descriptions were inspected and no detectors or metrics ran then. After A2, this scorer loaded only A-specific files and did not open shared parquet or any B trace/label file.

Total execution time across recorded attempts was **2415.23 seconds (40.25 minutes)** on `Sankalps-Razer` (Windows-10-10.0.26300-SP0; Python 3.11.14; 32 logical CPUs). It started at `2026-11-13T20:14:45.264184+00:00` and finished at `2026-11-13T20:58:03.047834+00:00`; local date 2026-11-13 (America/New_York).

**Crash-only continuation: 2 recorded attempts.** Completed checkpoints were not rescored.

## Trace-level results

Intervals are Wilson 95% binomial intervals. Undefined metrics have a zero denominator; they are not replaced by zero. Counts include only class-eligible, gold-assessable A traces.

| Class | Evaluated | TP | FP | FN | TN | Precision [95% CI] | Recall [95% CI] |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| HALLUCINATION | 19 | 5 | 14 | 0 | 0 | 26.32% [11.81%, 48.79%] | 100.00% [56.55%, 100.00%] |
| LOOP_DETECTED | 63 | 0 | 0 | 22 | 41 | undefined (denominator 0) | 0.00% [0.00%, 14.87%] |
| TOOL_MISFIRE | 63 | 0 | 0 | 2 | 61 | undefined (denominator 0) | 0.00% [0.00%, 65.76%] |

## Per-source breakdown

| Source | Class | Evaluated | TP | FP | FN | TN | Precision [95% CI] | Recall [95% CI] |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| gaia | HALLUCINATION | 19 | 5 | 14 | 0 | 0 | 26.32% [11.81%, 48.79%] | 100.00% [56.55%, 100.00%] |
| gaia | LOOP_DETECTED | 50 | 0 | 0 | 15 | 35 | undefined (denominator 0) | 0.00% [0.00%, 20.39%] |
| gaia | TOOL_MISFIRE | 50 | 0 | 0 | 2 | 48 | undefined (denominator 0) | 0.00% [0.00%, 65.76%] |
| swe_bench | HALLUCINATION | 0 | 0 | 0 | 0 | 0 | undefined (denominator 0) | undefined (denominator 0) |
| swe_bench | LOOP_DETECTED | 13 | 0 | 0 | 7 | 6 | undefined (denominator 0) | 0.00% [0.00%, 35.43%] |
| swe_bench | TOOL_MISFIRE | 13 | 0 | 0 | 0 | 13 | undefined (denominator 0) | undefined (denominator 0) |

## Reading these results

LOOP_DETECTED fired on 0 of 63 evaluated traces, detecting 0 of 22 mapped positive traces. Precision is undefined when there are no positive predictions; this is not a precision of zero.
TOOL_MISFIRE fired on 0 of 63 evaluated traces, detecting 0 of 2 mapped positive traces. Precision is undefined when there are no positive predictions; this is not a precision of zero.

HALLUCINATION flagged 19 of 19 eligible traces: 5 true positives and 14 false positives. Its recall estimate is based on only 5 mapped positive traces. The Wilson interval and limited eligibility matter when interpreting that estimate; it does not establish recall on abstaining traces.

## Abstentions and exclusions

Abstentions are outside TP/FP/FN/TN and both accuracy-metric denominators. Cohort reservation and the six prior join exclusions are also outside the 64-trace A denominator.

| Source | Class | Type | Reason | Count |
| --- | --- | --- | --- | ---: |
| gaia | HALLUCINATION | abstentions | `no_checkable_claims` | 1 |
| gaia | HALLUCINATION | abstentions | `no_successful_retrieval_text` | 30 |
| swe_bench | HALLUCINATION | abstentions | `no_successful_retrieval_text` | 13 |
| swe_bench | HALLUCINATION | exclusions | `conversion_failure` | 1 |
| swe_bench | LOOP_DETECTED | exclusions | `conversion_failure` | 1 |
| swe_bench | TOOL_MISFIRE | exclusions | `conversion_failure` | 1 |

Overall HALLUCINATION: **19 evaluated, 44 abstentions, 1 other eligibility/gold exclusion(s)**. SWE Bench: 0 evaluated and 13 abstentions.

The six pre-registered exclusions remain:

- `0035f455b3ff2295167a844f04d85d34`: `missing_label_trace_id`.
- `5b5a35053775cbf29701c171e6675853`: `missing_label_trace_id`.
- `5e5dc94e090341c564d582f551a0cddb`: `missing_label_trace_id`.
- `5ec1cd43eb8ae4094e93a4892ff0f06f`: `missing_label_trace_id`.
- `6cc6dc35a28bbed6cfd873756094bc16`: `missing_label_trace_id`.
- `a96c6811716c0473b86a23321db79c34`: `invalid_label_json`.

Within-A conversion failures (pre-registered reason; no trace repair or adapter changes):

- `72822db6e120878d916b515c2501246b`: `conversion_failure`; adapter validation rejected the trace before detector execution.

## What this evaluation can and cannot test

TRAIL's Resource Abuse/Timeout Issues and tool-origin API/Formatting categories are broader than the frozen exact-repeat LOOP/MISFIRE rules. A1 retags the fixed source-reader tools as retrieval; the unchanged LOOP/MISFIRE tool-call helper excludes these retagged spans. Gold tool-origin scope uses the preserved OpenInference TOOL identity, as registered in A1. This adapter/domain mismatch limits interpretation of transfer performance; it was not corrected after seeing results.

HALLUCINATION tests only A traces with successful retrieved text, checkable claims, and the registered readability gate. It cannot measure hallucination detection on abstaining traces. SWE Bench abstentions under the fixed A1 source interface are a coverage limitation, not correct negatives.

PLAN_DRIFT and CONTEXT_BLEED were not scored: no explicit declared plans were captured in the 15 dev traces and no cross-session memory interface was established. No threshold, taxonomy mapping, retrieval rule, or cohort membership was changed after test access.

Exactly registered category terms were used. 225 out-of-mapping annotations across 16 normalized category fingerprints were left unmapped; fingerprint/count audit is in the aggregate JSON. Annotation descriptions/evidence/impact and scalar dataset scores were never read by label mapping.

## Passage length and execution observations

- `6000_plus_chars`: 15 traces, 14815 frozen premise/claim pairs, 2284.49 seconds of trace processing, maximum premise length 600 characters.
- `no_source`: 43 traces, 0 frozen premise/claim pairs, 2.20 seconds of trace processing, maximum premise length 0 characters.
- `under_6000_chars`: 5 traces, 979 frozen premise/claim pairs, 112.97 seconds of trace processing, maximum premise length 600 characters.

These are workload observations, not changes to the method or evidence that passage length caused an accuracy effect. The frozen source/claim extraction and model truncation behavior were used as is. Abstention reasons above describe missing applicable input; no trace was removed for a long page or slow inference. No NLI execution error was recorded: the sole crash was adapter validation of a duplicate span ID. The larger-source bucket required more processing time, but no length-based abstention or error was observed.

## Crash record

The initial attempt stopped after 23 completed traces when the unchanged adapter rejected a duplicate span ID. The scorer was missing the pre-registered conversion-failure handling. The crash-only fix counts adapter validation failures under `conversion_failure`, without deduplicating/repairing input or changing adapter/detector code. The continuation retained completed checkpoints instead of rescoring them.

- Attempt 1: `failed`; failure metadata `{"file": "openinference.py", "function": "to_otlp", "line": 192, "type": "ValueError"}`; code commit `7bbae2307ebfb4ed59b114861054b14969dbb635`; 0 completed before attempt; continuation reason: initial run.
- Attempt 2: `complete`; failure metadata `null`; code commit `7255ea16f000b1273496ff2c07f9d057b6896683`; 23 completed before attempt; continuation reason: Handle pre-registered conversion_failure exclusions for unchanged adapter validation errors; duplicate span ID remains rejected with no repair, mapping or detector changes. Resume 23 completed checkpoints without rescoring them.

## Provenance and checks

- Dataset revision: `b424ce63d5973d5dcd7169b1bc3c07ccdee276d1`.
- Original split manifest SHA-256: `4081a888f8d624b257cc8a6fe1648a0709160b05154bfd5df59967bf6c16f061`.
- A2 manifest SHA-256: `cbc4f1033ece2774237acb4fb12678f9a61754602ad122c3bc1a6654cfc3f795`.
- TRAIL-A ID manifest SHA-256: `1b1c8afba707315f519735f7bb52e8f63ae4d0922334a9f46728688b641346bf`.
- Original/A1 commits: `8bc721b2d404449f1b2de6b1e8461777852cafaa`, `8222003b6495b0d9476fe045dfddcf3089ac8876`.
- A2 commit: `999b28af3285d21da0bb9546d807c9eb1277ba3e`; disclosure commit: `d19cb86bdc2e601aff1282607fb5ae8cc9da4e2b`. Both were verified on the remote before scoring.
- Scoring code commit: `7bbae2307ebfb4ed59b114861054b14969dbb635`.
- Detector config: `phase2-detectors-frozen`; local NLI revision: `6c749ce3425cd33b46d187e45b92bbf96ee12ec7`.
- Pre-flight: committed manifest/ID digests, source revision markers and hashes, six exclusions, empty adapter/detector diff against `8222003`, and 75 frozen-file comparisons passed. Local model files matched the pinned cache.
- Windows PowerShell; exact requested Python; Hugging Face and Transformers offline modes enabled. No provider calls, model downloads, container/subsystem commands, NexusBench TEST access, dashboard edits, or README/RESULTS changes.
- 152 focused synthetic/compatibility tests passed before the initial run; two additional synthetic crash-handling tests passed before continuation. The full 154-test focused suite passed after the fix. The structural loader test proves outside-set labels are never opened/decoded. Secret and dev-content-copy scans precede commits and never load B.

## Optional localization

LOOP/MISFIRE only; conditional on trace TP, unambiguous gold and existing locator; +/-1 completion-order span. HALLUCINATION omitted: no pre-existing unambiguous locator.

- LOOP_DETECTED: 0/0 within +/-1 span; 0 true positives excluded for ambiguous/missing gold location; 0 lacked a locator. Zero denominator means not assessable.
- TOOL_MISFIRE: 0/0 within +/-1 span; 0 true positives excluded for ambiguous/missing gold location; 0 lacked a locator. Zero denominator means not assessable.

**frozen detectors, thresholds unchanged, scored once, reported as is**

Machine-readable results: [trail_a_scored.json](../../results/external/trail_a_scored.json). No gated trace, prompt, output, or annotation description is included.
