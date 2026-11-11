# Phase 2 — TEST results (scored once, frozen detectors)

- **Provider:** local NLI + rules; Gemini judge variant only
- **Model:** cross-encoder/nli-deberta-v3-base
- **Mock:** no
- **Generated:** 2026-11-10 at commit `d293ab6` by `python -m scripts.phase2.score_test`
- **Result file:** [`results/detect_test.json`](../results/detect_test.json)

Test split (357 traces), scored once at `d293ab6` with the code frozen at tag `phase2-detectors-frozen`.

## All models (vs shipped-SVM baseline)

| Class | Kind | Support | Precision | Recall | F1 | Baseline P / R |
|---|---|---|---|---|---|---|
| HALLUCINATION | headline | 30 | 0.811 (30/37; 0.65–0.92) | 1.000 (30/30; 0.88–1.00) | 0.8955 | 0.1226 / 0.8667 |
| CONTEXT_BLEED | headline | 30 | 1.000 (26/26; 0.87–1.00) | 0.867 (26/30; 0.69–0.96) | 0.9286 | None / 0.0 |
| PLAN_DRIFT | headline | 31 | 1.000 (31/31; 0.89–1.00) | 1.000 (31/31; 0.89–1.00) | 1.0 | None / 0.0 |
| TOOL_MISFIRE | rule-defined | 38 | 1.000 (38/38; 0.91–1.00) | 1.000 (38/38; 0.91–1.00) | 1.0 | 1.0 / 0.9211 |
| LOOP_DETECTED | rule-defined | 29 | 1.000 (29/29; 0.88–1.00) | 1.000 (29/29; 0.88–1.00) | 1.0 | 0.8056 / 1.0 |

Headline macro recall (H, CB, PD): **0.9556** over HALLUCINATION, CONTEXT_BLEED, PLAN_DRIFT; secondary (H, PD): **1.0** — baseline 0.2889 / 0.4334

## deepseek-flash

| Class | Kind | Support | Precision | Recall | F1 | Baseline P / R |
|---|---|---|---|---|---|---|
| HALLUCINATION | headline | 30 | 0.811 (30/37; 0.65–0.92) | 1.000 (30/30; 0.88–1.00) | 0.8955 | 0.208 / 0.8667 |
| CONTEXT_BLEED | headline | 18 | 1.000 (15/15; 0.78–1.00) | 0.833 (15/18; 0.59–0.96) | 0.9091 | None / 0.0 |
| PLAN_DRIFT | headline | 0 | n/a | n/a | n/a | None / None |
| TOOL_MISFIRE | rule-defined | 33 | 1.000 (33/33; 0.89–1.00) | 1.000 (33/33; 0.89–1.00) | 1.0 | 1.0 / 1.0 |
| LOOP_DETECTED | rule-defined | 19 | 1.000 (19/19; 0.82–1.00) | 1.000 (19/19; 0.82–1.00) | 1.0 | 0.8261 / 1.0 |

Headline macro recall (H, CB, PD): **0.9166** over HALLUCINATION, CONTEXT_BLEED; secondary (H, PD): **1.0** — baseline 0.4334 / 0.8667

## qwen2.5:7b-instruct

| Class | Kind | Support | Precision | Recall | F1 | Baseline P / R |
|---|---|---|---|---|---|---|
| HALLUCINATION | headline | 0 | n/a | n/a | n/a | 0.0 / None |
| CONTEXT_BLEED | headline | 12 | 1.000 (11/11; 0.72–1.00) | 0.917 (11/12; 0.62–1.00) | 0.9565 | None / 0.0 |
| PLAN_DRIFT | headline | 31 | 1.000 (31/31; 0.89–1.00) | 1.000 (31/31; 0.89–1.00) | 1.0 | None / 0.0 |
| TOOL_MISFIRE | rule-defined | 5 | 1.000 (5/5; 0.48–1.00) | 1.000 (5/5; 0.48–1.00) | 1.0 | 1.0 / 0.4 |
| LOOP_DETECTED | rule-defined | 10 | 1.000 (10/10; 0.69–1.00) | 1.000 (10/10; 0.69–1.00) | 1.0 | 0.7692 / 1.0 |

Headline macro recall (H, CB, PD): **0.9584** over CONTEXT_BLEED, PLAN_DRIFT; secondary (H, PD): **1.0** — baseline 0.0 / 0.0

## Confusion (all models)

| label \ pred | CONTEXT_BLEED | HALLUCINATION | LOOP_DETECTED | NORMAL | PLAN_DRIFT | TOOL_MISFIRE |
|---|---|---|---|---|---|---|
| CONTEXT_BLEED | 26 | 0 | 0 | 4 | 0 | 0 |
| HALLUCINATION | 0 | 30 | 0 | 0 | 0 | 0 |
| LOOP_DETECTED | 0 | 0 | 29 | 0 | 0 | 0 |
| NORMAL | 0 | 7 | 0 | 118 | 0 | 0 |
| OTHER_FAILURE | 0 | 0 | 0 | 74 | 0 | 0 |
| PLAN_DRIFT | 0 | 0 | 0 | 0 | 31 | 0 |
| TOOL_MISFIRE | 0 | 0 | 0 | 0 | 0 | 38 |

## CONTEXT_BLEED vs the pre-registered reference rule

- reference: P 1.000 (24/24; 0.86–1.00), R 0.800 (24/30; 0.61–0.92)
- detector: P 1.000 (26/26; 0.87–1.00), R 0.867 (26/30; 0.69–0.96)

## Variant: Gemini judge for HALLUCINATION (separate)

| Class | Kind | Support | Precision | Recall | F1 |
|---|---|---|---|---|---|
| HALLUCINATION | headline | 30 | 0.811 (30/37; 0.65–0.92) | 1.000 (30/30; 0.88–1.00) | 0.8955 |
| CONTEXT_BLEED | headline | 30 | 1.000 (26/26; 0.87–1.00) | 0.867 (26/30; 0.69–0.96) | 0.9286 |
| PLAN_DRIFT | headline | 31 | 1.000 (31/31; 0.89–1.00) | 1.000 (31/31; 0.89–1.00) | 1.0 |
| TOOL_MISFIRE | rule-defined | 38 | 1.000 (38/38; 0.91–1.00) | 1.000 (38/38; 0.91–1.00) | 1.0 |
| LOOP_DETECTED | rule-defined | 29 | 1.000 (29/29; 0.88–1.00) | 1.000 (29/29; 0.88–1.00) | 1.0 |

Headline macro recall (H, CB, PD): **0.9556** over HALLUCINATION, CONTEXT_BLEED, PLAN_DRIFT; secondary (H, PD): **1.0**

## D5 false alerts per 1,000 NORMAL

- detectors 56.0 (7/125); baseline 1000.0

## D4 external (HaluEval, ToolBench)

- halueval (n=120): binary P 0.546 (47/86; 0.44–0.65), R 0.783 (47/60; 0.66–0.88); HALLUCINATION R 0.783 (47/60; 0.66–0.88); v3 baseline P/R 1.0/0.033
- toolbench (n=100): binary P 1.000 (50/50; 0.93–1.00), R 1.000 (50/50; 0.93–1.00); TOOL_MISFIRE R 1.000 (50/50; 0.93–1.00); v3 baseline P/R 1.0/1.0

## D6 latency

- detectors per trace (CPU): p50 0.4 ms, p95 674.1 ms, max 10314.8 ms
- SDK overhead: 0.01 ms per call

## Registered sensitivity analysis (founding-year tolerance)

- 6 test rows meet the criterion; detector flags 6 of them as HALLUCINATION.
