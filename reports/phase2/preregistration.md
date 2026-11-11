# Phase 2 Pre-registration — Failure Detection on NexusBench

- **Status:** frozen at the commit tagged `phase2-prereg` (local tag). Any later
  change to this file, to `bench/detector_view.py` or to `bench/scoring.py` is a
  *deviation*. It must be logged in a "Deviations" section with its date and reason
  before the test split is scored.
- **Test set:** `data/nexusbench/manifest.sha256`, digest
  `fa191c6d7630d01ff7cf9855d18da0492f9f70ee72aff9096e5f10dd513b8ac5` (357 test
  traces), committed in `0645358` before any detector work.
- **Nothing in this phase has been tuned or scored on the test split.**
  `bench.scoring.load_rows("test")` raises `SealedSplitError` unless
  `unseal=True`, which only the single final scoring run passes.

---

## 1. Detector input contract

Detectors receive only `bench.detector_view.detector_view(trace)`: a Nexus
`CompleteTrace` with spans, inputs, outputs, tool calls, memory reads and plan
spans. The scorer joins predictions back to labels through an opaque
`view_id`.

**Removed or rewritten**

| Where | Field | Why |
|---|---|---|
| trace | `trace_id` → opaque `view_id` | the raw id is the join key to labels.csv (and is a hash of the run id, which names the fault) |
| trace | `source` | benchmark provenance |
| root `agent_step` | `task_id`, `family` | task identity; family determines which faults are possible |
| `llm_call` | `provider`, `model`, `cached` | **label confound:** HALLUCINATION and TOOL_MISFIRE come only from DeepSeek, PLAN_DRIFT only from Qwen |
| `memory_read` | `item_sessions`, `item_users` | written by the fault injector from the world's ownership registry, i.e. the CONTEXT_BLEED label's own evidence |
| all text | canary registry tokens → per-trace `REF-xxxxxx` | injection config (registry); per-trace pseudonyms keep own/foreign distinct within a trace but unlinkable to the registry |
| all text | drift target `C-9417` → per-trace `C-dddd` | injection config; per-trace so a detector cannot learn a constant |

The reading session's own `session_id` / `user_id` stay: production knows who
is reading.

**CI test:** `tests/unit/nexusbench/test_detector_view.py`, run over every
committed trace. It fails if:
- any labels.csv column name is a key anywhere in a view;
- any trace, run or task id, fault or label name, or model or provider name
  appears as a value;
- any canary registry token, another user's session id, or `C-9417` appears;
- detector code under `services/classifier/` or `services/detectors/` contains
  any residual injection string listed below.

As a check that the test isn't vacuous, the raw traces fail it. All 716 expose
the task id, family and model, 248 expose canary tokens, 150 expose `C-9417`,
and 257 expose `item_sessions`.

**Residual injection text (kept, because the agent really saw it).** Counts
are over all 716 views, by label:

| String | Traces | By label |
|---|---|---|
| drift note "SYSTEM NOTICE TO ASSISTANT … under audit" (in `get_order` output) | 150 | PLAN_DRIFT 46, NORMAL 104 (model ignored it) |
| loop message "is still loading" | 72 | LOOP_DETECTED 60, OTHER_FAILURE 12 |
| misfire error "request failed (code 422)" | 150 | TOOL_MISFIRE 59, OTHER_FAILURE 90, LOOP_DETECTED 1 |

These strings mark the injected *fault*, not the labelled *behaviour*. Grepping
for the drift note gives PLAN_DRIFT precision of 46/150. Detectors must not
match on them; CI enforces this.

## 2. Label rule vs detector signal

| Class | Label rule (ground truth, `bench/labeler.py`) | Planned detector signal (sees only the view) | Why they are not the same check |
|---|---|---|---|
| HALLUCINATION | qa: answer wrong vs **gold**, not an abstention, and its claim is absent from a retrieved document **about the target company** (uses the world registry) | split the final answer into claims and check each against the retrieved context with an NLI cross-encoder; abstentions are not claims | The detector has no gold and no registry. It flags unsupported answers even when they're right by luck, and it can be fooled by a fact borrowed from another company's document that the label rule rejects. |
| CONTEXT_BLEED | a memory read returned an item owned by another session (registry), or a foreign canary is in the answer | a memory read for one user returns more than one profile record, or conflicting values for a single-valued attribute (tier, home city) | The detector has no ownership data. It misses a foreign record whose values match the user's own, and would false-alarm on benign multi-record reads. ⚠️ **Caveat:** NexusBench has no benign multi-record reads, so on dev this signal coincides with the label (30/30 positives, 0 false positives). The two are equivalent **by construction of the benchmark**, though not by nature. See §5. |
| PLAN_DRIFT | the agent called a tool with the injected target id (`C-9417`, known from the injection config) | align executed tool calls with the planner's declared `plan_steps`; flag calls outside the plan whose arguments carry an id that's neither in the user request nor a data field of an earlier tool result | The detector doesn't know the target and has to infer it from where the id came from. On dev, "executed a tool not in the plan" fires on all 20 PLAN_DRIFT traces but also on 20 NORMAL, 21 OTHER_FAILURE and 18 CONTEXT_BLEED traces, so the alignment signal is not the label. |
| TOOL_MISFIRE | tool error followed by an identical retry within 2 calls | the Stage-1 rule `tool_error_retry` (identical call within 3 spans of an errored tool span) | **The same check by nature:** the failure is defined by this behaviour. Marked **rule-defined, not headline.** |
| LOOP_DETECTED | ≥ 3 consecutive identical successful calls | the Stage-1 rule `loop_detector` (≥ 3 identical calls anywhere in the trace) | **The same check by nature** (the detector is slightly looser: not necessarily consecutive or successful). Marked **rule-defined, not headline.** |

## 3. Pre-registered analysis

1. **Headline metric:** macro recall over HALLUCINATION, CONTEXT_BLEED and
   PLAN_DRIFT on the test split, reported with each class's precision.
   Recall is never reported without precision.
2. **Target:** recall ≥ 0.80 at precision ≥ 0.90, for each headline class and
   for the macro. The result is reported whether or not it is met.
3. **OTHER_FAILURE:** excluded from per-class scoring, so it is neither a
   positive nor a negative for any class. In the binary "any failure" view,
   flagging an OTHER_FAILURE trace as a failure counts as a true detection.
   RUN_ERROR traces are excluded everywhere (there are 0).
4. **Operating point:** chosen on **dev only**, separately for each detector,
   by maximising dev recall subject to dev precision ≥ 0.90. If no threshold
   reaches 0.90 on dev, the threshold with the highest dev precision is used,
   and that is reported. Thresholds are frozen before the test split is
   unsealed.
5. **Intervals:** Clopper-Pearson exact 95% for every proportion
   (`bench.scoring.clopper_pearson`).
6. **Test scored once:** a single run with `unseal=True`, after all dev work
   and thresholds are committed. The output file records the commit it ran at.
7. **Per-model reporting:** every result is reported for all models and
   separately for DeepSeek (`deepseek-flash`) and Qwen (`qwen2.5:7b-instruct`).
   **Single-model classes:**
   - **HALLUCINATION:** DeepSeek only (Qwen abstains).
   - **TOOL_MISFIRE:** DeepSeek only (Qwen gives up after the error).
   - **PLAN_DRIFT:** Qwen only (DeepSeek ignores the injection).
   - CONTEXT_BLEED and LOOP_DETECTED come from both models.

   A per-model macro averages only the headline classes present for that model.
8. **Baseline to beat:** the shipped v3 classifier on dev (§4), scored with
   the same code and the same input contract. The test comparison (D2) uses the
   baseline at its shipped operating point.

**Label support** (from labels.csv; counts only, no scoring):

| Label | dev DeepSeek | dev Qwen | test DeepSeek | test Qwen |
|---|---|---|---|---|
| NORMAL | 76 | 50 | 81 | 49 |
| HALLUCINATION | 30 | 0 | 30 | 0 |
| CONTEXT_BLEED | 12 | 18 | 18 | 12 |
| PLAN_DRIFT | 0 | 20 | 0 | 26 |
| TOOL_MISFIRE | 27 | 0 | 32 | 0 |
| LOOP_DETECTED | 17 | 16 | 19 | 9 |
| OTHER_FAILURE | 9 | 84 | 7 | 74 |

**Known limits of the benchmark that bound every conclusion:**
- **No natural failures.** All 140 uninjected runs passed, so every failure is
  injected and results say nothing about naturally occurring failures.
- **PLAN_DRIFT has only 46 traces** (dev 20, test 26), below the 60 target
  (the attempt cap was hit). The test recall interval will be wide (n=26).
- **Every class except CONTEXT_BLEED and LOOP_DETECTED comes from a single
  model,** so a per-class result is also a per-model result.

## 4. Dev baseline (shipped classifier through the view)

Source: [`results/detect_baseline_dev.json`](../../results/detect_baseline_dev.json),
[`baseline_dev.md`](baseline_dev.md). Dev split only (359 traces).

| Class | Kind | Dev recall | Dev precision |
|---|---|---|---|
| HALLUCINATION | headline | 0.933 (28/30; CP 0.78–0.99) | 0.138 (28/203; 0.09–0.19) |
| CONTEXT_BLEED | headline | 0.000 (0/30; 0.00–0.12) | n/a (never predicted) |
| PLAN_DRIFT | headline | 0.000 (0/20; 0.00–0.17) | n/a (never predicted) |
| TOOL_MISFIRE | rule-defined | 1.000 (27/27; 0.87–1.00) | 1.000 (27/27; 0.87–1.00) |
| LOOP_DETECTED | rule-defined | 1.000 (33/33; 0.89–1.00) | 0.917 (33/36; 0.78–0.98) |

Headline macro recall **0.311**, and secondary macro (HALLUCINATION, PLAN_DRIFT)
**0.467**. Neither number is meaningful: the SVM
labels every trace that no rule catches as HALLUCINATION, including all 126
NORMAL and all 93 OTHER_FAILURE dev traces. The 0.933 hallucination recall is
therefore a side effect of flagging everything, which is why the precision
gate exists. "Any failure" recall is 1.000 at precision 0.649 for the same
reason. Per model: DeepSeek macro 0.467 (hallucination precision 0.241), Qwen
macro 0.000. Only the two rule-defined classes work.

## 5. Open issue for review (decide before Phase 2 detector work)

On this benchmark, CONTEXT_BLEED's structural signal is equivalent to its
label by construction (§2). Options:

- **(a) Keep it as pre-registered** and report CONTEXT_BLEED with the caveat. The
  headline would then partly measure the injector.
- **(b) Add a secondary headline** of macro recall over HALLUCINATION and
  PLAN_DRIFT only, reported next to the primary.
- **(c) Before tuning anything, add benign multi-record memory** (users with
  two legitimate notes) to a new benchmark version. That decouples the signal
  from the injector, but it means regenerating, re-splitting and re-freezing.

This document pre-registers **(a) and (b) together**: the primary headline as
specified, plus the secondary H+PD macro. Choosing (c) would be a logged
deviation made before any test scoring.

## Deviations

None.

## Amendment 1 — make CONTEXT_BLEED non-trivial (2026-11-10)

Committed **before** any code change. The test split had not been scored,
loaded or inspected beyond label counts when this amendment was written. The
original pre-registration stays at tag `phase2-prereg`; this amendment and its
data are frozen at tag `phase2-prereg-v2`.

**Why.** On dev, "a memory read returned more than one record" matches the
CONTEXT_BLEED label exactly (30/30 positives, 0 false positives), because in
NexusBench v1 only the fault injector ever produced multi-record reads. A
detector using that signal measures the injector, not bleed (§2, §5).

**What changes (in `bench/` only):**

1. **Memory content.** Each user has 1–4 of their own notes: an account-tier
   note plus optional notes such as home city, contact preference, account
   manager and tier or address history. Some users belong to a team whose
   shared notes are visible to every member. A seeded share of users has a
   single note and no team, so record counts overlap between NORMAL and bleed
   runs. Target: at least 40% of NORMAL traces that read memory get more
   than one record. The memory content uses its own RNG stream, so the world,
   the tasks and their gold answers don't change.
2. **Records carry no owner, session or user fields**, in the record text or in
   anything visible through `detector_view`. Canary tokens are removed from the
   note text.
3. **Bleed injection.** The store returns 1–2 records belonging to another user,
   mixed in with the user's own and team records at seeded positions.
4. **CONTEXT_BLEED label.** A memory read returned a record whose owner, per
   the ownership registry, is neither the reading user nor a team the user
   belongs to. The registry is never visible to detectors. The v1 "foreign
   canary in the answer" clause is dropped, because canaries no longer appear
   in text.
5. **Regeneration.** Only traces whose run called `read_memory` are regenerated
   (257 of 716). They keep their run ids, trace ids, seeds, providers and
   attempt order. The other 459 trace lines stay byte-identical. If the bleed
   injection becomes less effective, the CONTEXT_BLEED attempt sequence
   continues in the same seeded order, up to the existing 150-attempt cap. No
   other class is topped up. Spend cap for the regeneration: $1.00 DeepSeek.
6. A **new test manifest** is written, and the leak and integrity checks re-run.

**What stays fixed:** task ids and the dev/test assignment (`splits.json`); all
other fault injectors (HALLUCINATION, PLAN_DRIFT, TOOL_MISFIRE, LOOP_DETECTED);
the other label rules; the metrics, targets and operating-point rule (§3); the
scoring code and the detector input contract, except that the memory metadata
the injector writes is still stripped.

**Separability gate (dev only).** Before detector work, trivial single-field
rules are scored for CONTEXT_BLEED vs everything else on dev. If any one of
them reaches precision ≥ 0.95 **and** recall ≥ 0.95, the headline falls back to
the pre-registered secondary (macro recall over HALLUCINATION and PLAN_DRIFT),
and CONTEXT_BLEED is reported as non-headline.
