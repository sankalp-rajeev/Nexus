# Phase 2 detectors — DEV report (tuning split)

- **Provider:** local NLI + rules; Gemini judge variant only
- **Model:** cross-encoder/nli-deberta-v3-base; judge gemini-3.5-flash-lite
- **Mock:** no
- **Generated:** 2026-11-10 at commit `bd6a318` by `python -m scripts.phase2.tune_dev`
- **Result file:** [`results/detect_dev.json`](../results/detect_dev.json)

Dev only (359 traces). Test is sealed. Operating points: max dev recall subject to dev precision >= 0.90, else max dev precision.

## Operating points (frozen into services/detectors/thresholds.json)

| Class | Operating point | Dev P | Dev R | Meets P ≥ 0.90 |
|---|---|---|---|---|
| HALLUCINATION | score ≥ 0.5034 | 0.857 (30/35; 0.70–0.95) | 1.000 (30/30; 0.88–1.00) | **no** |
| CONTEXT_BLEED | score ≥ 1.0 | 1.000 (23/23; 0.85–1.00) | 0.767 (23/30; 0.58–0.90) | yes |
| PLAN_DRIFT | ungrounded_any_source | 1.000 (24/24; 0.86–1.00) | 1.000 (24/24; 0.86–1.00) | yes |

## Pipeline, all models (vs shipped-SVM baseline)

| Class | Kind | Support | Precision | Recall | F1 | Baseline P / R |
|---|---|---|---|---|---|---|
| HALLUCINATION | headline | 30 | 0.857 (30/35; 0.70–0.95) | 1.000 (30/30; 0.88–1.00) | 0.9231 | 0.1373 / 0.9333 |
| CONTEXT_BLEED | headline | 30 | 1.000 (23/23; 0.85–1.00) | 0.767 (23/30; 0.58–0.90) | 0.8679 | None / 0.0 |
| PLAN_DRIFT | headline | 24 | 1.000 (24/24; 0.86–1.00) | 1.000 (24/24; 0.86–1.00) | 1.0 | None / 0.0 |
| TOOL_MISFIRE | rule-defined | 34 | 1.000 (34/34; 0.90–1.00) | 1.000 (34/34; 0.90–1.00) | 1.0 | 1.0 / 0.8824 |
| LOOP_DETECTED | rule-defined | 34 | 1.000 (34/34; 0.90–1.00) | 1.000 (34/34; 0.90–1.00) | 1.0 | 0.85 / 1.0 |

Headline macro recall (H, CB, PD): **0.9222** over HALLUCINATION, CONTEXT_BLEED, PLAN_DRIFT; secondary (H, PD): **1.0** — baseline 0.3111 / 0.4667

## Pipeline, deepseek-flash

| Class | Kind | Support | Precision | Recall | F1 | Baseline P / R |
|---|---|---|---|---|---|---|
| HALLUCINATION | headline | 30 | 0.857 (30/35; 0.70–0.95) | 1.000 (30/30; 0.88–1.00) | 0.9231 | 0.2414 / 0.9333 |
| CONTEXT_BLEED | headline | 12 | 1.000 (10/10; 0.69–1.00) | 0.833 (10/12; 0.52–0.98) | 0.9091 | None / 0.0 |
| PLAN_DRIFT | headline | 0 | n/a | n/a | n/a | None / None |
| TOOL_MISFIRE | rule-defined | 28 | 1.000 (28/28; 0.88–1.00) | 1.000 (28/28; 0.88–1.00) | 1.0 | 1.0 / 1.0 |
| LOOP_DETECTED | rule-defined | 17 | 1.000 (17/17; 0.80–1.00) | 1.000 (17/17; 0.80–1.00) | 1.0 | 0.8947 / 1.0 |

Headline macro recall (H, CB, PD): **0.9166** over HALLUCINATION, CONTEXT_BLEED; secondary (H, PD): **1.0** — baseline 0.4667 / 0.9333

## Pipeline, qwen2.5:7b-instruct

| Class | Kind | Support | Precision | Recall | F1 | Baseline P / R |
|---|---|---|---|---|---|---|
| HALLUCINATION | headline | 0 | n/a | n/a | n/a | 0.0 / None |
| CONTEXT_BLEED | headline | 18 | 1.000 (13/13; 0.75–1.00) | 0.722 (13/18; 0.47–0.90) | 0.8387 | None / 0.0 |
| PLAN_DRIFT | headline | 24 | 1.000 (24/24; 0.86–1.00) | 1.000 (24/24; 0.86–1.00) | 1.0 | None / 0.0 |
| TOOL_MISFIRE | rule-defined | 6 | 1.000 (6/6; 0.54–1.00) | 1.000 (6/6; 0.54–1.00) | 1.0 | 1.0 / 0.3333 |
| LOOP_DETECTED | rule-defined | 17 | 1.000 (17/17; 0.80–1.00) | 1.000 (17/17; 0.80–1.00) | 1.0 | 0.8095 / 1.0 |

Headline macro recall (H, CB, PD): **0.8611** over CONTEXT_BLEED, PLAN_DRIFT; secondary (H, PD): **1.0** — baseline 0.0 / 0.0

## False alerts per 1,000 NORMAL traces

- all: **41.0** (5/122)
- deepseek-flash: 65.8 (5/76)
- qwen2.5:7b-instruct: 0.0 (0/46)

## Confusion (all models)

| label \ pred | CONTEXT_BLEED | HALLUCINATION | LOOP_DETECTED | NORMAL | PLAN_DRIFT | TOOL_MISFIRE |
|---|---|---|---|---|---|---|
| CONTEXT_BLEED | 23 | 0 | 0 | 7 | 0 | 0 |
| HALLUCINATION | 0 | 30 | 0 | 0 | 0 | 0 |
| LOOP_DETECTED | 0 | 0 | 34 | 0 | 0 | 0 |
| NORMAL | 0 | 5 | 0 | 117 | 0 | 0 |
| OTHER_FAILURE | 0 | 0 | 0 | 85 | 0 | 0 |
| PLAN_DRIFT | 0 | 0 | 0 | 0 | 24 | 0 |
| TOOL_MISFIRE | 0 | 0 | 0 | 0 | 0 | 34 |

## CONTEXT_BLEED vs the pre-registered reference rule

- reference (≥ 2 'Account tier:' records): P 1.000 (15/15; 0.78–1.00), R 0.500 (15/30; 0.31–0.69)
- detector: P 1.000 (23/23; 0.85–1.00), R 0.767 (23/30; 0.58–0.90)

## Variant: Gemini judge in place of the NLI hallucination detector (separate)

| Class | Kind | Support | Precision | Recall | F1 |
|---|---|---|---|---|---|
| HALLUCINATION | headline | 30 | 0.857 (30/35; 0.70–0.95) | 1.000 (30/30; 0.88–1.00) | 0.9231 |
| CONTEXT_BLEED | headline | 30 | 1.000 (23/23; 0.85–1.00) | 0.767 (23/30; 0.58–0.90) | 0.8679 |
| PLAN_DRIFT | headline | 24 | 1.000 (24/24; 0.86–1.00) | 1.000 (24/24; 0.86–1.00) | 1.0 |
| TOOL_MISFIRE | rule-defined | 34 | 1.000 (34/34; 0.90–1.00) | 1.000 (34/34; 0.90–1.00) | 1.0 |
| LOOP_DETECTED | rule-defined | 34 | 1.000 (34/34; 0.90–1.00) | 1.000 (34/34; 0.90–1.00) | 1.0 |

Headline macro recall (H, CB, PD): **0.9222** over HALLUCINATION, CONTEXT_BLEED, PLAN_DRIFT; secondary (H, PD): **1.0**

## Latency (all detectors per trace, CPU, model warm)

- p50 0.4 ms, p95 695.7 ms, max 10474.6 ms (n=359)

## Spend

- Gemini judge (dev, cumulative ledger): $0.0135. NLI and rules are local and free.

## Registered sensitivity analysis (not used for tuning)

- 4 dev rows are QA founding-year runs that passed the checker with a non-exact year (the ±1.1% numeric tolerance admits ±22 years). They are labelled NORMAL but are wrong answers. The HALLUCINATION detector flags 4 of them. Labels are not changed in this phase; the same mechanical criterion will be applied to test.

## Disclosures (added after scoring, 2026-11-10)

- **On NexusBench, hallucinations are largely detectable by entity absence;
  HaluEval is the harder test.** The entity-presence rule on its own matches
  the full NLI detector on dev (R 1.00, P 0.857), because the injector hides
  the target company's document. See `results/phase2_entity_rule_dev.json` and
  DECISIONS D44.
- **The Gemini judge and the NLI detector are not independent.** They share
  evidence extraction (`retrieved_context()`, including the dev-tuned pronoun
  resolution) and the "skip if no documents" gate. Their agreement is not
  corroboration from independent methods. See
  `results/phase2_independence_audit.json` and DECISIONS D41 and D43.
