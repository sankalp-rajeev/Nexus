# Phase 2 baseline — shipped classifier on NexusBench DEV

- **Provider:** none (no LLM)
- **Model:** v3 classifier as shipped: rules + SVM over MiniLM embedding, PatchCore, io_divergence, NLI contradiction (data/classifier_model)
- **Mock:** no
- **Generated:** 2026-11-10 at commit `8207df3` by `python -m bench.phase2_baseline`
- **Result file:** [`results/detect_baseline_dev.json`](../results/detect_baseline_dev.json)

- Split: **dev only** (359 traces). Test is sealed.
- Input: `bench.detector_view` (the pre-registered detector contract).
- Operating point: as shipped (no retraining, no threshold change).
- Intervals: Clopper-Pearson 95%. OTHER_FAILURE excluded from per-class rows.

## All models (n=359)

Headline macro recall (H, CB, PD): **0.3111** over HALLUCINATION, CONTEXT_BLEED, PLAN_DRIFT; secondary macro (H, PD): **0.4667**

| Class | Kind | Support | Recall | Precision |
|---|---|---|---|---|
| HALLUCINATION | headline | 30 | 0.933 (28/30; 0.78-0.99) | 0.137 (28/204; 0.09-0.19) |
| CONTEXT_BLEED | headline | 30 | 0.000 (0/30; 0.00-0.12) | n/a |
| PLAN_DRIFT | headline | 24 | 0.000 (0/24; 0.00-0.14) | n/a |
| TOOL_MISFIRE | rule-defined | 34 | 0.882 (30/34; 0.73-0.97) | 1.000 (30/30; 0.88-1.00) |
| LOOP_DETECTED | rule-defined | 34 | 1.000 (34/34; 0.90-1.00) | 0.850 (34/40; 0.70-0.94) |

Any failure (OTHER_FAILURE counts as a failure): recall 1.000 (237/237; 0.98-1.00), precision 0.660 (237/359; 0.61-0.71); OTHER_FAILURE flagged 1.000 (85/85; 0.96-1.00).

## deepseek-flash (n=171)

Headline macro recall (H, CB, PD): **0.4667** over HALLUCINATION, CONTEXT_BLEED; secondary macro (H, PD): **0.9333**

| Class | Kind | Support | Recall | Precision |
|---|---|---|---|---|
| HALLUCINATION | headline | 30 | 0.933 (28/30; 0.78-0.99) | 0.241 (28/116; 0.17-0.33) |
| CONTEXT_BLEED | headline | 12 | 0.000 (0/12; 0.00-0.26) | n/a |
| PLAN_DRIFT | headline | 0 | n/a | n/a |
| TOOL_MISFIRE | rule-defined | 28 | 1.000 (28/28; 0.88-1.00) | 1.000 (28/28; 0.88-1.00) |
| LOOP_DETECTED | rule-defined | 17 | 1.000 (17/17; 0.80-1.00) | 0.895 (17/19; 0.67-0.99) |

Any failure (OTHER_FAILURE counts as a failure): recall 1.000 (95/95; 0.96-1.00), precision 0.556 (95/171; 0.48-0.63); OTHER_FAILURE flagged 1.000 (8/8; 0.63-1.00).

## qwen2.5:7b-instruct (n=188)

Headline macro recall (H, CB, PD): **0.0** over CONTEXT_BLEED, PLAN_DRIFT; secondary macro (H, PD): **0.0**

| Class | Kind | Support | Recall | Precision |
|---|---|---|---|---|
| HALLUCINATION | headline | 0 | n/a | 0.000 (0/88; 0.00-0.04) |
| CONTEXT_BLEED | headline | 18 | 0.000 (0/18; 0.00-0.19) | n/a |
| PLAN_DRIFT | headline | 24 | 0.000 (0/24; 0.00-0.14) | n/a |
| TOOL_MISFIRE | rule-defined | 6 | 0.333 (2/6; 0.04-0.78) | 1.000 (2/2; 0.16-1.00) |
| LOOP_DETECTED | rule-defined | 17 | 1.000 (17/17; 0.80-1.00) | 0.809 (17/21; 0.58-0.95) |

Any failure (OTHER_FAILURE counts as a failure): recall 1.000 (142/142; 0.97-1.00), precision 0.755 (142/188; 0.69-0.81); OTHER_FAILURE flagged 1.000 (77/77; 0.95-1.00).

## Confusion (all models; rows = label, cols = prediction)

| label \ pred | HALLUCINATION | LOOP_DETECTED | TOOL_MISFIRE |
|---|---|---|---|
| CONTEXT_BLEED | 30 | 0 | 0 |
| HALLUCINATION | 28 | 2 | 0 |
| LOOP_DETECTED | 0 | 34 | 0 |
| NORMAL | 122 | 0 | 0 |
| OTHER_FAILURE | 84 | 1 | 0 |
| PLAN_DRIFT | 24 | 0 | 0 |
| TOOL_MISFIRE | 0 | 4 | 30 |
