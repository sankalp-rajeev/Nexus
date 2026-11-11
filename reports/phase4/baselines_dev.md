# Phase 4 no-critic baselines (dev)

- **Provider:** deepseek+ollama
- **Model:** deepseek-flash+qwen2.5:7b-instruct
- **Mock:** no
- **Generated:** 2026-11-10 at commit `924680c` by `python -m bench.heal.baselines --score`
- **Result files:** [`results/heal_generic_dev.json`](../../results/heal_generic_dev.json), [`results/heal_noise.json`](../../results/heal_noise.json), per-run records in [`results/heal_runs.jsonl`](../../results/heal_runs.jsonl)
- **Pre-registration:** [`preregistration.md`](preregistration.md)

Counts are patches (one per failure). Intervals are 95% Clopper-Pearson. A task passes at >= 2 of 3 runs by the bench-v1.1 checker. Generated file; do not edit.

## H5: no patch, each failure re-run 3x

| Group | Patches | H1 repair | H2 generalize | H3 regress | Gate promoted | Old rule promoted | Old-rule false promotions |
|---|---|---|---|---|---|---|---|
| all | 59 | 22/59 (0.37; 0.25–0.51) | 0/59 (0.00; 0.00–0.06) | 0/59 (0.00; 0.00–0.06) | 0/59 (0.00; 0.00–0.06) | 22/59 (0.37; 0.25–0.51) | 22 |
| fault=CONTEXT_BLEED | 12 | 11/12 (0.92; 0.62–1.00) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 11/12 (0.92; 0.62–1.00) | 11 |
| fault=HALLUCINATION | 12 | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0 |
| fault=LOOP_DETECTED | 12 | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0 |
| fault=PLAN_DRIFT | 11 | 11/11 (1.00; 0.72–1.00) | 0/11 (0.00; 0.00–0.28) | 0/11 (0.00; 0.00–0.28) | 0/11 (0.00; 0.00–0.28) | 11/11 (1.00; 0.72–1.00) | 11 |
| fault=TOOL_MISFIRE | 12 | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0 |

H2 and H3 are 0 by construction for the null patch (it is its own reference).

Seed-level noise (no patch):

- faulted cells (own + held-out tasks): 75; seeds disagree in 0/75 (0.00; 0.00–0.05); at least one seed passes in 29/75 (0.39; 0.28–0.51)
- regression cells: 36; seeds disagree in 0/36 (0.00; 0.00–0.10); all 3 seeds pass in 36/36 (1.00; 0.90–1.00)
- failing task passes on seed 0 alone (what the old rule sees): 22/59 (0.37; 0.25–0.51)

Spend: $0.1872 over 333 runs (1702 LLM calls, 0 run errors).

## Generic fallback templates as patches

Inapplicable (no config key for the template's target): 24 failures (CONTEXT_BLEED, TOOL_MISFIRE). They are not run and are not in the denominators below.

| Group | Patches | H1 repair | H2 generalize | H3 regress | Gate promoted | Old rule promoted | Old-rule false promotions |
|---|---|---|---|---|---|---|---|
| all | 35 | 1/35 (0.03; 0.00–0.15) | 0/35 (0.00; 0.00–0.10) | 0/35 (0.00; 0.00–0.10) | 0/35 (0.00; 0.00–0.10) | 1/35 (0.03; 0.00–0.15) | 1 |
| fault=HALLUCINATION | 12 | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0 |
| fault=LOOP_DETECTED | 12 | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0 |
| fault=PLAN_DRIFT | 11 | 1/11 (0.09; 0.00–0.41) | 0/11 (0.00; 0.00–0.28) | 0/11 (0.00; 0.00–0.28) | 0/11 (0.00; 0.00–0.28) | 1/11 (0.09; 0.00–0.41) | 1 |

By injection tag:

- other_fix: 35 patches, H1 1/35 (0.03; 0.00–0.15)

Net of H5 (same failures, primary outcome): n 35, H1_arm 1, H1_noise_same_failures 11, H1_net -0.2857, fixed_only_with_patch 0, passed_only_without_patch 10

H4 inputs (primary): old_rule_promoted 1, old_rule_false_promotions 1, gate_promoted 0, gate_false_promotions_on_confirmation 0, n_patches 35

Spend (runs not shared with H5): $0.0598 over 276 runs (1464 LLM calls, 0 run errors).

## Secondary outcome (reported, not gated): the fault's own rule did not fire

### H5

| Group | Patches | H1 repair | H2 generalize | H3 regress | Gate promoted | Old rule promoted | Old-rule false promotions |
|---|---|---|---|---|---|---|---|
| all | 59 | 3/59 (0.05; 0.01–0.14) | 0/59 (0.00; 0.00–0.06) | 0/59 (0.00; 0.00–0.06) | 0/59 (0.00; 0.00–0.06) | 3/59 (0.05; 0.01–0.14) | 3 |
| fault=CONTEXT_BLEED | 12 | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0 |
| fault=HALLUCINATION | 12 | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0 |
| fault=LOOP_DETECTED | 12 | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0 |
| fault=PLAN_DRIFT | 11 | 2/11 (0.18; 0.02–0.52) | 0/11 (0.00; 0.00–0.28) | 0/11 (0.00; 0.00–0.28) | 0/11 (0.00; 0.00–0.28) | 2/11 (0.18; 0.02–0.52) | 2 |
| fault=TOOL_MISFIRE | 12 | 1/12 (0.08; 0.00–0.38) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 1/12 (0.08; 0.00–0.38) | 1 |

### Generic

| Group | Patches | H1 repair | H2 generalize | H3 regress | Gate promoted | Old rule promoted | Old-rule false promotions |
|---|---|---|---|---|---|---|---|
| all | 35 | 15/35 (0.43; 0.26–0.61) | 13/35 (0.37; 0.21–0.55) | 0/35 (0.00; 0.00–0.10) | 12/35 (0.34; 0.19–0.52) | 14/35 (0.40; 0.24–0.58) | 2 |
| fault=HALLUCINATION | 12 | 12/12 (1.00; 0.74–1.00) | 12/12 (1.00; 0.74–1.00) | 0/12 (0.00; 0.00–0.26) | 12/12 (1.00; 0.74–1.00) | 12/12 (1.00; 0.74–1.00) | 0 |
| fault=LOOP_DETECTED | 12 | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0 |
| fault=PLAN_DRIFT | 11 | 3/11 (0.27; 0.06–0.61) | 1/11 (0.09; 0.00–0.41) | 0/11 (0.00; 0.00–0.28) | 0/11 (0.00; 0.00–0.28) | 2/11 (0.18; 0.02–0.52) | 2 |
