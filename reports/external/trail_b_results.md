# TRAIL-B frozen v1-vs-v2 results

**Primary hypothesis, LOOP on TRAIL-B:** v1 detected **0/14** mapped positive traces (precision undefined (denominator 0); recall 0.00% [0.00%, 21.53%]). V2 detected **6/14** (precision 66.67% [35.42%, 87.94%]; recall 42.86% [21.38%, 67.41%]). V1 had 0 false positives; v2 had 3. These are independent per-class flags under the original primary mapping; intervals are Wilson 95%.

The registered development expectation for LOOP was approximately 0.8 precision and 0.4 recall. B estimates and uncertainty are reported as observed; no detector, threshold, mapping, eligibility or exclusion change followed B access. This report makes no unregistered significance claim or pooled accuracy claim.

TRAIL-B contains **63 traces (49 GAIA, 14 SWE Bench)**. Both frozen versions were evaluated on the same cohort using the same TRAIL-A scorer helpers for gold mapping, independent flags, confusion counts and Wilson intervals. V1 is phase2-detectors-frozen; v2 is detectors-v2 at 5660480 with C5 final answer only. The six earlier unjoinable GAIA exclusions remain outside B.

## Primary mapping

Original mapping: Resource Abuse/Timeout -> LOOP alone; tool-origin API/Formatting -> MISFIRE; Language-only/Tool-related hallucination -> HALLUCINATION on applicable traces. The cohort gold-positive count includes assessable positives on abstaining traces; evaluated positives exclude abstentions/exclusions. Conversion failures cannot be assigned gold labels and are not included in either positive count.

| Version | Class | Cohort | Evaluated | Gold + cohort / evaluated | TP / FP / FN / TN | Precision [Wilson 95%] | Recall [Wilson 95%] |
| --- | --- | ---: | ---: | --- | --- | --- | --- |
| v1 | LOOP_DETECTED | 63 | 63 | 14 / 14 | 0 / 0 / 14 / 49 | undefined (denominator 0) | 0.00% [0.00%, 21.53%] |
| v1 | TOOL_MISFIRE | 63 | 63 | 0 / 0 | 0 / 0 / 0 / 63 | undefined (denominator 0) | undefined (denominator 0) |
| v1 | HALLUCINATION | 63 | 11 | 28 / 1 | 1 / 10 / 0 / 0 | 9.09% [1.62%, 37.74%] | 100.00% [20.65%, 100.00%] |
| v2 | LOOP_DETECTED | 63 | 63 | 14 / 14 | 6 / 3 / 8 / 46 | 66.67% [35.42%, 87.94%] | 42.86% [21.38%, 67.41%] |
| v2 | TOOL_MISFIRE | 63 | 63 | 0 / 0 | 0 / 9 / 0 / 54 | 0.00% [0.00%, 29.91%] | undefined (denominator 0) |
| v2 | HALLUCINATION | 63 | 11 | 28 / 1 | 1 / 10 / 0 / 0 | 9.09% [1.62%, 37.74%] | 100.00% [20.65%, 100.00%] |

## C3 secondary analysis

C3 changes only the v2 Resource Abuse/Timeout prediction to LOOP OR TOOL_MISFIRE. V1's primary mapping, all gold labels and other classes stay unchanged. C3 was secondary before scoring and is not promoted based on the outcome; its development counts equalled the original mapping.

| Version | Class | Cohort | Evaluated | Gold + cohort / evaluated | TP / FP / FN / TN | Precision [Wilson 95%] | Recall [Wilson 95%] |
| --- | --- | ---: | ---: | --- | --- | --- | --- |
| v1 | LOOP_DETECTED | 63 | 63 | 14 / 14 | 0 / 0 / 14 / 49 | undefined (denominator 0) | 0.00% [0.00%, 21.53%] |
| v1 | TOOL_MISFIRE | 63 | 63 | 0 / 0 | 0 / 0 / 0 / 63 | undefined (denominator 0) | undefined (denominator 0) |
| v1 | HALLUCINATION | 63 | 11 | 28 / 1 | 1 / 10 / 0 / 0 | 9.09% [1.62%, 37.74%] | 100.00% [20.65%, 100.00%] |
| v2 | LOOP_DETECTED | 63 | 63 | 14 / 14 | 6 / 3 / 8 / 46 | 66.67% [35.42%, 87.94%] | 42.86% [21.38%, 67.41%] |
| v2 | TOOL_MISFIRE | 63 | 63 | 0 / 0 | 0 / 9 / 0 / 54 | 0.00% [0.00%, 29.91%] | undefined (denominator 0) |
| v2 | HALLUCINATION | 63 | 11 | 28 / 1 | 1 / 10 / 0 / 0 | 9.09% [1.62%, 37.74%] | 100.00% [20.65%, 100.00%] |

## Claims hierarchy

**TOOL_MISFIRE is descriptive only: 0 assessable gold-positive B traces, fewer than five. No claim is made.** The tables give its observed counts and intervals; they do not establish transfer accuracy.

**HALLUCINATION is reported without an improvement claim.** Development precision was 24%, recall 100%, with saturated predictions and performance expected near the eligible-cohort base rate. The B report retains all abstentions outside metric denominators and makes no recall claim on abstaining traces.

- v1: 11 eligible traces, 11 flagged; eligible mapped-positive base rate 9.09%, precision 9.09% [1.62%, 37.74%], recall 100.00% [20.65%, 100.00%]. Of 28 assessable cohort positives, only 1 are evaluated; 27 lie outside that denominator.
- v2: 11 eligible traces, 11 flagged; eligible mapped-positive base rate 9.09%, precision 9.09% [1.62%, 37.74%], recall 100.00% [20.65%, 100.00%]. Of 28 assessable cohort positives, only 1 are evaluated; 27 lie outside that denominator.

## GAIA / SWE Bench breakdown

| Mapping | Source | Version | Class | Cohort / evaluated | Gold + cohort / evaluated | TP / FP / FN / TN | Precision [Wilson 95%] | Recall [Wilson 95%] |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| primary | gaia | v1 | HALLUCINATION | 49 / 11 | 22 / 1 | 1 / 10 / 0 / 0 | 9.09% [1.62%, 37.74%] | 100.00% [20.65%, 100.00%] |
| primary | gaia | v1 | LOOP_DETECTED | 49 / 49 | 10 / 10 | 0 / 0 / 10 / 39 | undefined (denominator 0) | 0.00% [0.00%, 27.75%] |
| primary | gaia | v1 | TOOL_MISFIRE | 49 / 49 | 0 / 0 | 0 / 0 / 0 / 49 | undefined (denominator 0) | undefined (denominator 0) |
| primary | swe_bench | v1 | HALLUCINATION | 14 / 0 | 6 / 0 | 0 / 0 / 0 / 0 | undefined (denominator 0) | undefined (denominator 0) |
| primary | swe_bench | v1 | LOOP_DETECTED | 14 / 14 | 4 / 4 | 0 / 0 / 4 / 10 | undefined (denominator 0) | 0.00% [0.00%, 48.99%] |
| primary | swe_bench | v1 | TOOL_MISFIRE | 14 / 14 | 0 / 0 | 0 / 0 / 0 / 14 | undefined (denominator 0) | undefined (denominator 0) |
| primary | gaia | v2 | HALLUCINATION | 49 / 11 | 22 / 1 | 1 / 10 / 0 / 0 | 9.09% [1.62%, 37.74%] | 100.00% [20.65%, 100.00%] |
| primary | gaia | v2 | LOOP_DETECTED | 49 / 49 | 10 / 10 | 6 / 3 / 4 / 36 | 66.67% [35.42%, 87.94%] | 60.00% [31.27%, 83.18%] |
| primary | gaia | v2 | TOOL_MISFIRE | 49 / 49 | 0 / 0 | 0 / 9 / 0 / 40 | 0.00% [0.00%, 29.91%] | undefined (denominator 0) |
| primary | swe_bench | v2 | HALLUCINATION | 14 / 0 | 6 / 0 | 0 / 0 / 0 / 0 | undefined (denominator 0) | undefined (denominator 0) |
| primary | swe_bench | v2 | LOOP_DETECTED | 14 / 14 | 4 / 4 | 0 / 0 / 4 / 10 | undefined (denominator 0) | 0.00% [0.00%, 48.99%] |
| primary | swe_bench | v2 | TOOL_MISFIRE | 14 / 14 | 0 / 0 | 0 / 0 / 0 / 14 | undefined (denominator 0) | undefined (denominator 0) |
| C3_secondary | gaia | v1 | HALLUCINATION | 49 / 11 | 22 / 1 | 1 / 10 / 0 / 0 | 9.09% [1.62%, 37.74%] | 100.00% [20.65%, 100.00%] |
| C3_secondary | gaia | v1 | LOOP_DETECTED | 49 / 49 | 10 / 10 | 0 / 0 / 10 / 39 | undefined (denominator 0) | 0.00% [0.00%, 27.75%] |
| C3_secondary | gaia | v1 | TOOL_MISFIRE | 49 / 49 | 0 / 0 | 0 / 0 / 0 / 49 | undefined (denominator 0) | undefined (denominator 0) |
| C3_secondary | swe_bench | v1 | HALLUCINATION | 14 / 0 | 6 / 0 | 0 / 0 / 0 / 0 | undefined (denominator 0) | undefined (denominator 0) |
| C3_secondary | swe_bench | v1 | LOOP_DETECTED | 14 / 14 | 4 / 4 | 0 / 0 / 4 / 10 | undefined (denominator 0) | 0.00% [0.00%, 48.99%] |
| C3_secondary | swe_bench | v1 | TOOL_MISFIRE | 14 / 14 | 0 / 0 | 0 / 0 / 0 / 14 | undefined (denominator 0) | undefined (denominator 0) |
| C3_secondary | gaia | v2 | HALLUCINATION | 49 / 11 | 22 / 1 | 1 / 10 / 0 / 0 | 9.09% [1.62%, 37.74%] | 100.00% [20.65%, 100.00%] |
| C3_secondary | gaia | v2 | LOOP_DETECTED | 49 / 49 | 10 / 10 | 6 / 3 / 4 / 36 | 66.67% [35.42%, 87.94%] | 60.00% [31.27%, 83.18%] |
| C3_secondary | gaia | v2 | TOOL_MISFIRE | 49 / 49 | 0 / 0 | 0 / 9 / 0 / 40 | 0.00% [0.00%, 29.91%] | undefined (denominator 0) |
| C3_secondary | swe_bench | v2 | HALLUCINATION | 14 / 0 | 6 / 0 | 0 / 0 / 0 / 0 | undefined (denominator 0) | undefined (denominator 0) |
| C3_secondary | swe_bench | v2 | LOOP_DETECTED | 14 / 14 | 4 / 4 | 0 / 0 / 4 / 10 | undefined (denominator 0) | 0.00% [0.00%, 48.99%] |
| C3_secondary | swe_bench | v2 | TOOL_MISFIRE | 14 / 14 | 0 / 0 | 0 / 0 / 0 / 14 | undefined (denominator 0) | undefined (denominator 0) |

## Abstentions and exclusions

Abstentions are counted separately, never as negatives or positives. Evaluated + abstentions + exclusions equals the cohort denominator for every version/class/source. The same reasons and denominators apply in both mappings.

| Version | Source | Class | Type | Reason | Count |
| --- | --- | --- | --- | --- | ---: |
| v1 | gaia | HALLUCINATION | abstentions | `no_successful_retrieval_text` | 38 |
| v1 | swe_bench | HALLUCINATION | abstentions | `no_successful_retrieval_text` | 14 |
| v2 | gaia | HALLUCINATION | abstentions | `no_successful_retrieval_text` | 38 |
| v2 | swe_bench | HALLUCINATION | abstentions | `no_successful_retrieval_text` | 14 |

v1 HALLUCINATION: 11 evaluated, 52 abstentions, 0 exclusions within the 63-trace cohort.

v2 HALLUCINATION: 11 evaluated, 52 abstentions, 0 exclusions within the 63-trace cohort.

230 out-of-mapping annotations across 20 normalized category fingerprints were left unmapped under the original exact category rules. Annotation evidence/descriptions/impact and dataset scalar scores were not used.

PLAN_DRIFT and CONTEXT_BLEED are not scored: TRAIL's declared-plan/cross-session-memory signals were not established. HALLUCINATION evaluates captured final-answer claims with successful readable retrieved text, not all intermediate-span errors. Abstaining sources are coverage limits, never correct negatives.

## Historical v1 TRAIL-A context

The previously scored v1 A result below is unchanged. It uses a different cohort and is context only; the B v1-v2 tables above provide the same-data comparison.

| Class | A cohort / evaluated | TP / FP / FN / TN | Precision [Wilson 95%] | Recall [Wilson 95%] |
| --- | --- | --- | --- | --- |
| HALLUCINATION | 64 / 19 | 5 / 14 / 0 / 0 | 26.32% [11.81%, 48.79%] | 100.00% [56.55%, 100.00%] |
| LOOP_DETECTED | 64 / 63 | 0 / 0 / 22 / 41 | undefined (denominator 0) | 0.00% [0.00%, 14.87%] |
| TOOL_MISFIRE | 64 / 63 | 0 / 0 / 2 / 61 | undefined (denominator 0) | 0.00% [0.00%, 65.76%] |

A had one conversion exclusion. HALLUCINATION evaluated 19 A traces and abstained on 44. The 15 original dev traces and all A development comparisons are outside the B evaluation.

## Guardrail disclosure: v1 stays live

Before B scoring, A3 disclosed NexusBench DEV independent-flag macro recall unchanged at 0.953333. Five-class priority-label macro recall fell 0.953333 -> 0.929804, a 0.023529 drop beyond the 0.02 limit, because v2 LOOP masks four MISFIRE decisions. False alerts stayed 8.474576 per 1,000 NORMAL. **V2 is not a live-default candidate; v1 stays live.** No reselection or tuning followed this breach. NexusBench TEST was not decoded or evaluated.

## Pre-flight, execution and provenance

Pre-flight PASS: B ID-list SHA-256 `7c100a724edd4faabf27ce4b5d84b469d72ae474d6645f496c998c806dbfc72f`; dataset revision `b424ce63d5973d5dcd7169b1bc3c07ccdee276d1`; v2 code/config identical to `5660480673c8a4b3b1f2dbbd0dad6b2438ea3284`; shared v1 freeze and unchanged live paths passed; local NLI revision `6c749ce3425cd33b46d187e45b92bbf96ee12ec7` verified byte-for-byte against the pinned cache. The loader reuses score_trail.load_requested and filters requested IDs before either file open or label JSON decode; synthetic tests cover outside-ID rejection. The 126 B-specific source files and 63 joins were verified before inference; shared parquet was not opened.

The earlier pre-A2 mechanical join check decoded all 148 rows, including future B rows, but inspected no label categories, evidence or descriptions and ran no detectors or metrics. It was disclosed in d19cb86 and A3. B was first used for detector evaluation only after the reviewed A3 was committed and pushed.

**Scored once**, with 63 per-trace checkpoints for each version. Runtime **1869.70s** (31.16 minutes), local date 2026-11-13 (America/New_York); started `2026-11-13T23:16:25.667453+00:00`, finished `2026-11-13T23:47:35.374094+00:00`. Per-version detector runtime: v1 1856.87s; v2 0.94s. Machine `Sankalps-Razer`, Windows-10-10.0.26300-SP0, Python 3.11.14, 32 logical CPUs.

Shared exact pair memoization and the frozen C4 short-circuit affect per-version timings; these timings are not a general speed benchmark.

**No crash, continuation or rerun.**

Scoring code commit: `1f6b25e75c52509cb42eea8f8400968d3339c28d`. V2 frozen commit: `5660480673c8a4b3b1f2dbbd0dad6b2438ea3284`.

Pre-registration commits:

- A1: `8222003b6495b0d9476fe045dfddcf3089ac8876`.
- A2: `999b28af3285d21da0bb9546d807c9eb1277ba3e`.
- A3: `0f0eda0d3d8c94ce0053cc30eb86489bb1f6875b`.
- disclosure: `d19cb86bdc2e601aff1282607fb5ae8cc9da4e2b`.
- original: `8bc721b2d404449f1b2de6b1e8461777852cafaa`.

All inference used the pinned local model offline (HF_HUB_OFFLINE=1; TRANSFORMERS_OFFLINE=1). No provider calls, Docker/WSL commands, model downloads, live-default changes or frozen v1 modifications occurred. Exact pinned-model pair memoization reuses original probabilities; no detector scores were approximated. Raw checkpoints/cache/logs remain under excluded data/external/trail/b_scoring/. This report and aggregate JSON contain no gated trace content, prompts, outputs or annotation descriptions.

Frozen detectors, thresholds unchanged, scored once, reported as is.
