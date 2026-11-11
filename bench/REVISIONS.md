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
| weight in kg (tool), shipping weight in kg (plan) | measurement | \|x − gold\| ≤ max(0.011 kg, 0.1% of gold) | gold uses 0.45359237 kg/lb. Common factors (0.4536, 0.454) are within 0.09%, and display rounding to 0.01 kg adds ≤ 0.005 kg |

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
