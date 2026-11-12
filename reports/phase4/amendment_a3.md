# Phase 4 pre-registration, amendment A3: the test scoring

- **Status:** committed before any Phase 4 test run, and frozen with the dev protocol
  under tag `phase4-dev-frozen`. The pre-registration ([`preregistration.md`](preregistration.md),
  tag `phase4-prereg`), A1 ([`amendment_a1.md`](amendment_a1.md)) and A2
  ([`amendment_a2.md`](amendment_a2.md), tag `phase4-prereg-a2`) are unchanged. Where A3
  says nothing, they hold.
- **Date:** 2026-11-11 · **Branch:** `phase-4-healing`
- **State when A3 was written:** dev is finished and reviewed (D73, D74). The selected arm
  is **`v1_structured`**. Nothing has been run on the test split. A3 was written after
  reading the test **labels only**: the failure counts below are from `labels.csv`.
  No test trace, run or detector output had been looked at.
- **Code:** `bench/heal/sets.py` (`build_test_sets`, `assert_split`),
  `bench/heal/freeze.py` (the freeze guard), `bench/heal/harness.py` (test mode),
  `bench/heal/test_phase.py` (evidence, critic, runs, scoring). Tests:
  `tests/unit/heal/test_a3.py`.

## Why an amendment is needed

Pre-registration §1f says the test failures, held-out sets and regression set "will be
built by the same code and rules on the test split". That does not fix the failure
sample. The dev failures were not drawn by Phase 4 code. They are the Phase 3 critic's
dev selection, copied in as a file (`phase3_selection.json`). Nor does §1f say how test
evidence is built, which arms run on test, or what the spend cap is. A3 fixes all of
that before any test run.

## 1. Test failures, held-out sets, regression set

- **Failures.** The rule that chose the dev failures is applied to the bench-v1.1 test label
  rows: `services.critic.experiments.select_labels`. It takes 12 per class, with seed
  `20261110:<class>`, and draws round-robin over (provider, model), distinct tasks
  first. The selection is a pure function of the labels.
- **Exclusions.** Two dev rules apply unchanged.
  - **Label check** (`sets.entries`): a selected trace whose bench-v1.1 label or fault
    differs from its selection label is not a failure. On test this excludes **0**
    traces, because the selection reads the same labels.
  - **A1 no observable harm** (`score.eligible`): a CONTEXT_BLEED failure whose
    original trace passed the checker is left out of H1, H2, the gate counts and H4.
    Its H3 regression breaks are still reported.
- **Held-out sets and the A2 regression set.** These come from `sets.derive`, with the
  same seed strings as dev, run on test rows only. The regression set is every test QA
  task that passes with no fault (20) plus 3 seeded tasks from each other family (9),
  29 in all. The 12-task A1 regression set is also written, but scoring uses the A2 set.
- **Short held-out pool.** The TOOL_MISFIRE/ollama pool has only 4 test tasks where
  the fault fired, against the usual 6. Each of the 4 TOOL_MISFIRE/ollama failures
  therefore has **3** held-out tasks, not 5. The rule is applied as written, with no
  top-up from other providers or faults.
- **Seal.** The sets are written to [`prereg_sets_test.json`](prereg_sets_test.json),
  and CI checks that the code reproduces them. The builder refuses any task id that
  isn't a test id.

Test failure counts, from labels only:

| Class | Failures | deepseek | ollama | Excluded: no observable harm | Scored for H1/H2/gate |
|---|---|---|---|---|---|
| HALLUCINATION | 12 | 12 | 0 | 0 | 12 |
| TOOL_MISFIRE | 12 | 8 | 4 | 0 | 12 |
| CONTEXT_BLEED | 12 | 6 | 6 | 9 | 3 |
| PLAN_DRIFT | 12 | 0 | 12 | 0 | 12 |
| LOOP_DETECTED | 12 | 6 | 6 | 0 | 12 |
| **All** | **60** | 32 | 28 | 9 | **51** |

Dev had 59 failures (one label exclusion), of which 11 CONTEXT_BLEED were excluded for no
observable harm. Test has 60, of which 9 are excluded. The original trace passed the
checker in 10 of the 12 test PLAN_DRIFT failures. A1's outcome for PLAN_DRIFT is not the
checker, and A1 has no PLAN_DRIFT exclusion, so all 12 are scored.

## 2. Detector evidence

The critic gets the same kind of evidence on test as on dev. The **frozen Phase 2
detectors** (tag `phase2-detectors-frozen`; `services/detectors` and
`bench/detector_view.py` unchanged at HEAD) run on the detector view of each of the 60
selected test traces. The predicted class (`pipeline.label`, frozen thresholds) goes to
`services.critic.detector_adapter.from_detector`, as in Phase 3 round 3. Only `pred`
is used. A NORMAL prediction gives no evidence and therefore no proposal, as on dev. The
Phase 3 leak assertion runs on the evidence, and the run fails if any evidence leaks.

The output is [`test/evidence.json`](test/evidence.json). It is input to the critic,
not a Phase 2 result. **No Phase 2 test metric is computed, written or reported.**
`results/detect_test*.json` is not touched, and no detector precision or recall is
derived from these 60 traces. The test report gives only the critic's coverage: how
many failures got a proposal, and why the others did not.

## 3. The critic on test

There is one `v1_structured` proposal per test failure. It is generated the way Phase 3
round 3 generated the dev proposals (`round3_part_b.run_experiment`):

- the same `run_critic` call;
- the same DeepSeek provider;
- the same deployment snapshot (`baseline_config`);
- `critic_arm = "v1_structured"`;
- detector evidence only.

The Phase 3 dev-only scoring steps (C3, scoring truth, Phase 3 fix tag) are not run;
Phase 4 computes its own injection tag (`config.injection_tag`). The records go to
[`test/v1_structured.jsonl`](test/v1_structured.jsonl). They are read by
`critic.load_round3` under the A1 rules: a fallback, an invalid proposal or a failed
dry run gives no patch. A proposal is generated once; no failure is re-asked.

## 4. Arms, runs and outcome

There are three arms. Each is scored exactly as on dev (`a2.score_arm`):

- **no patch** (H5);
- **generic**: the fallback templates. CONTEXT_BLEED and TOOL_MISFIRE are inapplicable,
  as on dev;
- **critic `v1_structured`**.

Under all three:

- **Seeds:** 0–2 for every arm, on each failure's own, held-out and A2 regression tasks.
- **Fresh-seed confirmation:** every gate-promoted generic and critic patch gets
  seeds 3–5.
- **Unchanged from dev:**
  - the gate (`services/healer/gate.py`), with check 3 on the A2 regression set;
  - the A1 primary outcome;
  - the old rule (H4: own task passes on seed 0);
  - the injection tags, with `other_fix` as the headline and `reverts_injection`
    reported apart;
  - reporting per failure and per distinct patch (A2);
  - the false-promotion definitions.
- **Not on test:** H6 is not part of the test scoring.

The test is scored **once**. Runs are idempotent by run id (an interrupted run resumes
and does not restart). Proposals are not regenerated. Nothing is tuned after a test
result is seen.

## 5. Freeze, seal and spend

- **Freeze.** `phase4-dev-frozen` is tagged after the evidence file is committed. Test
  mode (the test critic, `Harness(split="test")` and test scoring) refuses to start
  unless the tag is an ancestor of HEAD and none of the frozen paths has changed since
  the tag (`bench.heal.freeze.FROZEN_PATHS`). The frozen paths cover:
  - the gate, outcome and scoring code;
  - the harness and agent;
  - the critic package, including the `v1_structured` prompt and transport;
  - the Phase 2 detectors;
  - A1–A3, the dev sets, and the test sets and evidence.
- **Seal.** A test-mode harness refuses dev task ids, and a dev harness still refuses
  test ids.
- **Storage.** Test runs go to `results/heal_runs_test.jsonl` with their own ledger
  (`bench/heal/_state/cost_ledger_test.jsonl`). The critic's calls go to
  `reports/phase4/test/critic_calls.jsonl`.
- **Cap: $5.50** for the whole test scoring (user decision, D75). The critic has a
  sub-cap of $0.60. The run cap is $5.50 minus the critic's actual spend, checked
  before every paid call against the worst case.
- **Estimate.** Before any test run, from dev costs per run, the estimate is $4.54
  expected and $5.34 if every applicable patch is promoted. It is re-checked once the
  proposals exist and before any agent run. If it exceeds $5.50, nothing runs until
  the user decides.
