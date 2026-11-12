# Nexus — Decision Log

Each entry gives the decision, why it was made, the alternatives that were
rejected, and what it costs. These are the answers to "why did you do it that
way?". Newest entries go at the bottom of each section. Dates are 2026-11-10
unless noted.

---

## Evidence and reporting

**D1. Every public number comes from a committed result file.**
*Why:* the original README claimed "precision 1.000", "20/20 actionable" and
"heals in under 90 s", and none of these was backed by a real run (the 90 s
came from a mocked test that finished in 50 ms). A claim you can't trace back
can't be defended. *How:* `results/*.json` files carry date, commit, a dirty
flag, provider, model, mock flag and seed. `RESULTS.md` is generated from them,
and CI fails if it is stale or a report lacks a provider/model header.
*Rejected:* hand-maintained results tables, which drift.

**D2. Precision is never reported without recall.**
*Why:* "1.000 precision" hid a 0.473 recall and 2/60 hallucinations caught. A
detector that flags almost nothing has perfect precision.

**D3. The mock LLM is opt-in only (`NEXUS_LLM=mock`); a missing key is an error.**
*Why:* the critic silently fell back to a mock when no key was set, which is
how 20 generic fallback templates were reported as "20/20 actionable". Silent
fallbacks produce results that look real. *Cost:* local runs without a key
fail loudly, which is the intended behaviour.

**D4. Pin model versions and record them in every result.**
*Why:* `gemini-2.0-flash` had been retired. A result without a model version
can't be reproduced or compared later.

**D5. Wilson intervals in the Phase 0 summaries, Clopper-Pearson for Phase 2.**
*Why:* Wilson is a good default for summarising existing reports. For
pre-registered detection claims at small n (PLAN_DRIFT test n=26),
Clopper-Pearson is exact and conservative, so a reviewer can't argue the
interval is too optimistic.

**D6. Provenance treats `results/`, `RESULTS.md` and `docs/` as outputs.**
*Why:* regenerating one result rewrote tracked output files, which marked the
*next* result "dirty" even though the source code was committed. The dirty
flag should mean "the code that produced this was uncommitted". *How:* commit
the code, then regenerate the results at that commit, then commit the results.

## Infrastructure

**D7. Healthchecks + `depends_on: service_healthy` + `restart: unless-stopped`.**
*Why:* services connected to Postgres and Kafka once at startup and crashed for
good while TimescaleDB was still initialising. *Detail:* `pg_isready -h 127.0.0.1`,
because the first-boot init server listens only on the Unix socket, so a socket
check reports "ready" too early.

**D8. `.dockerignore` at the repo root.**
*Why:* every image builds from the repo root, which shipped the Windows
`node_modules` (native binaries for the wrong OS), `.venv`, `.env` and caches
into Linux images.

**D9. SDK distribution `nexus-selfheal`, not published yet.**
*Why:* `nexus-agent` on PyPI belongs to someone else. Publishing waits until
the documented API matches the code, which was not the case at first
(`configure`, `record_span` and the LangChain integration didn't exist).

**D10. Don't push `main`; push phase branches.**
*Why:* `origin/main` had a commit made on GitHub that the local branch lacked.
Pushing phase branches as new branches can't overwrite anyone's work.

## NexusBench design (Phase 1)

**D11. A fully fictional world.**
*Why:* if facts are real, a correct answer might come from the model's own
memory, which makes "unsupported by context" impossible to judge. With invented
companies, orders and users, a correct answer must come from a tool or
document, so hallucination labels are checkable.

**D12. A provider-agnostic JSON action protocol instead of native function calling.**
*Why:* the same agent had to run on Gemini, DeepSeek and a local Ollama model.
*Cost:* some malformed JSON, which is counted (`invalid_json`) rather than
hidden.

**D13. DeepSeek + local Qwen, not Gemini, for the benchmark.**
*Why:* the Gemini key turned out to be free-tier (20 requests/day per model).
DeepSeek is cheap and paid (the whole benchmark cost $0.28); Qwen 7B runs on a
local RTX 4080 for free. *Bonus:* the benchmark's agent models are separate
from the critic model (Gemini), so a model doesn't diagnose its own family.
*Cost:* two model families only.

**D14. Response cache + cost ledger + hard per-provider caps, checked before each call.**
*Why:* regeneration must be free and reproducible, and a spending mistake must
be impossible rather than merely unlikely. Caps are checked against the worst
case (`max_tokens`), not the expected cost.

**D15. Labels come from deterministic rules over what the agent did, never from
an LLM or a human.**
*Why:* a benchmark labelled by an LLM judge would measure the judge.
*Auditability:* labels can be recomputed from the committed traces alone
(`bench/relabel.py`, CI-checked). Recomputing caught 39 runs mislabelled by an
abstention regex that had since been fixed.

**D16. A label describes behaviour, not injection.**
*Why:* if an injected run is labelled a failure even when the model resisted,
a detector can score well by spotting the injection rather than the failure.
Injected-but-resisted runs are labelled NORMAL (passed) or OTHER_FAILURE
(failed some other way).

**D17. An `OTHER_FAILURE` label.**
*Why:* forcing every failed run into one of the five types would invent
labels. It is excluded from per-class scoring, and flagging one counts as a
true detection of "some failure".

**D18. Quota-driven attempts with a hard cap; report shortfalls instead of
extending.**
*Why:* PLAN_DRIFT reached the 150-attempt cap at 46 (DeepSeek never follows
the injection). Raising the cap for one class after seeing the data would be a
data-dependent choice, so it is reported as is.

**D19. Split by task, not by trace; a user's memory tasks share one split.**
*Why:* repeated runs of the same task are near-duplicates. Splitting by trace
would let a detector see the test task during development.

**D20. A SHA-256 manifest of the test set (trace line + labels row), committed
before any tuning; LF line endings pinned.**
*Why:* it makes "we didn't touch the test set" checkable by anyone. Without the
`.gitattributes` pin, a Windows checkout would rewrite the hashed bytes.

**D21. The checker requires the task's required tools to have actually run.**
*Why:* a correct number without running the lookup is a lucky guess, not a
success.

**D22. A hallucination claim is "supported" only by a document about the
company asked about.**
*Why:* the pilot showed models borrowing a fact from another company's document
("X employs 9,179" when 9,179 belongs to Y). Checking only whether the value
appears anywhere in the context called that "supported".

## Phase 2 pre-registration

**D23. Pre-register before building detectors; freeze with a git tag.**
*Why:* choosing metrics after seeing results lets you pick the flattering
ones. The tag `phase2-prereg` fixes the metrics, targets, operating-point rule
and input contract. Later changes are logged as amendments with a new tag, and
the old tag is never moved.

**D24. A detector input contract (`bench/detector_view.py`) enforced by CI.**
*Why:* raw traces leak the answer: task id, fault family, model name, the
injector's ownership metadata, and canary tokens. A detector that reads them
scores perfectly and means nothing.
- **Model name is stripped** because it is a label confound: HALLUCINATION and
  TOOL_MISFIRE come only from DeepSeek, PLAN_DRIFT only from Qwen.
- **Injection-config identifiers get per-trace pseudonyms** (not constant
  ones), so a detector can't learn the constant.
- **Text the agent really saw stays** (the injected drift note), because a
  production trace would contain it. CI forbids detector code from matching
  those literals, and the note isn't a shortcut anyway (it appears in 104
  NORMAL traces).

**D25. LOOP_DETECTED and TOOL_MISFIRE are "rule-defined, not headline".**
*Why:* their detector *is* their definition, so scoring them measures nothing
new.

**D26. Headline = macro recall over HALLUCINATION, CONTEXT_BLEED and
PLAN_DRIFT, with a pre-registered secondary over HALLUCINATION + PLAN_DRIFT.**
*Why:* the secondary was registered in advance in case CONTEXT_BLEED proved
trivial, so falling back to it is not a post-hoc choice.

**D27. The operating point is chosen on dev only (max recall at dev precision
≥ 0.90); test is scored once; the test split is sealed in code.**
*Why:* tuning a threshold on test turns test into dev. `load_rows("test")`
raises unless the one final run passes `unseal=True`.

**D28. Baseline = the shipped classifier at its shipped operating point.**
*Why:* retraining or re-thresholding the baseline on NexusBench would make it
a different model. It turned out to be degenerate: it predicts HALLUCINATION
for every trace no rule catches, so its 0.93 hallucination recall comes with
0.14 precision.

**D29. Amendment 1: make CONTEXT_BLEED non-trivial before any detector work.**
*Why:* in v1, "memory returned more than one record" matched the label
exactly on dev (30/30, 0 FP), because only the injector produced multi-record
reads. *How:*
- the amendment was written and committed before the code;
- memory content gets its own RNG stream, so the world, tasks, gold answers
  and splits are unchanged;
- records carry no owner fields, and ownership lives only in a registry that
  detectors never see;
- legitimate multi-record reads (own notes, shared team notes) overlap with
  bleed in record count;
- only the 257 traces that read memory were regenerated, and the other 459
  are byte-identical;
- there is a new manifest and a new tag `phase2-prereg-v2`, and the old tag
  is kept.

*Gate:* if any trivial single-field rule still reaches P ≥ 0.95 and R ≥ 0.95
on dev, the headline falls back to the pre-registered secondary.

*Outcome:*
- The gate was not tripped. "Record count > 1" is now P 0.435 / R 1.00.
- One partial shortcut remains: "≥ 2 `Account tier:` records" (P 1.00,
  R 0.50). It was registered as a trivial reference that a CONTEXT_BLEED
  detector must beat, rather than removed by redesigning again, because a
  second redesign after seeing dev results starts to become tuning the
  benchmark to the detector.
- Spend was $0.089.

**D30. Report the side effects of the regeneration instead of correcting them.**
*Why:* new memory content changed the agents' behaviour on memory tasks under
the other faults. PLAN_DRIFT went from 46 to 55, and Qwen now produces 11
TOOL_MISFIRE runs. Re-running or filtering to restore the old counts would
pick data by its labels. The labels are still produced by the unchanged rules,
so the new counts are reported as they are.

**D31. Keep the old tag and add a new one (`phase2-prereg-v2`) instead of
moving it.**
*Why:* a moved tag erases the evidence of what was registered first. Keeping
both shows the amendment was made openly, before any test scoring.

## Phase 2 detectors

**D32. Detectors live in `services/detectors/` and read only the detector view.**
*Why:* CI already scans this directory for hardcoded injection strings. Keeping
the shipped v3 classifier untouched keeps the baseline honest.

**D33. Hallucination = claim-level NLI against retrieved documents, with three
general fixes found on dev.**
1. *Sentence-level premises.* The DeBERTa cross-encoder judged "X was founded
   in 1964" as entailed by "X was founded in 1964 by Y." but as neutral once
   an unrelated sentence followed. Scoring against sentences and 2-sentence
   windows is standard practice (cf. SummaC).
2. *Pronoun resolution + entity gating.* NLI accepted "Talka Robotics was
   founded in 2018" from another company's "It was founded in 2018". The
   leading "It" now resolves to the document title, and a premise only
   supports a claim if it names the claim's entities.
3. *Non-claims are skipped:* hedges, statements about the retrieval itself,
   and requests ("Please check …").

*Rejected:* using an LLM as the main detector (cost, and an LLM judging LLM
output). It is a separate variant instead.

**D34. The Gemini judge is a separate variant, never mixed in.**
*Why:* it is a different model family from both trace models (plan rule 4).
Mixing it into the pipeline would hide which component earns the result.
*Detail:* `bench/llm.py` sends `thinkingBudget: 0`, which Gemini 3.x rejects
with HTTP 400. Because `bench/` was frozen for this phase, the judge overrides
only the request body (`thinkingLevel: low`). `bench/llm.py` still needs that
fix.

**D35. CONTEXT_BLEED = conflicts in single-valued personal attributes across
the records of one read.**
*Why:* there are no owner fields. A record that belongs to someone else shows
up as a second tier, city, account manager or contact preference that
disagrees with the user's own. It is a superset of the registered reference
rule. *Known miss:* a foreign record whose attributes don't overlap with the
user's own (e.g. the user has only a tier note and the foreign record is a
city note).

**D36. PLAN_DRIFT = identifier provenance.**
An id in a call's arguments must come from the user request or a *data
field* of an earlier tool result; ids that appear only inside prose don't
count. *Why:* the injection hides an id inside free text, and following it is
exactly a call whose id has no data provenance. "Executed a tool not in the
plan" on its own was too noisy (plans are often one step). *Deviation from the
brief:* grounding from *any* earlier tool result rather than only *planned*
tools, chosen on dev (D-3 in the pre-registration).

**D37. Retry and loop windows are counted in tool calls, not spans.**
*Why:* a span window depends on how densely a trace is instrumented. That
alone explained the Qwen misfire gap (2/6 → 6/6 on dev) without anything
Qwen-specific.

**D38. Ties broken by the midpoint of the tied threshold range.**
*Why:* the pre-registration didn't say. Taking the lowest tied threshold
(0.0069) would have put the operating point just above NORMAL scores, which is
fragile. Fixed and logged before the freeze.

**D39. A label defect found during Phase 2 is reported, not fixed.**
The numeric checker's ±1.1% tolerance accepts founding years up to ±22 years
off. *Why not fix it:* labels and the manifest are frozen for this phase.
Changing them after seeing detector output is post-hoc relabelling. A
mechanical sensitivity criterion was registered before the freeze and is
reported next to the pre-registered numbers. The fix belongs in a later,
announced benchmark revision.

**D40. The test result is reported as scored, with the sensitivity analysis kept separate.**
HALLUCINATION missed the pre-registered precision target on test (0.811). 6
of its 7 false positives meet the label-defect criterion registered before the
freeze. The headline reports 0.811. The adjusted figure (precision 36/37 if
those 6 are counted as hallucinations) is shown only as a labelled
sensitivity analysis. *Why:* the target was pre-registered, so missing it is a
result. The adjusted number is honest only because its criterion was fixed
before the test was unsealed.

**D41. The judge variant agrees with the NLI detector — but the two are NOT independent (corrected; see D43).**
On dev, the Gemini judge and the NLI detector agree on every trace where either
ran (0 disagreements in 96). Test results are identical in aggregate (same
confusion matrix). *Correction:* an earlier version of this entry called this
"two independent methods agreeing". That was wrong. Both read their evidence
from the same `retrieved_context()`, which includes the pronoun resolution
added during dev tuning, and both skip traces with no retrieved documents.
Their agreement shows that two judges given the same evidence reach the same
verdict, not that the evidence extraction is right.

**D42. The test results carry `+dirty` provenance; they are not re-run.**
During the one-time test run, the Gemini judge appended to its tracked cache
and ledger (`data/phase2/`) before the result files were written, so the
provenance dirty flag is set. No source file changed: `score_test.py`
refused to run unless every frozen path (`services/detectors`,
`scripts/phase2`, `bench`, `data/nexusbench`) matched tag
`phase2-detectors-frozen`. Re-running to clear the flag would score the test
split a second time. *Lesson:* put caches and ledgers that experiments write
to in the provenance exclusion list, as with D6.

## Phase 2 follow-ups

**D43. Independence audit: shared evidence extraction, separate judgement.**
From the code at tag `phase2-detectors-frozen`:
- The judge does not see any NLI output, the claim split or the entity gate
  (it gets the raw final answer).
- It runs on every trace, not only on traces the NLI path selected.
- Both use `retrieved_context()` and the same "no retrieved documents → skip"
  gate.

On dev the judge ran on 96 traces and NLI on 55. The other 41 are answers in
which NLI found no factual claim after its hedge filter; the judge cleared all
41. Per-trace test agreement can't be reported because test predictions were
not persisted (D45).

**D44. Disclosure: on NexusBench, hallucinations are largely detectable by entity absence.**
The entity-presence rule alone (flag a claim whose entities appear in no
retrieved premise) gets R 1.00 (30/30), P 0.857 (30/35) on dev, which is the
same as the full NLI detector. *Why it matters:* the HALLUCINATION injector
hides the document about the company asked about, so the company's name is
absent from the context by construction. NexusBench therefore barely tests the
NLI part; HaluEval (D4: R 0.783, P 0.546) is the harder test.

**D45. Per-trace test predictions were not persisted; v1.1 test sensitivity uses
stored aggregates only.**
*What happened:* `score_test.py` stored per-class counts, confusion matrices
and the ids of the 6 year-tolerance rows (all predicted HALLUCINATION), but not
a prediction per trace. Re-running detectors on test is not allowed, so the
v1.1 test metrics are computed exactly where the stored data determines them
and as bounds otherwise. *Lesson:* every scoring run must write its per-trace
predictions (now done for dev: `results/phase2_dev_predictions.json`).

**D46. NexusBench v1.1 is an announced revision: labels are recomputed, traces untouched.**
*Why:* the ±1.1% numeric tolerance mislabelled wrong founding years as NORMAL.
The fix is a per-field tolerance (exact for years and counts, ±1 cent for USD,
0.1% + 0.011 kg for weights), each with a written justification. The note was
committed before the code. Labels were recomputed from the committed traces,
with no regeneration. Phase 2 primary results stay on v1; v1.1 appears only as
a sensitivity analysis computed from stored predictions. Effect on test:
HALLUCINATION precision 0.811 → 0.973, false alerts per 1,000 NORMAL
56 → 8.5, headline unchanged.

**D47. A unit test caught a flaw in the announced rule; it was corrected openly.**
The first kg rule, max(abs, rel), rejected correct 0.454-factor answers
rounded to 0.01 kg, contradicting its own justification. It became additive
(rel + abs) before anything was tagged. The correction is recorded in
REVISIONS.md, and it changed no label in the data.

**D48. Judge caches and ledgers are untracked; `results/` is the only tracked output.**
*Why:* tracked caches that experiments append to made the one-time test rows
"dirty" (D42), even though no source changed. From now on `data/phase2/` is
gitignored. The files stay on disk, so caching still saves money, but they
don't affect provenance. The committed copies remain in history up to this
commit. The existing test result rows are left as they are, still marked
`+dirty` (D42). `data/nexusbench/` is benchmark *input* data and stays
tracked; its manifest is CI-checked. Phase 2 spend stays auditable: $0.0285
over 149 judge calls, as recorded in the committed ledger history.

**D49. `bench/llm.py` now picks the thinking field by Gemini major version.**
`thinkingBudget: 0` for 2.x and `thinkingLevel: low` for 3.x+. Unit-tested and
verified with one live call. The frozen judge keeps its own override; the
detectors are not edited after `phase2-detectors-frozen`.

## Phase 4 preparation (healing harness, pre-registration, baselines)

**D50. A patch is a config diff over the agent's three real config values.**
`system_prompt`, `MAX_STEPS` and `TOOL_SPECS` are the values the Phase 3 critic
snapshots. A patch is a list of RFC 6902 `replace` ops on JSON pointers that already
exist, type-preserving, with `MAX_STEPS` bounded to 1–30 (`bench/heal/config.py`).
*Why:* the harness has to accept whatever the Phase 3 arms produce without depending on
their code. Whole-key replacement (the Phase 3 format) is a special case, adapted by
`from_phase3`. *Consequence, stated up front:* only HALLUCINATION lives in the config.
The other four faults live in the tool backend, which no config diff can change.

**D51. A config-driven copy of the agent loop, not an edit to `bench/agent.py`.**
*Why:* `bench/` is frozen benchmark code, and its traces are hashed in the test
manifest. `bench.heal.agent.ConfiguredAgent` repeats the loop with the three values
passed in. A unit test checks that it sends byte-identical LLM requests to
`BenchAgent` for both the clean and the guessing config. *Cost:* two copies of the loop
to keep in sync. The equivalence test fails if they drift.

**D52. The failures are the Phase 3 critic's own dev selection; one mislabelled entry is excluded.**
*Why:* the baselines and the critic arms must be scored on the same failures. The file
is copied verbatim and pinned by its content hash. That way a line-ending conversion
(CRLF in the phase-3 worktree, LF in git) can't change the pin. `PLAN_DRIFT:mem-006:ollama:r0`
is labelled PLAN_DRIFT in the selection, but NORMAL in bench-v1.1 (also NORMAL in the
phase-3 branch's own `labels.csv`), so it is not a failure. It is excluded and reported
rather than silently relabelled.

*Correction (2026-11-11, amendment A1).* An earlier version of this entry said "the
cause is in Phase 3 code". That was not checked, and it is wrong. Phase 3's label
reader (`dev_labels`) returns NORMAL for this row on the bench-v1.1 file. The actual
cause:
- the selection's provenance commit `7d95b15` (no longer on any branch) carries a
  `labels.csv` that is byte-identical to **NexusBench v1** (`0645358`);
- in v1 this run *was* PLAN_DRIFT; its trace was regenerated in v2 (Amendment 1, D29),
  where it became NORMAL;
- all 60 selection rows match v1 labels, and 59 also match v1.1.

So the selection was drawn from v1 labels, which predate the v2 memory regeneration
and the v1.1 relabel. The exclusion stands. Phase 3's round 3 re-selects on v1.1 and
gets a different 60; the overlap is in D63.

**D53. Primary outcome = the v1.1 checker; "rule cleared" is a secondary outcome, never gated.**
*Why:* the brief fixes the checker as the pass rule. Writing down before any run what
that implies:
- HALLUCINATION and LOOP_DETECTED own tasks cannot pass under any config diff (the
  needed document or record never arrives).
- 22 of 59 CONTEXT_BLEED/PLAN_DRIFT failures already passed the checker in their
  original trace.

The secondary outcome (the fault's own rule did not fire) comes from the same runs at
no extra cost. It shows the abstention-style wins that the primary outcome can't credit.
*Rejected:* changing the gate's pass rule to "label NORMAL". It would make CONTEXT_BLEED
unfixable by construction, because its rule fires on what the store returns, and it
would depart from the brief.

**D54. Held-out tasks are drawn from tasks where the fault fired for the same provider;
every run of a patch uses the failure's deployed config.**
*Why:* a held-out task the fault never affects can't show generalization. Injection
effectiveness differs sharply by model (DeepSeek ignores the drift note; Qwen never
hallucinates). Regression runs also use the patched *deployed* config: for a
HALLUCINATION failure, that is the guessing prompt plus the patch. That is what would
ship. So their no-patch reference is the deployed config on clean tasks, not the clean
config.

**D55. Run ids are pure functions of the experiment, and the applied config is asserted, not assumed.**
The run id = patch hash + base config + env fault + task + provider + seed. Re-running
skips completed ids. A stored id whose intended config hash differs stops the run. After
every run, the hash of the config the agent actually used (prompt sent, step budget
enforced, tool list rendered) must equal the intended hash, or nothing is recorded.
*Why:* in the capstone, a label bug came from a run whose stored identity did not match
what had run. *Detail:* Phase 4 uses its own response cache and fresh cache tags, so a
no-patch rerun is a new sample rather than a replay of the original trace.

**D56. On dev, gate false promotions are measured on a fresh-seed confirmation.**
*Why:* a gate-promoted patch passes checks 2 and 3 by definition, so "false promotions
with the gate" on the same runs is always 0 and says nothing. Each gate-promoted patch
is re-run on seeds 3–5; it is a false promotion if the confirmation fails check 2 or 3.
The old rule (seed 0 of the same input passes) is scored on the main runs.

**D57. The regression set covers all four NexusBench families.**
The brief and the plan say "three task families". NexusBench has four (qa, tool, plan,
memory). The memory family is where CONTEXT_BLEED, and many TOOL_MISFIRE and
LOOP_DETECTED failures, live, so leaving it out would hide regressions from patches
aimed at them. 3 seeded tasks per family = 12.

**D58. The generic arm maps fallback templates to config keys by a fixed rule, and
reports the templates that have no key as inapplicable.**
Prompt templates are appended to the deployed prompt. The retry template keeps only
`max_steps`. `memory_store` (CONTEXT_BLEED) and `tool_call_wrapper` (TOOL_MISFIRE)
don't exist, so 24 patches are not run. *Why:* inventing a mapping for a
nonexistent component would credit the template with a fix it doesn't describe.

**D59. One Phase 4 spend cap across all providers, in Phase 4's own ledger.**
`bench.heal.harness.PhaseLedger` caps the total at $1.50, checked before every paid
call against the worst case. The Phase 1 caps are per provider and all-time, which
doesn't match this budget. The ledger and cache are untracked local state (D48). The
spend of record is the per-run `cost_usd` in `results/heal_runs.jsonl`, which is
tracked.

**D60. The duplicate-run guard compares experiment identity, not the request.**
The first launch stopped before any run: a clean-base regression run was requested by
failures with different faults, and the guard compared the whole request (including
the failure's fault) instead of the experiment. The guard now compares patch hash,
intended config hash, env fault, task, provider and seed. Nothing had been recorded,
so no protocol or result changed. This was the guard working as intended: it fails
closed.

**D61. Baseline outcome (dev), reported as scored.**
609 runs, $0.247 of the $1.50 cap, 0 run errors. Runs were made at `59eb90d`, scored at
`924680c`.
- **H5 (null patch):** the own task passes for 22 of 59 failures. These are exactly the
  11 CONTEXT_BLEED and 11 PLAN_DRIFT failures whose original trace already passed. 0 of
  the HALLUCINATION, LOOP_DETECTED and TOOL_MISFIRE failures pass. At temperature 0 the
  3 seeds never disagreed (0 of 111 cells), so "noise" here is "the failure was not a
  checker failure", not run-to-run variance.
  - The **old rule would promote the do-nothing patch for 22 of 59 failures**. All 22
    are false promotions (no held-out gain). The gate promotes none.
- **Generic templates:** 24 inapplicable, 35 run.
  - H1 1/35, H2 0/35, H3 0/35, gate promoted 0.
  - **Net of H5, H1 is −0.29.** The plan-adherence template made Qwen emit empty tool
    calls until `max_steps`, which broke 10 of the 11 PLAN_DRIFT tasks that pass with no
    patch. It still followed the drift (rule fired in all 39 runs).
  - On the secondary outcome, the HALLUCINATION template clears the rule in 12/12 (the
    agent abstains) and the gate promotes it 12/12. The primary outcome credits none of
    it, as pre-registered.
  - No gate promotion on the primary outcome, so no confirmation runs were needed.
- **Not changed after seeing this:** the pass rule, the sets and the gate. Whether the
  critic arms should be gated on the secondary outcome for HALLUCINATION is a question
  for an amendment *before* those runs, not a re-scoring of these.

## Phase 4 amendment A1 (2026-11-11)

**D62. The primary repair outcome is per-class "safe-failure repair" (A1); checker-only H1 becomes secondary.**
*Why:* under the checker alone, HALLUCINATION and LOOP_DETECTED can never be repaired
(D53), and 22 "repairs" were failures that were never checker failures. A1 credits the
behaviour that is safe for each fault: abstaining, reporting the error, not following
the injection, or asking the user to confirm. H3 stays checker-based, which makes
abstention credit safe: over-abstention breaks regression tasks. CONTEXT_BLEED failures
whose original trace passed the checker show no observable harm, so they leave the H1,
H2, gate and H4 denominators, and their H3 is still reported. *Guard against post-hoc
tuning:* the patterns are fixed in code at tag `phase4-prereg-a1`, before A1 is applied
to any stored run. Any later pattern fix is a new amendment, with both scores reported.

**D63. A1 records a failure-set mismatch with Phase 3 round 3 and fixes a default.**
Round 3 re-selects on v1.1 labels. Only 33 of its 60 traces are among the 59
pre-registered failures (D52). The default is to compare arms on the 33-failure
intersection. The alternative, adopting round 3's 60 with new sets and new baseline
runs, needs an amendment A2 first. *Why not decide silently:* either choice changes
every critic-arm number, and the user owns that decision.

**D64. Harness v2 stores tool outputs.**
The H6 judges must see the tool outputs, which v1 records did not keep. Run ids, config
hashes and scoring are unchanged, so v1 records stay valid. Only v2 records can be
sampled for H6.

**D65. Round 3 shows the critic the clean prompt; the harness applies patches to the deployed one.**
Round 3's `baseline_config` gives `_BASE_SYSTEM` to every failure, including
HALLUCINATION, where the deployed prompt is `_GUESS_SYSTEM`. Phase 4 keeps the original
rule (§0): the patch is applied to the deployed config. A whole-prompt replacement then
removes the guessing text without the critic having seen it, and rule 1e tags it
`reverts_injection`, which keeps it out of the headline. Phase 3's own `fix_tag` is
reported beside it.

**D66. The failure set stays the 59 pre-registered failures; the 33-failure default in A1 §5a is superseded (user decision, 2026-11-11).**
Phase 3 will generate proposals for exactly the 59 failures in
`reports/phase4/prereg_sets.json`, so every arm is scored on the same 59 and no A2 is
needed. The pre-registration is unchanged. The tagged A1 text is left as committed,
and this entry records that its §5a default no longer applies. *Why:* re-selecting on
the critic's side would swap 26 failures that already have baseline runs for 27 that
have none.

**D67. Spend cap for the rest of Phase 4: $3.00 total, in a new ledger.**
This covers the critic arms, the fresh-seed confirmations, H6 (its own $0.40 sub-cap)
and the generic confirmation. The preparation ledger (cap $1.50) is closed at $0.247.
The new ledger (`bench/heal/_state/cost_ledger_rest.jsonl`, cap `REST_CAP_USD`) starts
at $0, so the two budgets can't mix. It is checked before every paid call against the
worst case.

**D68. The Gemini key is billed; the generic HALLUCINATION promotions hold on fresh seeds.**
- **Gemini:** a one-call probe (2026-11-11, `gemini-3.5-flash-lite`, $0.00003 in the
  rest-of-phase ledger) returned HTTP 200 with `x-gemini-service-tier: standard`. Phase
  2's local ledger shows 149 calls to the same model on 2026-11-10, well past a
  20-per-day free limit. H6 keeps its full 300-run sample.
- **Confirmation:** seeds 3–5 for the 12 gate-promoted generic HALLUCINATION patches,
  78 DeepSeek runs (26 unique tasks × 3; the held-out pool overlaps the own tasks),
  $0.051, 0 run errors. **All 12 hold.** In each, the own task is a safe repair, the
  held-out rate is 1.0 vs 0.0 with no patch, and there are 0 checker regressions on the
  12-task set. H4 (A1) for the generic arm: 12 gate promotions, 0 gate false promotions.
- *Caveat:* the 12 patches are one identical diff, so they share their held-out and
  regression runs. This is one patch confirmed on 12 own tasks, not 12 independent
  confirmations. Its credit comes from blanket abstention, which H3 guards only on the
  12-task regression set (3 qa tasks).

**D69. Amendment A2: every passing dev QA task in the regression set; report per distinct patch (user decision, 2026-11-11).**
The regression set's QA part grows from 3 tasks to all 20 dev QA tasks that pass with no
fault (`regression_a2`, 29 tasks in all). Tool, plan and memory tasks are unchanged.
Every H metric is reported per failure and per distinct patch (deduplicated by diff
hash). The generic arm's 12 HALLUCINATION promotions are re-scored against the wider
set. *Why:* with 3 QA tasks, an abstain-everything prompt can pass check 3, and A1 gives
abstention repair credit. One diff promoted on 12 failures is one patch, not 12. Tagged
`phase4-prereg-a2` before any critic-arm run. The planned critic-arm spend under A2
(~$6.0 DeepSeek) exceeds the $3.00 cap. This is recorded in A2 and resolved before any
critic-arm run.

**D70. The rest-of-Phase-4 cap rises from $3.00 to $7.50 (user decision, 2026-11-11, before any critic-arm run).**
The A2 plan puts both critic arms at about $6.0 of DeepSeek runs (6,612 runs), plus
about $0.5 for fresh-seed confirmations and up to $0.40 for H6, against the $2.90 left.
The user chose to raise the cap and run the protocol as pre-registered, rather than
stage it (A3) or stop. The ledger is the same (`cost_ledger_rest.jsonl`), and it already
holds the $0.10 spent so far. Arm runs stop at $7.10, so H6 always has its $0.40
sub-cap. H6 checks both its own ledger and the $7.50 total.

**D71. The critic-arm run was interrupted by a laptop crash and resumed, not restarted (2026-11-11).**
- **Interruption:** the laptop crashed during `python -m bench.heal.a2 --run arms`. That
  run had planned 11,403 runs: 381 already done, 11,022 to run. The last log line was
  9,050/11,022, with spend at $4.7683. All DeepSeek runs had finished. Only local Qwen
  `v1_structured` runs were left.
- **Where state lives:** the run records are in the repo (`results/heal_runs.jsonl`),
  and the ledgers and LLM cache are in `bench/heal/_state/` (gitignored). Only the run
  log was in a temp folder. It was copied to `data/phase4/runs/` (now gitignored).
  Before anything else, all four JSONL stores were backed up to
  `data/phase4/runs/backup-20261111T110139/`, with SHA-256 sums.
- **Integrity:**
  - Every line of every store parses, and every file ends with a newline, so there is
    no truncated record. **Nothing was quarantined.**
  - There are 9,903 run ids, all unique. The 840 committed records are byte-identical.
    The 9,063 new records all have status `ok` and are all in the plan.
  - Resume point: **9,444 of 11,403 done, 1,959 to run.** All 1,959 are Qwen runs for
    `v1_structured` (`new`: 5,880/5,880; references: 486/486).
  - The LLM cache has 58 repeated DeepSeek keys with differing texts, going back to the
    baseline runs. These are concurrent identical first calls (adjacent lines). Each run
    record stores the response it got, so no recorded result depends on the cache.
    This was not caused by the crash and is left as is.
- **Environment:**
  - Ollama was down after the crash and was restarted. It serves the same
    `qwen2.5:7b-instruct`, digest `845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e`.
  - The DeepSeek key loads, and the harness key check passes.
  - The rest-of-phase ledger is exactly $4.7683, matching the log.
- **Resume:** the same command with the idempotent skip, started as a detached process
  (`data/phase4/runs/resume_arms.cmd`, logging to `data/phase4/runs/arms_run.log`).
  It reported "11403 runs, 9444 done, 1959 to run". **No completed record was
  altered.** The store is append-only, and the resume only adds the missing run ids.

**D72. The rest-of-Phase-4 cap rises from $7.50 to $9.50 for the fresh-seed confirmations (user decision, 2026-11-11).**
The arms finished at 11,403/11,403 with 0 run errors and $4.7683 spent. The gate
promoted 58 patches on seeds 0–2 (29 per arm). Confirming all of them on seeds 3–5 is
6,090 runs (5,250 DeepSeek). At the measured $0.00071 per arm DeepSeek run, that is about
$3.74, more than the $2.33 left. (The ~$0.5 confirmation estimate in D70 assumed few
promotions.) The user chose to raise the cap and confirm all 58, rather than confirm a
subset or stop. With a subset, the selection rule could not be applied. Arm and
confirmation runs stop at $9.10, which keeps H6's $0.40 sub-cap. The selection rule is
unchanged. The report adds three descriptive items requested by the user:
- the seed-disagreement rate in the arm runs;
- gate promotions per class and per distinct patch, split into `reverts_injection` and
  `other_fix`;
- a cost estimate for the one-time test scoring, made before anything runs on test.

**D73. Phase 4 critic arms on dev: results and the selected arm (2026-11-11).**
Full report: `reports/phase4/critic_arms_dev.md`. The outcome is A1 safe-failure repair,
with the 29-task A2 regression set.
- **`new`** (47 patches): H1 33, H2 33, H3 1, gate 29. Of the 29, 20 are `other_fix` and
  9 `reverts_injection`. 0 gate false promotions on seeds 3–5, 3 old-rule false
  promotions.
- **`v1_structured`** (44 patches): H1 31, H2 32, H3 3, gate 29. Of the 29, 17 are
  `other_fix` and 12 `reverts_injection`. 0 gate false promotions, 2 old-rule false
  promotions.
- **Distinct patches:** every critic patch is a distinct diff (at most 1 failure per
  patch), so the per-distinct counts equal the per-failure ones. The generic arm is the
  exception: 1 patch covering 12 failures.
- **Selection:** the rule picks **`v1_structured`**. Gate false promotions tie at 0, and
  H2 breaks the tie: 32/44 (0.727) vs 33/47 (0.702). The per-distinct counts pick the
  same arm. *Caveat:* the margin comes from `reverts_injection` (12/12 vs 10/12). On
  `other_fix` alone, `new` has the higher H2 (23/35 vs 20/32). The rule is applied as
  pre-registered.
- **No patch passes the gate under the checker outcome.** In both arms every promotion
  comes from the A1 definition (abstaining, or reporting the error or status). PLAN_DRIFT
  is almost unrepaired (1/11 and 0/11). TOOL_MISFIRE and LOOP_DETECTED account for most
  `other_fix` promotions.
- **Seed noise (descriptive):** within seeds 0–2, 6.1% of faulted cells and 0.2% of
  regression cells disagree. Only 9 of 2,073 promoted task outcomes flip on seeds 3–5.
  So the confirmation mostly tests determinism at temperature 0.
- **H6:** kappa is 0.51 (95% CI 0.27–0.72) for the DeepSeek judge and 0.33 (0.08–0.56)
  for the Gemini judge. Raw agreement is 0.95 for both. Only 18 of the 300 runs fail by
  the reference, so the difference is not established.
- **Test scoring:** estimated at about $4.67 plus about 3.5 h of local Qwen. Nothing was
  run on test; it needs its own cap and go-ahead.
- **Spend:** $8.5624 of the $9.50 cap ($8.5129 runs + $0.0495 H6).

**D74. The generic A2 result goes back to its committed values; seed noise gets its own file (2026-11-11).**
Re-scoring for D73 had rewritten `results/heal_generic_a2_dev.json`. Its scored numbers
did not change, but it gained a `seed_noise` block, and the cap it recorded went from
$3.00 (the cap in force when the generic run was made) to $9.50. The file is restored
byte for byte to commit `6403c0d`. `--score` now writes the generic file only under
`--only generic`, and always records the run-time cap (`GENERIC_RUN_CAP_USD = 3.0`).
The seed-disagreement rates for all three arms (D72 item 1, descriptive only) are in a
new file, `results/heal_seed_noise_dev.json`, written by `--score --only seed_noise`;
the report reads them from there. The numbers are unchanged: seeds 0–2 disagree in
45 of 3,683 cells, and 9 of 2,073 promoted task outcomes flip on seeds 3–5. The critic-arm
and selection result files are untouched.

**D75. Amendment A3 (test scoring protocol), the test cap and the dev freeze (2026-11-11).**
The pre-registration says the test sets are built "by the same code and rules", but the
dev failures came from a Phase 3 file, so the test failure sample was not fixed. Nor
was the test evidence, the set of arms, or the cap. A3
(`reports/phase4/amendment_a3.md`) fixes them before any test run.
- **Failures.** Phase 3's `select_labels` runs on the test labels (12 per class), with
  the dev exclusions and the A1 no-observable-harm rule unchanged. Held-out and A2
  regression sets use the dev code and seed strings. This gives 60 failures, 0 label
  exclusions and 9 CONTEXT_BLEED no-harm exclusions, so 51 are scored for
  H1/H2/gate. The TOOL_MISFIRE/ollama held-out pool has only 4 test tasks, so those 4
  failures get 3 held-out tasks; there is no top-up.
- **Evidence.** The frozen Phase 2 detectors run on the 60 selected test traces only,
  using `pred` only, and feed `from_detector`. 59 of the 60 have evidence, and the leak
  assert passed. The output is `reports/phase4/test/evidence.json`. No Phase 2 test
  metric was computed or written.
- **Arms.** No patch, generic, and `v1_structured`. Proposals are generated once, as in
  Phase 3 round 3. Seeds 0–2 for every arm; seeds 3–5 for every gate-promoted patch.
- **Cap.** $5.50 for the whole test scoring (user decision): a critic sub-cap of $0.60,
  and runs capped at $5.50 minus the critic's actual spend. The estimate before any
  test run is $4.54 expected and $5.34 worst case.
- **Freeze.** Tag `phase4-dev-frozen`. Test mode refuses to start unless the tag is an
  ancestor of HEAD and the frozen paths (`bench/heal/freeze.py`) are unchanged.
- **Hygiene.** The older critic integration tests wrote mock proposals to
  `results/critic_dev/proposals.jsonl` whenever Postgres was up. An autouse fixture now
  sends that output to a temp path, and the stray file, which was untracked mock
  output, was removed.

**D76. Phase 4 test scoring under A3: scored once (2026-11-11).**
Frozen code at `phase4-dev-frozen` (`f2a4939`). Runs: seeds 0–2, 6,231 runs; fresh-seed
confirmations for every gate-promoted patch, seeds 3–5, 2,754 runs; 0 run errors.
`--score` ran once and did not crash. An earlier scoring launch was stopped by the user
before it wrote any file, and the same command was then run unchanged. Before Docker
was needed again, the `nexus-*` containers were stopped (`docker compose stop`); the
harness used none of them. Report: `reports/phase4/test_scoring.md`.
- **Coverage.** 50 of the 60 failures got a usable `v1_structured` patch. Of the other
  10, 9 failed the Phase 3 dry run (7 CONTEXT_BLEED, 2 TOOL_MISFIRE) and 1 had a NORMAL
  detector prediction, so no proposal was made. 48 patches are scored on the 51
  eligible failures.
- **Headline, `other_fix`, net of no patch.**
  - H1: 21/36 repaired, against 4/36 with no patch, for a net of +17.
  - H2: 22/36.
  - H3: 12/36 patches break at least one regression task.
  - Gate: 14/36 promoted, against 17/32 on dev.
  - Per class:
    | Class | H1 repaired | Gate promoted |
    |---|---|---|
    | TOOL_MISFIRE | 9/10 | 6/10 |
    | LOOP_DETECTED | 10/12 | 8/12 |
    | PLAN_DRIFT | 1/12 | 0/12 |
    | CONTEXT_BLEED (n = 3 scored; counts only) | 1/2 | 0/2 |
- **`reverts_injection`, reported apart.** HALLUCINATION: 11/12 promoted.
- **H4.**
  | Arm | Old rule promoted | Old-rule false promotions | Gate promoted | Gate false promotions on s3–5 |
  |---|---|---|---|---|
  | `v1_structured` | 32 | 6 | 25 | 0 |
  | generic | 12 | 0 | 12 | 0 |
  | no patch | 3 | 3 | 0 | 0 |
- **Against generic, per eligible failure.** The gate promoted 25/51 for `v1_structured`
  and 12/51 for generic. Generic's 12 are all HALLUCINATION. The critic beats generic on
  TOOL_MISFIRE (6/12 vs 0, generic inapplicable) and LOOP_DETECTED (8/12 vs 0/12). Both
  get 0/12 on PLAN_DRIFT.
- **Dev vs test.** H3 is higher on test: 12/48 against 3/44 on dev. Gate promotions are
  lower: 25/48 against 29/44.
- **Spend.** $4.56 of the $5.50 cap: $0.377 on the critic and $4.185 on runs.

**D77. Phase 5 performance endpoints and SDK loss observability (2026-11-12).**
The headline is the registered 100-occurrence DEV run at concurrency 2; latency,
cost and provider/cache drift are performance measurements. Gate decisions are
descriptive only, not a re-estimate of Phase 4 rates. Frozen logic remains at
`phase4-test-scored`; Windows checkout CRLF-only differences are informational,
with normalized-content identity and empty Git diff both required.

L4 keeps the registered 20-occurrence paired design, using recorded DEV LLM and
tool responses as a deterministic stub so provider latency cannot hide SDK cost.
Two warm-up passes are discarded; latency and fresh-process memory measurements
are separate. Failed HTTP batches have no retry/persistence. Add public
`export_failed` and `dropped_total` span counters in the SDK, preserving the
queue-full-only `dropped` field and all existing export/queue policies. The
10,000-span default queue drops newest; unrestricted metadata/pending spans mean
there is no finite total RAM bound. Historical L4 timings precede the counter fix.

The user's follow-up replaces L3's original concurrency grid with 10 fixed-seed
DEV occurrences at concurrency 1 then 4. Ingestion measures the deployed
classifier and a measurement Postgres sink, separately from the offline heal
detectors; mount the configured cached NLI model read-only rather than benchmark
its missing-model fallback. Keep all paid calls in capped controllers: Part C
DeepSeek $1.50; separate Gemini critic $2.00 and its DeepSeek gates $0.75. Gemini
is a separate first-20 side row with provider-format adaptation documented in
amendment 2. Never pool it into the headline.

The full test suite is collected with `-p no:deepeval`; tests requiring sealed
TEST artifacts remain explicit skips. Keep raw run files out of Git. The
collector's synthetic alerts remain in Kafka with offsets unchanged: automatic
approval review rejected offset advancement as a future-alert skip risk, so
paid consumers remain stopped. Full results and limitations are in
`reports/phase5/results.md`, backed by `results/phase5/*.json`.

**D78. Use the DEV-only test runner for every CI invocation (2026-11-12).**
Main-push CI ran TEST-reading hygiene checks from the Phase 4 merge until
this change. The Actions history contains two such runs:
[43143079344](https://github.com/sankalp-rajeev/Nexus/actions/runs/43143079344)
at `81289ed` and
[43309560963](https://github.com/sankalp-rajeev/Nexus/actions/runs/43309560963)
at `75771ab`.
Both used plain pytest; their test-job logs show the eight checks that the
DEV-only runner skips passing: five result-provenance checks and three fixed
TEST-set consistency checks. The integration jobs also used plain pytest,
but their integration-only selection did not include those eight tests.

These were pass/fail format and consistency checks on already-scored,
committed TEST results and their fixed split manifest. No re-scoring, new
sample, or experiment, model-selection or gate decision resulted. This audit
used workflow history and Actions command/test-status lines, without opening
TEST artifact contents.

From this commit, both CI jobs always invoke
`python scripts/phase5/pytest_dev_only.py -p no:deepeval` with their existing
guarded-run arguments. This applies to every configured PR and push event,
including main pushes, without a branch-name exception. `scripts/phase5/`
and the frozen benchmark logic remain unchanged.
