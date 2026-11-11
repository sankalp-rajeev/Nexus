# Phase 4 no-critic baselines (dev)

- **Provider:** deepseek+ollama
- **Model:** deepseek-flash+qwen2.5:7b-instruct
- **Mock:** no
- **Generated:** 2026-11-11 at commit `3274692` by `python -m bench.heal.baselines --score`
- **Result files:** [`results/heal_generic_dev.json`](../../results/heal_generic_dev.json), [`results/heal_noise.json`](../../results/heal_noise.json), per-run records in [`results/heal_runs.jsonl`](../../results/heal_runs.jsonl)
- **Protocol:** [`preregistration.md`](preregistration.md) + amendment [`amendment_a1.md`](amendment_a1.md) (primary outcome = A1 safe-failure repair)

Counts are patches (one per failure). Intervals are 95% Clopper-Pearson. A task passes at >= 2 of 3 runs. H3 is checker-based under every definition. Rescored from stored runs; no run was repeated for A1. Generated file; do not edit.

## Old vs new definition, side by side

| Arm | Definition | Patches | H1 repair | H2 generalize | H3 regress | Gate promoted | Old rule promoted | Old-rule false promotions |
|---|---|---|---|---|---|---|---|---|
| H5 no patch | old: checker | 59 | 22/59 (0.37; 0.25–0.51) | 0/59 (0.00; 0.00–0.06) | 0/59 (0.00; 0.00–0.06) | 0/59 (0.00; 0.00–0.06) | 22/59 (0.37; 0.25–0.51) | 22 |
| H5 no patch | new: A1 | 48 | 3/48 (0.06; 0.01–0.17) | 0/48 (0.00; 0.00–0.07) | 0/48 (0.00; 0.00–0.07) | 0/48 (0.00; 0.00–0.07) | 3/48 (0.06; 0.01–0.17) | 3 |
| generic | old: checker | 35 | 1/35 (0.03; 0.00–0.15) | 0/35 (0.00; 0.00–0.10) | 0/35 (0.00; 0.00–0.10) | 0/35 (0.00; 0.00–0.10) | 1/35 (0.03; 0.00–0.15) | 1 |
| generic | new: A1 | 35 | 12/35 (0.34; 0.19–0.52) | 12/35 (0.34; 0.19–0.52) | 0/35 (0.00; 0.00–0.10) | 12/35 (0.34; 0.19–0.52) | 12/35 (0.34; 0.19–0.52) | 0 |

A1 leaves out 11 CONTEXT_BLEED failures whose original trace already passed the checker (no observable harm); the checker rows include them. Generic arm per eligible failure (no applicable patch = not repaired): 12/48 (0.25; 0.14–0.40).

## H5: no patch (A1)

| Group | Patches | H1 repair | H2 generalize | H3 regress | Gate promoted | Old rule promoted | Old-rule false promotions |
|---|---|---|---|---|---|---|---|
| all | 48 | 3/48 (0.06; 0.01–0.17) | 0/48 (0.00; 0.00–0.07) | 0/48 (0.00; 0.00–0.07) | 0/48 (0.00; 0.00–0.07) | 3/48 (0.06; 0.01–0.17) | 3 |
| fault=CONTEXT_BLEED | 1 | 0/1 (0.00; 0.00–0.97) | 0/1 (0.00; 0.00–0.97) | 0/1 (0.00; 0.00–0.97) | 0/1 (0.00; 0.00–0.97) | 0/1 (0.00; 0.00–0.97) | 0 |
| fault=HALLUCINATION | 12 | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0 |
| fault=LOOP_DETECTED | 12 | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0 |
| fault=PLAN_DRIFT | 11 | 2/11 (0.18; 0.02–0.52) | 0/11 (0.00; 0.00–0.28) | 0/11 (0.00; 0.00–0.28) | 0/11 (0.00; 0.00–0.28) | 2/11 (0.18; 0.02–0.52) | 2 |
| fault=TOOL_MISFIRE | 12 | 1/12 (0.08; 0.00–0.38) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 1/12 (0.08; 0.00–0.38) | 1 |

H2 and H3 are 0 by construction for the null patch (it is its own reference).

Seed-level noise (no patch, checker): faulted cells 75, seeds disagree in 0/75 (0.00; 0.00–0.05); regression cells 36, seeds disagree in 0/36 (0.00; 0.00–0.10).

Spend: $0.1872 over 333 runs (1702 LLM calls, 0 run errors).

## Generic fallback templates (A1)

Inapplicable (no config key for the template's target): 24 failures (CONTEXT_BLEED, TOOL_MISFIRE); not run, not in the patch denominators.

| Group | Patches | H1 repair | H2 generalize | H3 regress | Gate promoted | Old rule promoted | Old-rule false promotions |
|---|---|---|---|---|---|---|---|
| all | 35 | 12/35 (0.34; 0.19–0.52) | 12/35 (0.34; 0.19–0.52) | 0/35 (0.00; 0.00–0.10) | 12/35 (0.34; 0.19–0.52) | 12/35 (0.34; 0.19–0.52) | 0 |
| fault=HALLUCINATION | 12 | 12/12 (1.00; 0.74–1.00) | 12/12 (1.00; 0.74–1.00) | 0/12 (0.00; 0.00–0.26) | 12/12 (1.00; 0.74–1.00) | 12/12 (1.00; 0.74–1.00) | 0 |
| fault=LOOP_DETECTED | 12 | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0 |
| fault=PLAN_DRIFT | 11 | 0/11 (0.00; 0.00–0.28) | 0/11 (0.00; 0.00–0.28) | 0/11 (0.00; 0.00–0.28) | 0/11 (0.00; 0.00–0.28) | 0/11 (0.00; 0.00–0.28) | 0 |

By injection tag: other_fix: 35 patches, H1 12/35 (0.34; 0.19–0.52).

Net of H5 (A1): n 35, H1_arm 12, H1_noise_same_failures 2, H1_net 0.2857, fixed_only_with_patch 12, passed_only_without_patch 2

H4 (A1): n_patches 35, old_rule_promoted 12, old_rule_false_promotions 0, gate_promoted 12, gate_false_promotions_on_confirmation 0, confirmation_not_run 12

A gate-promoted patch needs a fresh-seed confirmation (seeds 3-5) before H4 can count gate false promotions. A1 item 4 allows no new runs, so those are listed as not run.

Spend (runs not shared with H5): $0.0598 over 276 runs.

## Secondary outcomes

### checker only (phase4-prereg primary; secondary under A1)

H5:

| Group | Patches | H1 repair | H2 generalize | H3 regress | Gate promoted | Old rule promoted | Old-rule false promotions |
|---|---|---|---|---|---|---|---|
| all | 59 | 22/59 (0.37; 0.25–0.51) | 0/59 (0.00; 0.00–0.06) | 0/59 (0.00; 0.00–0.06) | 0/59 (0.00; 0.00–0.06) | 22/59 (0.37; 0.25–0.51) | 22 |
| fault=CONTEXT_BLEED | 12 | 11/12 (0.92; 0.62–1.00) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 11/12 (0.92; 0.62–1.00) | 11 |
| fault=HALLUCINATION | 12 | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0 |
| fault=LOOP_DETECTED | 12 | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0 |
| fault=PLAN_DRIFT | 11 | 11/11 (1.00; 0.72–1.00) | 0/11 (0.00; 0.00–0.28) | 0/11 (0.00; 0.00–0.28) | 0/11 (0.00; 0.00–0.28) | 11/11 (1.00; 0.72–1.00) | 11 |
| fault=TOOL_MISFIRE | 12 | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0 |

Generic:

| Group | Patches | H1 repair | H2 generalize | H3 regress | Gate promoted | Old rule promoted | Old-rule false promotions |
|---|---|---|---|---|---|---|---|
| all | 35 | 1/35 (0.03; 0.00–0.15) | 0/35 (0.00; 0.00–0.10) | 0/35 (0.00; 0.00–0.10) | 0/35 (0.00; 0.00–0.10) | 1/35 (0.03; 0.00–0.15) | 1 |
| fault=HALLUCINATION | 12 | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0 |
| fault=LOOP_DETECTED | 12 | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0 |
| fault=PLAN_DRIFT | 11 | 1/11 (0.09; 0.00–0.41) | 0/11 (0.00; 0.00–0.28) | 0/11 (0.00; 0.00–0.28) | 0/11 (0.00; 0.00–0.28) | 1/11 (0.09; 0.00–0.41) | 1 |

### fault rule cleared (secondary)

H5:

| Group | Patches | H1 repair | H2 generalize | H3 regress | Gate promoted | Old rule promoted | Old-rule false promotions |
|---|---|---|---|---|---|---|---|
| all | 59 | 3/59 (0.05; 0.01–0.14) | 0/59 (0.00; 0.00–0.06) | 0/59 (0.00; 0.00–0.06) | 0/59 (0.00; 0.00–0.06) | 3/59 (0.05; 0.01–0.14) | 3 |
| fault=CONTEXT_BLEED | 12 | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0 |
| fault=HALLUCINATION | 12 | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0 |
| fault=LOOP_DETECTED | 12 | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0 |
| fault=PLAN_DRIFT | 11 | 2/11 (0.18; 0.02–0.52) | 0/11 (0.00; 0.00–0.28) | 0/11 (0.00; 0.00–0.28) | 0/11 (0.00; 0.00–0.28) | 2/11 (0.18; 0.02–0.52) | 2 |
| fault=TOOL_MISFIRE | 12 | 1/12 (0.08; 0.00–0.38) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 1/12 (0.08; 0.00–0.38) | 1 |

Generic:

| Group | Patches | H1 repair | H2 generalize | H3 regress | Gate promoted | Old rule promoted | Old-rule false promotions |
|---|---|---|---|---|---|---|---|
| all | 35 | 15/35 (0.43; 0.26–0.61) | 13/35 (0.37; 0.21–0.55) | 0/35 (0.00; 0.00–0.10) | 12/35 (0.34; 0.19–0.52) | 14/35 (0.40; 0.24–0.58) | 2 |
| fault=HALLUCINATION | 12 | 12/12 (1.00; 0.74–1.00) | 12/12 (1.00; 0.74–1.00) | 0/12 (0.00; 0.00–0.26) | 12/12 (1.00; 0.74–1.00) | 12/12 (1.00; 0.74–1.00) | 0 |
| fault=LOOP_DETECTED | 12 | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0/12 (0.00; 0.00–0.26) | 0 |
| fault=PLAN_DRIFT | 11 | 3/11 (0.27; 0.06–0.61) | 1/11 (0.09; 0.00–0.41) | 0/11 (0.00; 0.00–0.28) | 0/11 (0.00; 0.00–0.28) | 2/11 (0.18; 0.02–0.52) | 2 |
