# Step 6.3b: the scored detectors on the live path

Date: 2026-11-12. Branch `phase-6-demo`. DEV split only; no provider calls; critic and healer
stayed stopped; no alert was published for any synthetic or DEV trace.

## What changed

The classifier service now runs the **frozen Phase 2 detectors** by default. The legacy pipeline
(rules, MiniLM, PatchCore, NLI, SVM) is still there, behind `NEXUS_CLASSIFIER=legacy`, off by
default. An unknown value is refused at start-up.

| | Before 6.3b | Now (default) |
|---|---|---|
| Service classifier | legacy pipeline | `services/classifier/live_detectors.py` (`DetectorClassifier`) |
| What it calls | `FailureClassifier` | `bench.detector_view.detector_view` then frozen `services/detectors.pipeline` then frozen `services/critic.detector_adapter.from_detector` |
| Detector logic copied | n/a | none |
| Frozen files changed | n/a | none (`check_frozen.py` PASS) |

## Step 1: can the frozen adapter be called on a live trace as-is?

Read-only analysis, done before any code, and the answer is **yes, composed the way Phase 4 did it,
with nothing changed**.

- `services/critic/detector_adapter.py` does **not** run the detectors. `from_detector({"pred":
  label}, view)` takes a label the detectors already produced and *localises* it: it finds the
  failure span by heuristic (first repeated tool call for LOOP, first errored-then-retried call
  for MISFIRE, first planner span's plan for PLAN_DRIFT, and so on) and builds the classification
  record. It insists that the trace id has the opaque `v-...` form that `detector_view` produces.
- The detectors themselves are `services/detectors/pipeline.py`: `compute_scores(trace)`,
  `label(scores, thresholds)`. They read a `CompleteTrace`-shaped object.
- `bench/detector_view.detector_view(dict)` is what turns a trace into the detector view. It
  returns a sanitised `CompleteTrace`: opaque `v-...` id, stripped metadata, canary and customer
  pseudonyms. It is the step Phase 4 always put in front of the detectors. It takes a plain
  `dict`, so a live `CompleteTrace` goes in via `model_dump(mode="json")`.
- So a live trace can be classified with no change to any frozen file: `detector_view` →
  `compute_scores` → `label` → `from_detector`. The one thing that does not come out of the
  frozen code is the *real* trace id (the view's is opaque), so the new adapter maps it back.
- What the detectors need from a span: `tool_name` (falls back to the span type), and, for
  PLAN_DRIFT, a span with `role == "planner"` carrying `plan_steps`. This is what the OTLP
  finding in `otel.md` is about.
- What lite (`services/collector/lite.py`) uses: the same frozen detector modules, called one by
  one (`rules.loop`, `rules.misfire`, `bleed.score`, `drift.flags`), with no HALLUCINATION, no
  NLI model, no torch, no detector view, hard-coded thresholds, and one alert per detector rather
  than one label by precedence. See "Lite" below.

## Which detector configuration is named as the live one

The configuration that produced the Phase 2 TEST score (0.956 macro recall), named in
`live_detectors.detector_config()` and exposed at `/health` under `detector_config`:

| Item | Value |
|---|---|
| Code | frozen `services/detectors/` at git tag `phase2-detectors-frozen` |
| Variant | `pipeline`, **no LLM judge** (the TEST scoring used no Gemini judge) |
| Thresholds | `services/detectors/thresholds.json`: HALLUCINATION 0.5034, CONTEXT_BLEED 1.0, PLAN_DRIFT variant `ungrounded_any_source` |
| Precedence | LOOP_DETECTED, TOOL_MISFIRE, CONTEXT_BLEED, PLAN_DRIFT, HALLUCINATION |
| NLI model | `cross-encoder/nli-deberta-v3-base`, revision `6c749ce3425cd33b46d187e45b92bbf96ee12ec7` (pinned in `.github/model-revisions.json`) |

The service refuses to be healthy if the model staged in the image is not that revision or does not
load (`NLIModelUnavailable`, same mechanism as the legacy NLI check). `/health` shows the staged
revision, so it is checkable from outside. The numbers in this repo for the 0.956 are Phase 2/4
TEST numbers; nothing in this step touched TEST.

## Step 3: DEV-only equivalence with the Phase 2 predictions

`scripts/phase6/live_detectors_equivalence.py`, raw data `results/phase6/live_detectors_equivalence.json`.
Compared with the committed `results/phase2_dev_predictions.json`, over all 359 DEV traces, through
(i) the adapter called directly and (ii) the full service path (`ClassifierService`).

| | Match with Phase 2 DEV predictions |
|---|---|
| Adapter, direct | **359/359 (100 %)** |
| Service path | **359/359 (100 %)** |
| HALLUCINATION NLI score, max abs difference (55 traces that have one) | 0.0 |
| Differences | none; nothing to explain |

Thresholds and config were not touched. By DEV label every group matches fully (CB 30/30, H 34/34,
LOOP 34/34, NORMAL 118/118, OTHER_FAILURE 85/85, PLAN_DRIFT 24/24, MISFIRE 34/34).

## Before and after on DEV labels

`scripts/phase6/live_detectors_before_after.py`, raw data `results/phase6/live_detectors_before_after.json`.
Legacy was run through the real service path; the detectors' predictions are the (equal) Phase 2
predictions. Scored against DEV labels via the DEV adapter. This is a DEV comparison: do not read it
as a TEST number.

| | Legacy classifier | Scored detectors |
|---|---|---|
| Macro recall, HALLUCINATION / CONTEXT_BLEED / PLAN_DRIFT | 0.314 | **0.922** |
| Macro recall, all five classes | 0.565 | **0.953** |
| HALLUCINATION recall / precision | 0.941 / 0.157 (32/204) | 1.000 / 0.971 (34/35) |
| CONTEXT_BLEED recall / precision | 0.000 (0/30) / n/a | 0.767 (23/30) / 1.000 |
| PLAN_DRIFT recall / precision | 0.000 (0/24) / n/a | 1.000 / 1.000 |
| LOOP_DETECTED recall / precision | 1.000 / 0.850 | 1.000 / 1.000 |
| TOOL_MISFIRE recall / precision | 0.882 / 1.000 | 1.000 / 1.000 |
| False alerts on the 118 NORMAL traces | **118/118** | 1/118 |
| Agreement between the two on the same traces | 97/359 | |

The legacy classifier called 288 of 359 DEV traces HALLUCINATION, so on this data it effectively
alerts on every normal trace. That is what the live service was doing until this step. DEV has 7
CONTEXT_BLEED traces the detectors miss; they are reported, not tuned.

## Step 4: the content-missing guard

Lives in the adapter only (`services/classifier/live_detectors.py`); no frozen file changed.

- When the detectors label a trace `LOOP_DETECTED`, the adapter finds the spans that make up the
  loop (the repeated-call run, `loop_runs`). If **all** of them are flagged `nexus.content_missing`
  it does not alert. It recomputes the label with the loop score turned off (so another detector
  that would also fire still fires), and if nothing else fires, the result is `NORMAL` with
  `triggered_rule = "insufficient_content"`.
- It is counted: `/health` carries `insufficient_content_suppressed`.
- It fails open: if the loop cannot be localised, the original alert stands. Native SDK spans
  never carry the flag, so the guard cannot affect them, and a real loop whose spans do have
  captured content still alerts (a loop mixed with captured calls, or with flagged spans
  elsewhere, also still alerts).
- Live check (OTLP with `--no-content`, `--synthetic`): trace `817aab7ff6370ca8766e41d01c6f32c6`
  classified `NORMAL`, `insufficient_content`; counter 1. The same scenario with content
  (`d5320ca5f4fb4ae8aec13d2ee530ff16`) classified `LOOP_DETECTED`, `detectors:loop`, confidence 1.0.

Tests (`tests/unit/classifier/test_live_detectors.py`, 14 tests): the 3-span content-less loop is
not alerted and is counted; the same loop with captured arguments alerts; a mixed run alerts;
flagged spans elsewhere do not hide a real loop; the guard removes only the loop verdict (a
simultaneous misfire still fires); native spans without the flag are never guarded. The rest cover
the flag default and `legacy`, an invalid flag value, the config pins, the model/revision refusal
and the id mapping.

## OTel parity, re-run with the new default

Details in `reports/phase6/otel.md`; data in `results/phase6/otel_parity.json` (the legacy 6.3 numbers
are kept there and in the report as a dated earlier section).

| | Result |
|---|---|
| (a) in-process, 359 DEV traces, plan sent as `nexus.agent.*` | **359/359**, blamed span 359/359 |
| (a) same, plan only as `app.*` attributes | 335/359; the 24 are exactly the DEV PLAN_DRIFT traces |
| (b) end to end, 20-trace subset | **20/20**, equal to the Phase 2 DEV prediction on 20/20 |
| Legacy, for the record (6.3) | 359/359 and 20/20 on its own labels (parity only, quality is in the table above) |

The PLAN_DRIFT finding is real: OpenTelemetry has no notion of a plan, so a plain instrumentation
loses PLAN_DRIFT detection. The mapping accepts opt-in `nexus.agent.role` / `nexus.agent.plan_steps`
(documented in `docs/otel_mapping.md`), with which parity is complete.

## Step 6: time from final span to classification

20-trace DEV subset, end to end, final span's POST returning to the classification appearing on
Kafka. Native traces sent one at a time, OTLP traces every 6 s. One run per cell; 20 samples each.

| Path | Classifier | p50 (s) | p95 (s) | min | max |
|---|---|---|---|---|---|
| Native | **detectors** | 30.6 | 31.2 | 30.2 | 31.4 |
| Native | legacy | 31.4 | 31.8 | 30.6 | 31.8 |
| OTLP | **detectors** | 31.2 | 31.9 | 31.2 | 32.1 |
| OTLP | legacy | 31.8 | 32.2 | 30.9 | 32.6 |

Where the time goes:

- **About 30 s is the assembly idle timeout.** DEV spans carry no `metadata.final`, so the
  assembler completes a trace only after 30 s without a new span (`TraceBuffer`). That is the
  floor for both classifiers and for both transports.
- **Up to ~1 s is the consumer's sweep granularity.** The consumer sweeps for completed traces
  only when `poll` returns nothing (about once a second), so completion is noticed 0 to 1 s late.
- **Compute is the smaller part.** Detector `classify`: p50 ~1.6 ms, p95 ~620 ms, max ~710 ms
  (only the ~15 % of traces that have retrieved context run the DeBERTa NLI model). Legacy
  `classify`: p50 534 ms, p95 808 ms, max 1134 ms. The legacy-versus-detectors gap at p50
  (about 0.6 to 0.8 s) is about the size of the legacy compute, so the new default is a little
  faster, not slower, at the median.
- OTLP is about 0.6 s later than native with either classifier. The classifier compute is
  identical on both paths, so this is in the transport/assembly side (the OTLP trace is converted
  and published by the collector before assembly). I did not isolate it further; with 20 samples
  and 1 s sweep granularity, differences under about a second should not be over-read.

## Step 7: lite

Not unified; the change is not small. Lite is deliberately dependency-light (no torch, no NLI
model), and the frozen `compute_scores` always runs every detector including HALLUCINATION, which
needs torch and the DeBERTa model (the classifier image grew from 2.9 GB to 4.32 GB for this).
Lite keeps calling the individual frozen detectors. The differences are listed in `reports/phase6/infra.md`, section "Step 6.3b:
lite versus the live detectors".

## Image and operations

- Classifier image: 4.32 GB (was 2.9 GB). It now includes `services/detectors`, three files from
  `services/critic` and five from `bench`, copied unmodified, and the DeBERTa model staged by
  `scripts/phase6/prepare_classifier_models.py` and verified offline at build time.
- `/health` fields: `classifier` (`detectors` or `legacy`), `detector_config`,
  `nli_staged_revision`, `insufficient_content_suppressed`.
- Rollback: set `NEXUS_CLASSIFIER=legacy` and recreate the classifier container.

## Process notes

- The earlier TEST-label peek (6.3) is recorded in D79 in `DECISIONS.md`. Nothing from it was used.
- Everything in this step came through the DEV adapter. No TEST file, result or trace was opened.
