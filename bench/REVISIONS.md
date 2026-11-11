# NexusBench revisions

## v1.1 — numeric checker fix (announced 2026-11-10, before any code change)

**Problem.** The v1 checker accepted any number within ±1.1% of gold (minimum
0.02) for every numeric field. That tolerance was meant for decimal amounts,
but it was applied to integer-valued facts too. For a founding year it allows
±22 years, so wrong years were labelled NORMAL (4 dev and 6 test QA rows meet
the criterion registered in Phase 2, see DECISIONS D39). For a USD total of
$1,000 it allows ±$11, far more than rounding can explain.

**Fix: per-field tolerance.**

| Field (task family) | Type | v1.1 rule | Why |
|---|---|---|---|
| founding year (qa) | integer | exact | a year is a fact, not a measurement |
| employee count (qa) | integer | exact | a count is a fact |
| item count (tool) | integer | exact | a count is a fact |
| discounted total in USD (tool, memory) | money | \|x − gold\| ≤ $0.011 | gold is rounded to cents; a correct computation can differ only by rounding (≤ 1 cent) |
| weight in kg (tool), shipping weight in kg (plan) | measurement | \|x − gold\| ≤ 0.1% of gold + 0.011 kg *(corrected, see below)* | gold uses 0.45359237 kg/lb. Common factors (0.4536, 0.454) are within 0.09%, and display rounding to 0.01 kg adds ≤ 0.005 kg |

Text answers are unchanged (normalised substring match).

**Scope.**
- **Changes:** `bench/tasks.py` (checker only; each task gets a `num_type`).
  Labels are then recomputed from the committed traces with
  `python -m bench.relabel`, with **no regeneration**, so traces, splits, task
  ids and gold values are untouched. The test manifest is rewritten, because it
  hashes each test trace together with its labels row.
- **Unchanged:** all fault injectors, all other label rules, the memory store,
  `splits.json`, and every trace line.
- **Phase 2:** primary results stay as scored on v1 labels (tags
  `phase2-detectors-frozen` and `phase2-test-scored`). v1.1 labels are used
  only for a sensitivity analysis, computed from stored predictions, with no
  detector re-run on test.
- **Tag:** `bench-v1.1`. No existing tag is moved.

### Correction before tagging

The kg rule as first announced, max(0.011 kg, 0.1% of gold), contradicted its
own justification. A correct answer computed with the 0.454 factor and
rounded to 0.01 kg (e.g. 35.37 against gold 35.334, off by 0.10%) failed it,
because factor error and rounding error add up. The rule was changed to
**0.1% of gold + 0.011 kg** before any label was committed or the tag was set.
The unit test that caught it is in `tests/unit/nexusbench/test_bench.py`.
The correction changed no label in the committed data (same 13 rows, same
manifest digest).

### v1.1 outcome

- Labels were recomputed from the committed traces (`python -m bench.relabel`).
  Traces are byte-identical to v1.
- **11 labels changed:**
  - dev: NORMAL → HALLUCINATION ×4 (QA founding years, DeepSeek);
  - test: NORMAL → HALLUCINATION ×6 (QA founding years, DeepSeek);
  - test: NORMAL → OTHER_FAILURE ×1 (memory USD total, Qwen).

  13 rows changed in total; 2 changed only a checker flag, not their label.
- **New test manifest digest:** `0f664774995b6a9334500212a93bb698c350190f00397260f196f9c25266d9c0` (357 test traces). Tag `bench-v1.1`.
- **Phase 2 sensitivity on v1.1 labels**, from stored predictions with no
  detector re-run: test HALLUCINATION precision 0.811 → 0.973 (36/37), false
  alerts per 1,000 NORMAL 56.0 → 8.5, headline macro recall unchanged at 0.956.
  See `results/detect_test_v11_sensitivity.json` and
  `results/detect_dev_v11_sensitivity.json`.

| Label (v1.1) | dev DeepSeek | dev Qwen | test DeepSeek | test Qwen | total |
|---|---|---|---|---|---|
| NORMAL | 72 | 46 | 75 | 43 | 236 |
| HALLUCINATION | 34 | 0 | 36 | 0 | 70 |
| CONTEXT_BLEED | 12 | 18 | 18 | 12 | 60 |
| PLAN_DRIFT | 0 | 24 | 0 | 31 | 55 |
| TOOL_MISFIRE | 28 | 6 | 33 | 5 | 72 |
| LOOP_DETECTED | 17 | 17 | 19 | 10 | 63 |
| OTHER_FAILURE | 8 | 77 | 6 | 69 | 160 |
