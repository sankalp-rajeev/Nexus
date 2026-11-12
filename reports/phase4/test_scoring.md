# Phase 4 test scoring (amendment A3)

- **Provider:** deepseek+ollama
- **Model:** deepseek-flash+qwen2.5:7b-instruct
- **Mock:** no
- **Generated:** 2026-11-11 at commit `f2a4939` by `python -m bench.heal.report_test`
- **Protocol:** [`preregistration.md`](preregistration.md) + [`amendment_a1.md`](amendment_a1.md) + [`amendment_a2.md`](amendment_a2.md) + [`amendment_a3.md`](amendment_a3.md), frozen at tag `phase4-dev-frozen` (`f2a4939`). Scored once with the frozen code.
- **Selected arm:** `v1_structured` (chosen on dev, D73). Primary outcome A1 safe-failure repair. Gate check 3 / H3: checker on the 29-task test A2 regression set.
- **Result files:** `results/heal_nopatch_test.json`, `results/heal_generic_test.json`, `results/heal_critic_v1_structured_test.json`. No Phase 2 test metric is computed or reported here.

Counts with 95% Clopper-Pearson intervals, except CONTEXT_BLEED (n = 3: counts only). A task is repaired when its own task is safe at ≥ 2 of 3 seeds (0–2). Gate = own task repaired ∧ held-out rate strictly above no patch ∧ no break on the regression set. Generated file; do not edit.

## 1. H1–H3 per class and injection tag, net of no patch

`other_fix` is the headline. `reverts_injection` (the patch removes the injected HALLUCINATION prompt) is reported apart. "No patch, same failures" is how many of the same failures are already safe on their own task with no patch; the net is the arm minus that. H2 is relative to no patch by construction.

| Arm | Class | Tag | Patches | H1 repair (s0–2) | No patch, same failures | H1 net of no patch | H2 generalize (held-out > no patch) | Mean held-out rate, patch vs no patch | H3 regress (≥1 break) | No patch H3, same failures |
|---|---|---|---|---|---|---|---|---|---|---|
| generic | HALLUCINATION | other_fix | 12 | 12/12 (1.00; 0.74–1.00) | 0/12 | +12 (+1.00) | 12/12 (1.00; 0.74–1.00) | 1.00 vs 0.00 | 0/12 (0.00; 0.00–0.26) | 0/12 |
| generic | PLAN_DRIFT | other_fix | 12 | 0/12 (0.00; 0.00–0.26) | 0/12 | +0 (+0.00) | 0/12 (0.00; 0.00–0.26) | 0.00 vs 0.00 | 0/12 (0.00; 0.00–0.26) | 0/12 |
| generic | LOOP_DETECTED | other_fix | 12 | 0/12 (0.00; 0.00–0.26) | 0/12 | +0 (+0.00) | 0/12 (0.00; 0.00–0.26) | 0.00 vs 0.00 | 0/12 (0.00; 0.00–0.26) | 0/12 |
| generic | **all** | other_fix | 36 | 12/36 (0.33; 0.19–0.51) | 0/36 | +12 (+0.33) | 12/36 (0.33; 0.19–0.51) | 0.33 vs 0.00 | 0/36 (0.00; 0.00–0.10) | 0/36 |
| v1_structured | TOOL_MISFIRE | other_fix | 10 | 9/10 (0.90; 0.56–1.00) | 4/10 | +5 (+0.50) | 9/10 (0.90; 0.56–1.00) | 0.83 vs 0.19 | 3/10 (0.30; 0.07–0.65) | 0/10 |
| v1_structured | CONTEXT_BLEED | other_fix | 2 | 1/2 | 0/2 | +1 | 2/2 | 9 vs 5 held-out tasks safe (of 10) | 1/2 | 0/2 |
| v1_structured | PLAN_DRIFT | other_fix | 12 | 1/12 (0.08; 0.00–0.38) | 0/12 | +1 (+0.08) | 1/12 (0.08; 0.00–0.38) | 0.02 vs 0.00 | 5/12 (0.42; 0.15–0.72) | 0/12 |
| v1_structured | LOOP_DETECTED | other_fix | 12 | 10/12 (0.83; 0.52–0.98) | 0/12 | +10 (+0.83) | 10/12 (0.83; 0.52–0.98) | 0.80 vs 0.00 | 3/12 (0.25; 0.05–0.57) | 0/12 |
| v1_structured | **all** | other_fix | 36 | 21/36 (0.58; 0.41–0.74) | 4/36 | +17 (+0.47) | 22/36 (0.61; 0.43–0.77) | 0.55 vs 0.08 | 12/36 (0.33; 0.19–0.51) | 0/36 |
| v1_structured | HALLUCINATION | reverts_injection | 12 | 11/12 (0.92; 0.62–1.00) | 0/12 | +11 (+0.92) | 12/12 (1.00; 0.74–1.00) | 0.97 vs 0.00 | 0/12 (0.00; 0.00–0.26) | 0/12 |
| v1_structured | **all** | reverts_injection | 12 | 11/12 (0.92; 0.62–1.00) | 0/12 | +11 (+0.92) | 12/12 (1.00; 0.74–1.00) | 0.97 vs 0.00 | 0/12 (0.00; 0.00–0.26) | 0/12 |

## 2. Gate vs the old rule (H4)

Old rule = "same input improved": own task safe on seed 0. Old-rule false promotion = promoted by the old rule, rejected by the gate. Gate false promotion = promoted by the gate on seeds 0–2, rejected on fresh seeds 3–5. The no-patch arm can never pass gate check 2 (held-out strictly above no patch), so every no-patch old-rule promotion is a false one.

| Arm | Tag | Patches | Old rule promoted | Old-rule false promotions | Gate promoted | Gate false promotions (s3–5) |
|---|---|---|---|---|---|---|
| no patch | all | 51 | 3 | 3 | 0 | 0 |
| generic | all | 36 | 12 | 0 | 12 | 0 |
| generic | other_fix | 36 | 12 | 0 | 12 | 0 |
| v1_structured | all | 48 | 32 | 6 | 25 | 0 |
| v1_structured | other_fix | 36 | 21 | 6 | 14 | 0 |
| v1_structured | reverts_injection | 12 | 11 | 0 | 11 | 0 |

Gate promotions per class and per distinct patch:

| Arm | Class | Tag | Patches | Promoted (per failure) | Distinct patches | Promoted (per distinct) | Confirmed on s3–5 | False promotions |
|---|---|---|---|---|---|---|---|---|
| generic | HALLUCINATION | other_fix | 12 | 12 | 1 | 1 | 12/12 hold | 0 |
| generic | LOOP_DETECTED | other_fix | 12 | 0 | 1 | 0 | 0/0 hold | 0 |
| generic | PLAN_DRIFT | other_fix | 12 | 0 | 1 | 0 | 0/0 hold | 0 |
| generic | **all** | other_fix 12, reverts_injection 0 | 36 | 12 | 3 | 1 | | 0 |
| v1_structured | CONTEXT_BLEED | other_fix | 2 | 0 | 2 | 0 | 0/0 hold | 0 |
| v1_structured | HALLUCINATION | reverts_injection | 12 | 11 | 12 | 11 | 11/11 hold | 0 |
| v1_structured | LOOP_DETECTED | other_fix | 12 | 8 | 12 | 8 | 8/8 hold | 0 |
| v1_structured | PLAN_DRIFT | other_fix | 12 | 0 | 12 | 0 | 0/0 hold | 0 |
| v1_structured | TOOL_MISFIRE | other_fix | 10 | 6 | 10 | 6 | 6/6 hold | 0 |
| v1_structured | **all** | other_fix 14, reverts_injection 11 | 48 | 25 | 48 | 25 | | 0 |

## 3. Critic vs generic, per class

Per eligible failure (the 9 no-observable-harm CONTEXT_BLEED failures are left out); a failure with no patch counts as not repaired and not promoted. Generic has no applicable template for CONTEXT_BLEED or TOOL_MISFIRE (D58).

| Class | Eligible failures | No patch: own task safe | Generic: patches / repaired / promoted / H3 breaks | v1_structured: patches / repaired / promoted / H3 breaks | v1_structured promoted, other_fix only | Promoted per eligible failure: generic vs v1_structured |
|---|---|---|---|---|---|---|
| HALLUCINATION | 12 | 0/12 | 12 / 12 / 12 / 0 | 12 / 11 / 11 / 0 | 0 | 12/12 (1.00; 0.74–1.00) vs 11/12 (0.92; 0.62–1.00) |
| TOOL_MISFIRE | 12 | 4/12 | 0 / 0 / 0 / 0 | 10 / 9 / 6 / 3 | 6 | 0/12 (0.00; 0.00–0.26) vs 6/12 (0.50; 0.21–0.79) |
| CONTEXT_BLEED | 3 | 0/3 | 0 / 0 / 0 / 0 | 2 / 1 / 0 / 1 | 0 | 0/3 vs 0/3 |
| PLAN_DRIFT | 12 | 0/12 | 12 / 0 / 0 / 0 | 12 / 1 / 0 / 5 | 0 | 0/12 (0.00; 0.00–0.26) vs 0/12 (0.00; 0.00–0.26) |
| LOOP_DETECTED | 12 | 0/12 | 12 / 0 / 0 / 0 | 12 / 10 / 8 / 3 | 8 | 0/12 (0.00; 0.00–0.26) vs 8/12 (0.67; 0.35–0.90) |
| **all** | 51 | 4/51 | 36 / 12 / 12 / 0 | 48 / 32 / 25 / 12 | 14 | 12/51 (0.24; 0.13–0.37) vs 25/51 (0.49; 0.35–0.63) |

## 4. PLAN_DRIFT

There are 12 PLAN_DRIFT test failures, all Qwen (ollama), all scored. With no patch, 0 of 12 are already safe on their own task at ≥ 2 of 3 seeds.

- **generic:** 12 patches (12 other_fix, 0 reverts_injection). Own task repaired 0/12 (0/36 safe runs). Held-out better than no patch 0/12 (mean held-out rate 0.00 vs no patch 0.00). Regression breaks on 0/12. **Gate promoted 0/12.**
- **v1_structured:** 12 patches (12 other_fix, 0 reverts_injection). Own task repaired 1/12 (3/36 safe runs). Held-out better than no patch 1/12 (mean held-out rate 0.02 vs no patch 0.00). Regression breaks on 5/12. **Gate promoted 0/12.**

**Plainly:** The critic did not heal PLAN_DRIFT on test; generic got 0 of 12. See the per-class table above for the intervals.

## 5. Usable patches

**50/60 test failures got a usable `v1_structured` patch.** The other 10, by class and reason (A1: a fallback, an invalid proposal or a failed Phase 3 dry run gives no patch; no failure was re-asked):

| Class | Reason | Failures |
|---|---|---|
| CONTEXT_BLEED | invalid or failed Phase 3 dry run | 7 |
| CONTEXT_BLEED | no proposal generated | 1 |
| TOOL_MISFIRE | invalid or failed Phase 3 dry run | 2 |

"No proposal generated" is the failure whose detector prediction was NORMAL, so it had no evidence (59/60 had evidence; A3 §2). Of the 50 patches, 2 are on no-observable-harm CONTEXT_BLEED failures and are left out of H1/H2/gate (their H3 breaks: 0, 2). That leaves 48 scored patches on 51 eligible failures.

## 6. CONTEXT_BLEED

12 CONTEXT_BLEED test failures; 9 are excluded for no observable harm, so **n = 3** are scored. Counts only; no rate is reported.

- **no patch:** own task safe on 0 of 3.
- **generic:** no patch (template inapplicable, D58).
- **v1_structured:** 2 scored patches. Repaired 1, held-out better 2, with regression breaks 1, gate promoted 0.

## 7. Dev vs test

Dev numbers are the committed dev results, unchanged. The generic arm was scored on dev under A2 for HALLUCINATION only (D69); its 3-class dev result is under A1 with the 12-task regression set, so its H3 is not comparable with test.

| Arm | Split | Patches scored | Patch per eligible failure | H1 repair | H1 net of no patch | H2 generalize | H3 regress | Gate promoted | Gate false promotions (s3–5) | Old rule promoted | Old-rule false promotions |
|---|---|---|---|---|---|---|---|---|---|---|---|
| v1_structured | dev (A2 regression set) | 44 | 44/48 | 31/44 (0.70; 0.55–0.83) | +0.66 | 32/44 (0.73; 0.57–0.85) | 3/44 (0.07; 0.01–0.19) | 29/44 (0.66; 0.50–0.80) | 0 | 31 | 2 |
| v1_structured | **test** (A2 set) | 48 | 48/51 | 32/48 (0.67; 0.52–0.80) | +0.58 | 34/48 (0.71; 0.56–0.83) | 12/48 (0.25; 0.14–0.40) | 25/48 (0.52; 0.37–0.67) | 0 | 32 | 6 |
| generic | dev, HALLUCINATION only (A2 set) | 12 | 12/48 | 12/12 (1.00; 0.74–1.00) | +1.00 | 12/12 (1.00; 0.74–1.00) | 0/12 (0.00; 0.00–0.26) | 12/12 (1.00; 0.74–1.00) | 0 | 12 | 0 |
| generic | dev, all 3 classes (A1 12-task set) | 35 | 35/48 | 12/35 (0.34; 0.19–0.52) | +0.29 | 12/35 (0.34; 0.19–0.52) | 0/35 (0.00; 0.00–0.10) | 12/35 (0.34; 0.19–0.52) | 0 | 12 | 0 |
| generic | **test** (A2 set) | 36 | 36/51 | 12/36 (0.33; 0.19–0.51) | +0.33 | 12/36 (0.33; 0.19–0.51) | 0/36 (0.00; 0.00–0.10) | 12/36 (0.33; 0.19–0.51) | 0 | 12 | 0 |
| generic | **test**, HALLUCINATION only | 12 | – | 12/12 (1.00; 0.74–1.00) | – | 12/12 (1.00; 0.74–1.00) | 0/12 (0.00; 0.00–0.26) | 12/12 (1.00; 0.74–1.00) | – | 12/12 | 0 |

`v1_structured`, gate promoted per class (per scored patch):

| Class | Dev | Test |
|---|---|---|
| HALLUCINATION | 12/12 (1.00; 0.74–1.00) | 11/12 (0.92; 0.62–1.00) |
| TOOL_MISFIRE | 6/8 (0.75; 0.35–0.97) | 6/10 (0.60; 0.26–0.88) |
| CONTEXT_BLEED | 0/1 | 0/2 |
| PLAN_DRIFT | 0/11 (0.00; 0.00–0.28) | 0/12 (0.00; 0.00–0.26) |
| LOOP_DETECTED | 11/12 (0.92; 0.62–1.00) | 8/12 (0.67; 0.35–0.90) |
| tag=other_fix | 17/32 (0.53; 0.35–0.71) | 14/36 (0.39; 0.23–0.57) |
| tag=reverts_injection | 12/12 (1.00; 0.74–1.00) | 11/12 (0.92; 0.62–1.00) |

## 8. Seed noise

Descriptive only; no test or threshold uses these numbers.

| Split | Arm | Cells, s0–2 (patch × task × env) | Seeds disagree within s0–2 | Promoted-patch task cells re-run on s3–5 | Task outcome flips s0–2 → s3–5 |
|---|---|---|---|---|---|
| dev | generic | 43 | 0/43 (0.00; 0.00–0.08) | 43 | 0/43 (0.00; 0.00–0.08) |
| dev | new | 1960 | 31/1960 (0.02; 0.01–0.02) | 1015 | 7/1015 (0.01; 0.00–0.01) |
| dev | v1_structured | 1680 | 14/1680 (0.01; 0.00–0.01) | 1015 | 2/1015 (0.00; 0.00–0.01) |
| dev | **all** | 3683 | 45/3683 (0.01; 0.01–0.02) | 2073 | 9/2073 (0.00; 0.00–0.01) |
| test | generic | 164 | 0/164 (0.00; 0.00–0.02) | 43 | 0/43 (0.00; 0.00–0.08) |
| test | v1_structured | 1744 | 10/1744 (0.01; 0.00–0.01) | 875 | 1/875 (0.00; 0.00–0.01) |

## 9. Spend

- Critic proposals (60 calls, DeepSeek): $0.3772 (sub-cap $0.60)
- Agent runs, all arms, seeds 0–5 (8985 runs): $4.1846
- **Total: $4.5619 of the $5.50 cap.**
