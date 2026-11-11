# Phase 4 pre-registration, amendment A2

- **Status:** committed and tagged `phase4-prereg-a2` **before any critic-arm run**. The
  pre-registration ([`preregistration.md`](preregistration.md), tag `phase4-prereg`) and
  amendment A1 ([`amendment_a1.md`](amendment_a1.md), tag `phase4-prereg-a1`) are
  unchanged. Where A2 says nothing, they hold, along with DECISIONS D66 (the 59
  pre-registered failures) and D67 (the $3.00 rest-of-phase cap).
- **Date:** 2026-11-11 · **Branch:** `phase-4-healing`
- **Already run when A2 was written:** the H5 and generic baselines (609 runs) and the
  generic HALLUCINATION confirmation on seeds 3–5 (78 runs), all against the 12-task A1
  regression set. No critic-arm run exists.
- **Code:** `bench/heal/sets.py` (`regression_a2`), `bench/heal/score.py`
  (`summarize_distinct`), `bench/heal/a2.py` (A2 runs and scoring), `bench/heal/h6.py`
  (H6, protocol from A1 §2, unchanged). Tests: `tests/unit/heal/test_a2.py`,
  `tests/unit/heal/test_sets.py`.

## 1. Over-abstention guard: a wider QA regression set

**Why.** Under A1, abstaining counts as a safe repair for HALLUCINATION. Abstaining on
everything is then caught only by check 3 (H3), and the A1 regression set has 3 QA
tasks. An abstain-everything prompt that happens to keep those 3 answered would pass the
gate. The generic HALLUCINATION template ("abstain when unsure") was promoted on all 12
HALLUCINATION failures with exactly this exposure (D68).

**Change.** The QA part of the regression set is widened to **every dev QA task that
passes with no fault**. "Passes with no fault" is the same criterion the A1 set used:
the committed bench-v1.1 uninjected run of the task passed the checker. All 20 dev QA
tasks meet it. The tool, plan and memory tasks are kept as they are. The list is fixed
in [`prereg_sets.json`](prereg_sets.json) as `regression_a2` (29 tasks), and CI checks
that the code reproduces it:

`qa-000, qa-001, qa-002, qa-003, qa-005, qa-006, qa-007, qa-008, qa-009, qa-013, qa-015,
qa-016, qa-021, qa-024, qa-026, qa-029, qa-032, qa-035, qa-037, qa-039, tool-001, tool-022,
tool-024, plan-003, plan-016, plan-017, mem-002, mem-010, mem-029`

The A1 set (`regression`, 12 tasks) is a subset and stays in the file unchanged, so
scores made under A1 are still reproducible.

**Where it applies.** Gate check 3 and H3 for both critic arms, their fresh-seed
confirmations, and the generic re-run in item 3. As before, regression runs use no
environment fault, the failure's provider and the patched deployed config. The no-patch
reference is the same task with no patch, the same provider and the same deployed
config, at seeds 0–2. Those references are run for the 17 new QA tasks. A task that
fails with no patch can't regress, so it is left out for that provider and deployed
config, and the count is reported (`regression_checked`).

Some QA regression tasks are also HALLUCINATION own or held-out tasks. That is allowed:
the regression run has no fault, so the document is present and the task is answerable.

## 2. Report every H metric per failure and per distinct patch

Every H metric (H1, H2, H3, gate promotions, H4 old-rule and gate false promotions,
harmful own-passes) is reported two ways:

- **Per failure,** as pre-registered: one row per failure that received a patch.
- **Per distinct patch:** rows grouped by (fault, diff hash), where the diff hash is
  `ConfigPatch.patch_hash`. The fault is part of the key because for HALLUCINATION the
  same diff runs on a different deployed config. A distinct patch **meets** a good
  outcome (check 1, check 2, promotion) only if it meets it on **every** failure it was
  applied to. It **counts as** a regression, harmful own-pass or false promotion if that
  happens on **any** of them. Each distinct patch's number of failures is reported, and
  so is the largest number for each arm.

**Named case: the generic arm.** Its 12 HALLUCINATION patches are one diff (the
abstention template appended to the deployed prompt). Per failure, it is "12 gate
promotions, 12 confirmed". Per distinct patch, it is **1 distinct patch confirmed on 12
failures**. It shares its held-out and regression runs across all 12, so it is not 12
independent confirmations (D68).

The selection rule (1f, A1 §3) is unchanged and still uses the per-failure counts: the
fewest gate false promotions on fresh seeds, ties broken by higher H2. The per-distinct
counts are reported next to it, and so is whether they would pick the same arm.

## 3. Generic HALLUCINATION patch against the A2 regression set

The generic arm's 12 promoted HALLUCINATION patches (1 distinct diff) are re-scored with
`regression_a2`. That requires runs only on the 17 new QA tasks (DeepSeek, guessing
deployed config):

- the patch at seeds 0–2 (the gate) and at seeds 3–5 (the confirmation);
- no patch at seeds 0–2 (the reference).

The report says whether the patch still passes check 3 and its confirmation under A2.
The A1-era result stays reported as it was. The other 23 generic patches (LOOP_DETECTED,
PLAN_DRIFT) failed check 1 on every failure under A1, so A2 can't change whether they
are promoted. They are not re-run, and their H3 under A2 is listed as not measured.

## 4. What stays the same

The 59 failures, held-out sets, seeds, the 2-of-3 task rule, the A1 primary outcome, the
gate, the injection tags, H5 and the H6 protocol (A1 §2: 300-run seeded sample of
critic-arm runs, now including runs on the A2 regression tasks), and the test seal are
all unchanged. As pre-registered, `reverts_injection` patches are reported separately
from `other_fix`, and the headline uses `other_fix`.

## Budget planning (not a cap)

Every paid call is still checked against the $3.00 rest-of-phase ledger (D67), and H6
has its own $0.40 sub-cap within it.

Measured on the plan (`python -m bench.heal.a2 --plan`, at this tag), against the $2.95
left in the ledger when A2 was written:

| Runs | DeepSeek runs | Est. DeepSeek $ | Qwen runs (local) |
|---|---:|---:|---:|
| Item 3 (generic re-run, 17 new QA tasks) | 153 | 0.10 | 0 |
| Critic `new`, seeds 0–2 + references | 3,672 | 3.20 | 2,361 (~4.0 h) |
| Critic `v1_structured`, seeds 0–2 + references | 3,042 | 2.88 | 2,151 (~3.7 h) |
| Both arms (shared references counted once) | 6,612 | 6.02 | 4,461 (~7.6 h) |

Fresh-seed confirmations come on top of that. **The full critic-arm protocol under A2
does not fit the $3.00 cap.** That conflict is resolved before any critic-arm run,
either by changing the cap or by a design amendment (A3) committed first. The ledger is
never topped up silently. If a run hits the cap, it stops and reports the n it
completed.
