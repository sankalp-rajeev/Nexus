# Phase 2 baseline — shipped classifier on NexusBench DEV

- **Provider:** none (no LLM)
- **Model:** v3 classifier as shipped: rules + SVM over MiniLM embedding, PatchCore, io_divergence, NLI contradiction (data/classifier_model)
- **Mock:** no
- **Generated:** 2026-11-10 at commit `7666a51` by `python -m bench.phase2_baseline`
- **Result file:** [`results/detect_baseline_dev.json`](../results/detect_baseline_dev.json)

- Split: **dev only** (359 traces). Test is sealed.
- Input: `bench.detector_view` (the pre-registered detector contract).
- Operating point: as shipped (no retraining, no threshold change).
- Intervals: Clopper-Pearson 95%. OTHER_FAILURE excluded from per-class rows.

## All models (n=359)

Headline macro recall (H, CB, PD): **0.3111** over HALLUCINATION, CONTEXT_BLEED, PLAN_DRIFT; secondary macro (H, PD): **0.4667**

| Class | Kind | Support | Recall | Precision |
|---|---|---|---|---|
| HALLUCINATION | headline | 30 | 0.933 (28/30; 0.78-0.99) | 0.138 (28/203; 0.09-0.19) |
| CONTEXT_BLEED | headline | 30 | 0.000 (0/30; 0.00-0.12) | n/a |
| PLAN_DRIFT | headline | 20 | 0.000 (0/20; 0.00-0.17) | n/a |
| TOOL_MISFIRE | rule-defined | 27 | 1.000 (27/27; 0.87-1.00) | 1.000 (27/27; 0.87-1.00) |
| LOOP_DETECTED | rule-defined | 33 | 1.000 (33/33; 0.89-1.00) | 0.917 (33/36; 0.78-0.98) |

Any failure (OTHER_FAILURE counts as a failure): recall 1.000 (233/233; 0.98-1.00), precision 0.649 (233/359; 0.60-0.70); OTHER_FAILURE flagged 1.000 (93/93; 0.96-1.00).

## deepseek-flash (n=171)

Headline macro recall (H, CB, PD): **0.4667** over HALLUCINATION, CONTEXT_BLEED; secondary macro (H, PD): **0.9333**

| Class | Kind | Support | Recall | Precision |
|---|---|---|---|---|
| HALLUCINATION | headline | 30 | 0.933 (28/30; 0.78-0.99) | 0.241 (28/116; 0.17-0.33) |
| CONTEXT_BLEED | headline | 12 | 0.000 (0/12; 0.00-0.26) | n/a |
| PLAN_DRIFT | headline | 0 | n/a | n/a |
| TOOL_MISFIRE | rule-defined | 27 | 1.000 (27/27; 0.87-1.00) | 1.000 (27/27; 0.87-1.00) |
| LOOP_DETECTED | rule-defined | 17 | 1.000 (17/17; 0.80-1.00) | 0.895 (17/19; 0.67-0.99) |

Any failure (OTHER_FAILURE counts as a failure): recall 1.000 (95/95; 0.96-1.00), precision 0.556 (95/171; 0.48-0.63); OTHER_FAILURE flagged 1.000 (9/9; 0.66-1.00).

## qwen2.5:7b-instruct (n=188)

Headline macro recall (H, CB, PD): **0.0** over CONTEXT_BLEED, PLAN_DRIFT; secondary macro (H, PD): **0.0**

| Class | Kind | Support | Recall | Precision |
|---|---|---|---|---|
| HALLUCINATION | headline | 0 | n/a | 0.000 (0/87; 0.00-0.04) |
| CONTEXT_BLEED | headline | 18 | 0.000 (0/18; 0.00-0.19) | n/a |
| PLAN_DRIFT | headline | 20 | 0.000 (0/20; 0.00-0.17) | n/a |
| TOOL_MISFIRE | rule-defined | 0 | n/a | n/a |
| LOOP_DETECTED | rule-defined | 16 | 1.000 (16/16; 0.79-1.00) | 0.941 (16/17; 0.71-1.00) |

Any failure (OTHER_FAILURE counts as a failure): recall 1.000 (138/138; 0.97-1.00), precision 0.734 (138/188; 0.66-0.80); OTHER_FAILURE flagged 1.000 (84/84; 0.96-1.00).

## Confusion (all models; rows = label, cols = prediction)

| label \ pred | HALLUCINATION | LOOP_DETECTED | TOOL_MISFIRE |
|---|---|---|---|
| CONTEXT_BLEED | 29 | 1 | 0 |
| HALLUCINATION | 28 | 2 | 0 |
| LOOP_DETECTED | 0 | 33 | 0 |
| NORMAL | 126 | 0 | 0 |
| OTHER_FAILURE | 93 | 0 | 0 |
| PLAN_DRIFT | 20 | 0 | 0 |
| TOOL_MISFIRE | 0 | 0 | 27 |
