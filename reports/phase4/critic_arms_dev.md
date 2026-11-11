# Phase 4 critic arms on dev (amendment A2)

- **Provider:** deepseek+ollama
- **Model:** deepseek-flash+qwen2.5:7b-instruct
- **Mock:** no
- **Generated:** 2026-11-11 at commit `0feb984` by `python -m bench.heal.report_a2`
- **Protocol:** [`preregistration.md`](preregistration.md) + [`amendment_a1.md`](amendment_a1.md) + [`amendment_a2.md`](amendment_a2.md). Primary outcome: A1 safe-failure repair. Gate check 3 / H3: checker on the 29-task A2 regression set.
- **Result files:** `results/heal_generic_a2_dev.json`, `results/heal_critic_new_dev.json`, `results/heal_critic_v1_structured_dev.json`, `results/heal_selection_dev.json`, `results/heal_h6_dev.json`, `results/heal_seed_noise_dev.json`. Dev only; the test split was not touched.

Counts with 95% Clopper-Pearson intervals. A task passes at ≥ 2 of 3 seeds. A distinct patch (fault, diff hash) meets a good outcome only if it meets it on every failure it was applied to, and a bad one if it happens on any. Generated file; do not edit.

## Arms (A1 outcome, A2 regression set)

The generic row covers only the 12 HALLUCINATION patches re-scored under A2 (amendment A2 item 3). Every critic-arm HALLUCINATION patch is a whole-prompt replacement and is tagged `reverts_injection`; the headline is `other_fix`.

| Arm | Slice | Unit | n | H1 repair | H2 generalize | H3 regress | Gate promoted | Gate false promotions (s3–5) | Old-rule promoted | Old-rule false promotions | Harmful own-pass |
|---|---|---|---|---|---|---|---|---|---|---|---|
| generic | all | per failure | 12 | 12/12 (1.00; 0.74–1.00) | 12/12 (1.00; 0.74–1.00) | 0/12 (0.00; 0.00–0.26) | 12/12 (1.00; 0.74–1.00) | 0 (12 confirmed) | 12/12 | 0 | 0 |
| generic | all | per distinct patch | 1 (covers 12, max 12/patch) | 1/1 | 1/1 | 0/1 | 1/1 | 0 | – | 0 | 0 |
| generic | tag=other_fix | per failure | 12 | 12/12 (1.00; 0.74–1.00) | 12/12 (1.00; 0.74–1.00) | 0/12 (0.00; 0.00–0.26) | 12/12 (1.00; 0.74–1.00) | 0 (12 confirmed) | 12/12 | 0 | 0 |
| generic | tag=other_fix | per distinct patch | 1 (covers 12, max 12/patch) | 1/1 | 1/1 | 0/1 | 1/1 | 0 | – | 0 | 0 |
| generic | fault=HALLUCINATION | per failure | 12 | 12/12 (1.00; 0.74–1.00) | 12/12 (1.00; 0.74–1.00) | 0/12 (0.00; 0.00–0.26) | 12/12 (1.00; 0.74–1.00) | 0 (12 confirmed) | 12/12 | 0 | 0 |
| generic | fault=HALLUCINATION | per distinct patch | 1 (covers 12, max 12/patch) | 1/1 | 1/1 | 0/1 | 1/1 | 0 | – | 0 | 0 |
| new | all | per failure | 47 | 33/47 (0.70; 0.55–0.83) | 33/47 (0.70; 0.55–0.83) | 1/47 (0.02; 0.00–0.11) | 29/47 (0.62; 0.46–0.75) | 0 (29 confirmed) | 30/47 | 3 | 1 |
| new | all | per distinct patch | 47 (covers 47, max 1/patch) | 33/47 | 33/47 | 1/47 | 29/47 | 0 | – | 3 | 1 |
| new | tag=other_fix | per failure | 35 | 23/35 (0.66; 0.48–0.81) | 23/35 (0.66; 0.48–0.81) | 1/35 (0.03; 0.00–0.15) | 20/35 (0.57; 0.39–0.74) | 0 (20 confirmed) | 21/35 | 3 | 1 |
| new | tag=other_fix | per distinct patch | 35 (covers 35, max 1/patch) | 23/35 | 23/35 | 1/35 | 20/35 | 0 | – | 3 | 1 |
| new | tag=reverts_injection | per failure | 12 | 10/12 (0.83; 0.52–0.98) | 10/12 (0.83; 0.52–0.98) | 0/12 (0.00; 0.00–0.26) | 9/12 (0.75; 0.43–0.95) | 0 (9 confirmed) | 9/12 | 0 | 0 |
| new | tag=reverts_injection | per distinct patch | 12 (covers 12, max 1/patch) | 10/12 | 10/12 | 0/12 | 9/12 | 0 | – | 0 | 0 |
| new | fault=CONTEXT_BLEED | per failure | 1 | 1/1 (1.00; 0.03–1.00) | 0/1 (0.00; 0.00–0.97) | 0/1 (0.00; 0.00–0.97) | 0/1 (0.00; 0.00–0.97) | 0 (0 confirmed) | 1/1 | 1 | 0 |
| new | fault=CONTEXT_BLEED | per distinct patch | 1 (covers 1, max 1/patch) | 1/1 | 0/1 | 0/1 | 0/1 | 0 | – | 1 | 0 |
| new | fault=HALLUCINATION | per failure | 12 | 10/12 (0.83; 0.52–0.98) | 10/12 (0.83; 0.52–0.98) | 0/12 (0.00; 0.00–0.26) | 9/12 (0.75; 0.43–0.95) | 0 (9 confirmed) | 9/12 | 0 | 0 |
| new | fault=HALLUCINATION | per distinct patch | 12 (covers 12, max 1/patch) | 10/12 | 10/12 | 0/12 | 9/12 | 0 | – | 0 | 0 |
| new | fault=LOOP_DETECTED | per failure | 11 | 9/11 (0.82; 0.48–0.98) | 9/11 (0.82; 0.48–0.98) | 1/11 (0.09; 0.00–0.41) | 7/11 (0.64; 0.31–0.89) | 0 (7 confirmed) | 8/11 | 2 | 1 |
| new | fault=LOOP_DETECTED | per distinct patch | 11 (covers 11, max 1/patch) | 9/11 | 9/11 | 1/11 | 7/11 | 0 | – | 2 | 1 |
| new | fault=PLAN_DRIFT | per failure | 11 | 1/11 (0.09; 0.00–0.41) | 2/11 (0.18; 0.02–0.52) | 0/11 (0.00; 0.00–0.28) | 1/11 (0.09; 0.00–0.41) | 0 (1 confirmed) | 0/11 | 0 | 0 |
| new | fault=PLAN_DRIFT | per distinct patch | 11 (covers 11, max 1/patch) | 1/11 | 2/11 | 0/11 | 1/11 | 0 | – | 0 | 0 |
| new | fault=TOOL_MISFIRE | per failure | 12 | 12/12 (1.00; 0.74–1.00) | 12/12 (1.00; 0.74–1.00) | 0/12 (0.00; 0.00–0.26) | 12/12 (1.00; 0.74–1.00) | 0 (12 confirmed) | 12/12 | 0 | 0 |
| new | fault=TOOL_MISFIRE | per distinct patch | 12 (covers 12, max 1/patch) | 12/12 | 12/12 | 0/12 | 12/12 | 0 | – | 0 | 0 |
| v1_structured | all | per failure | 44 | 31/44 (0.70; 0.55–0.83) | 32/44 (0.73; 0.57–0.85) | 3/44 (0.07; 0.01–0.19) | 29/44 (0.66; 0.50–0.80) | 0 (29 confirmed) | 31/44 | 2 | 2 |
| v1_structured | all | per distinct patch | 44 (covers 44, max 1/patch) | 31/44 | 32/44 | 3/44 | 29/44 | 0 | – | 2 | 2 |
| v1_structured | tag=other_fix | per failure | 32 | 19/32 (0.59; 0.41–0.76) | 20/32 (0.62; 0.44–0.79) | 3/32 (0.09; 0.02–0.25) | 17/32 (0.53; 0.35–0.71) | 0 (17 confirmed) | 19/32 | 2 | 2 |
| v1_structured | tag=other_fix | per distinct patch | 32 (covers 32, max 1/patch) | 19/32 | 20/32 | 3/32 | 17/32 | 0 | – | 2 | 2 |
| v1_structured | tag=reverts_injection | per failure | 12 | 12/12 (1.00; 0.74–1.00) | 12/12 (1.00; 0.74–1.00) | 0/12 (0.00; 0.00–0.26) | 12/12 (1.00; 0.74–1.00) | 0 (12 confirmed) | 12/12 | 0 | 0 |
| v1_structured | tag=reverts_injection | per distinct patch | 12 (covers 12, max 1/patch) | 12/12 | 12/12 | 0/12 | 12/12 | 0 | – | 0 | 0 |
| v1_structured | fault=CONTEXT_BLEED | per failure | 1 | 0/1 (0.00; 0.00–0.97) | 0/1 (0.00; 0.00–0.97) | 0/1 (0.00; 0.00–0.97) | 0/1 (0.00; 0.00–0.97) | 0 (0 confirmed) | 0/1 | 0 | 0 |
| v1_structured | fault=CONTEXT_BLEED | per distinct patch | 1 (covers 1, max 1/patch) | 0/1 | 0/1 | 0/1 | 0/1 | 0 | – | 0 | 0 |
| v1_structured | fault=HALLUCINATION | per failure | 12 | 12/12 (1.00; 0.74–1.00) | 12/12 (1.00; 0.74–1.00) | 0/12 (0.00; 0.00–0.26) | 12/12 (1.00; 0.74–1.00) | 0 (12 confirmed) | 12/12 | 0 | 0 |
| v1_structured | fault=HALLUCINATION | per distinct patch | 12 (covers 12, max 1/patch) | 12/12 | 12/12 | 0/12 | 12/12 | 0 | – | 0 | 0 |
| v1_structured | fault=LOOP_DETECTED | per failure | 12 | 11/12 (0.92; 0.62–1.00) | 12/12 (1.00; 0.74–1.00) | 1/12 (0.08; 0.00–0.38) | 11/12 (0.92; 0.62–1.00) | 0 (11 confirmed) | 11/12 | 0 | 0 |
| v1_structured | fault=LOOP_DETECTED | per distinct patch | 12 (covers 12, max 1/patch) | 11/12 | 12/12 | 1/12 | 11/12 | 0 | – | 0 | 0 |
| v1_structured | fault=PLAN_DRIFT | per failure | 11 | 0/11 (0.00; 0.00–0.28) | 0/11 (0.00; 0.00–0.28) | 0/11 (0.00; 0.00–0.28) | 0/11 (0.00; 0.00–0.28) | 0 (0 confirmed) | 0/11 | 0 | 0 |
| v1_structured | fault=PLAN_DRIFT | per distinct patch | 11 (covers 11, max 1/patch) | 0/11 | 0/11 | 0/11 | 0/11 | 0 | – | 0 | 0 |
| v1_structured | fault=TOOL_MISFIRE | per failure | 8 | 8/8 (1.00; 0.63–1.00) | 8/8 (1.00; 0.63–1.00) | 2/8 (0.25; 0.03–0.65) | 6/8 (0.75; 0.35–0.97) | 0 (6 confirmed) | 8/8 | 2 | 2 |
| v1_structured | fault=TOOL_MISFIRE | per distinct patch | 8 (covers 8, max 1/patch) | 8/8 | 8/8 | 2/8 | 6/8 | 0 | – | 2 | 2 |

## Gate promotions by class and tag

Promoted on seeds 0–2. `reverts_injection` = the patch removes the injected guessing prompt (HALLUCINATION only), kept out of the headline.

| Arm | Class | Tag | Patches | Promoted (per failure) | Distinct patches | Promoted (per distinct) | Confirmed on s3–5 | False promotions |
|---|---|---|---|---|---|---|---|---|
| generic | HALLUCINATION | other_fix | 12 | 12 | 1 | 1 | 12/12 hold | 0 |
| generic | **all** | other_fix 12, reverts_injection 0 | 12 | 12 | 1 | 1 | | 0 |
| new | CONTEXT_BLEED | other_fix | 1 | 0 | 1 | 0 | 0/0 hold | 0 |
| new | HALLUCINATION | reverts_injection | 12 | 9 | 12 | 9 | 9/9 hold | 0 |
| new | LOOP_DETECTED | other_fix | 11 | 7 | 11 | 7 | 7/7 hold | 0 |
| new | PLAN_DRIFT | other_fix | 11 | 1 | 11 | 1 | 1/1 hold | 0 |
| new | TOOL_MISFIRE | other_fix | 12 | 12 | 12 | 12 | 12/12 hold | 0 |
| new | **all** | other_fix 20, reverts_injection 9 | 47 | 29 | 47 | 29 | | 0 |
| v1_structured | CONTEXT_BLEED | other_fix | 1 | 0 | 1 | 0 | 0/0 hold | 0 |
| v1_structured | HALLUCINATION | reverts_injection | 12 | 12 | 12 | 12 | 12/12 hold | 0 |
| v1_structured | LOOP_DETECTED | other_fix | 12 | 11 | 12 | 11 | 11/11 hold | 0 |
| v1_structured | PLAN_DRIFT | other_fix | 11 | 0 | 11 | 0 | 0/0 hold | 0 |
| v1_structured | TOOL_MISFIRE | other_fix | 8 | 6 | 8 | 6 | 6/6 hold | 0 |
| v1_structured | **all** | other_fix 17, reverts_injection 12 | 44 | 29 | 44 | 29 | | 0 |

## Seed noise (descriptive only)

How often seeds disagree. This is not used by the gate or the selection rule (D72).

| Arm | Cells (patch × task × env), seeds 0–2 | Seeds disagree | of which faulted | of which regression | Promoted-patch task cells re-run on s3–5 | Task outcome flips s0–2 → s3–5 |
|---|---|---|---|---|---|---|
| generic | 43 | 0/43 (0.00; 0.00–0.08) | 0/14 (0.00; 0.00–0.23) | 0/29 (0.00; 0.00–0.12) | 43 | 0/43 (0.00; 0.00–0.08) |
| new | 1960 | 31/1960 (0.02; 0.01–0.02) | 30/336 (0.09; 0.06–0.12) | 1/1624 (0.00; 0.00–0.00) | 1015 | 7/1015 (0.01; 0.00–0.01) |
| v1_structured | 1680 | 14/1680 (0.01; 0.00–0.01) | 9/288 (0.03; 0.01–0.06) | 5/1392 (0.00; 0.00–0.01) | 1015 | 2/1015 (0.00; 0.00–0.01) |

Over the arms in this report (generic HALLUCINATION, `new`, `v1_structured`), the seeds disagree in 45 of 3683 cells (1.2%): 39 of 638 faulted cells (6.1%) and 6 of 3045 regression cells (0.2%). 9 of 2073 task outcomes on promoted patches flip between seeds 0–2 and 3–5. The earlier no-patch runs had 0 of 111. Patched prompts add some within-seed noise, mostly on faulted tasks. But the 2-of-3 task outcome almost never changes on fresh seeds. So the confirmation mostly tests determinism at temperature 0, not robustness, and few gate false promotions are expected by construction. Descriptive only; the selection rule is unchanged.

## Coverage

| Arm | Eligible failures (A1) | Got a patch | No patch (reasons) | H1 per failure (no patch = not repaired) | No-harm bleed excluded (H3 breaks) |
|---|---|---|---|---|---|
| generic | 48 | 12 | 36 (–) | 12/48 (0.25; 0.14–0.40) | 0 (0 with breaks) |
| new | 48 | 47 | 1 (fallback proposal: 1) | 33/48 (0.69; 0.54–0.81) | 9 (4 with breaks) |
| v1_structured | 48 | 44 | 4 (invalid or failed Phase 3 dry run: 3, fallback proposal: 1) | 31/48 (0.65; 0.49–0.78) | 4 (2 with breaks) |

## H4: old rule ("same input improved") vs the gate

Old-rule false promotion: seed 0 of the own task passes but the patch fails check 2 or check 3. Gate false promotion: gate-promoted on seeds 0–2, but check 2 or 3 fails on fresh seeds 3–5.

| Arm | Tag | Patches | Old rule promoted | Old-rule false promotions | Gate promoted | Gate false promotions (s3–5) |
|---|---|---|---|---|---|---|
| generic | all | 12 | 12 | 0 | 12 | 0 |
| generic | other_fix | 12 | 12 | 0 | 12 | 0 |
| new | all | 47 | 30 | 3 | 29 | 0 |
| new | other_fix | 35 | 21 | 3 | 20 | 0 |
| new | reverts_injection | 12 | 9 | 0 | 9 | 0 |
| v1_structured | all | 44 | 31 | 2 | 29 | 0 |
| v1_structured | other_fix | 32 | 19 | 2 | 17 | 0 |
| v1_structured | reverts_injection | 12 | 12 | 0 | 12 | 0 |

## Selection (pre-registered 1f / A1 §3)

| Arm | Gate false promotions (s3–5) | H2 per failure |
|---|---|---|
| new | 0 | 33/47 (0.70) |
| v1_structured | 0 | 32/44 (0.73) |

**Selected: `v1_structured`.**

Tie-break H2 by tag: `new` other_fix 23/35, reverts_injection 10/12; `v1_structured` other_fix 20/32, reverts_injection 12/12. The rule uses every patch, as pre-registered. Read the margin with that in mind: on `other_fix` alone, the headline tag, the order of the two arms can differ.

Per distinct patch the same rule picks `v1_structured` ({'new': {'gate_false_promotions': 0, 'H2': 0.7021}, 'v1_structured': {'gate_false_promotions': 0, 'H2': 0.7273}}).

## H6: judge bias

| Judge | Judged | Unparseable | κ (95% bootstrap) | Agreement | Judge pass / ref fail | Judge fail / ref pass | κ, DeepSeek agent runs | κ, Qwen agent runs |
|---|---|---|---|---|---|---|---|---|
| deepseek-flash | 300 | 0 | 0.5098 (0.2689–0.7196) | 0.9533 | 10 | 4 | 0.2354 | 0.5949 |
| gemini-3.5-flash-lite | 300 | 0 | 0.3304 (0.0842–0.5598) | 0.95 | 14 | 1 | -0.0086 | 0.4375 |

Only 18 of 300 sampled runs fail by the deterministic reference, so kappa is unstable here: raw agreement is high, and the two judges' intervals overlap widely. Read the kappa difference as indicative, not established.

Sample: 300 critic-arm runs, seed `20261110:heal:h6`. Reference: A1 safe-repair rule (faulted runs) or checker (regression runs).

## Test scoring: cost estimate (nothing run)

Arm `v1_structured`. Built from dev measurements only. Nothing was run or read on the test split.

- Dev, measured: critic runs s0-2: 5040 runs, $2.149; no-patch references: 486 runs, $0.226; confirmations s3-5: 3045 runs, $1.839.
- Assumptions: 60 test failures (12 per class, the same rule); 29 regression tasks (all 20 test QA tasks, from the datasheet's 40 QA tasks minus 20 dev, plus 3 per other family); scale 1.017× dev; the same promotion rate as dev (29/44); critic $0.006492/proposal (Phase 3 round 3).
- **Estimate: $4.67** (critic proposals $0.390 + agent runs $4.285), plus about 3.5 h of local Qwen.

This is a planning estimate, not a cap. The test scoring needs its own cap and go-ahead.

## Spend

- Rest-of-phase ledger (critic arms, confirmations, generic confirmations, Gemini probe): $8.5129 over 61592 paid calls.
- H6 ledger: $0.0495 over 356 paid calls. 600 judgments in total; the rest were byte-identical judge inputs, served from the response cache.
- Total $8.5624 of the $9.50 cap (D72). Preparation ledger closed at $0.247 (D67).
