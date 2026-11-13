# TRAIL diagnosis

**post-hoc diagnostics on TRAIL-A (development data after scoring)**

This is explanatory analysis, not a new validation result. No v2 change is implemented. TRAIL-B traces and labels were not loaded or evaluated. The original scored JSON, original results report, and original scoring checkpoint remain byte-for-byte unchanged. The accepted pre-A2 mechanical join disclosure remains in A2.

## 1. Scorer sanity - checked before fresh diagnostics

**No scorer/metric bug was found in the checks performed.** Class names exactly match the frozen detector names: `LOOP_DETECTED`, `TOOL_MISFIRE`, `HALLUCINATION`. Category matching follows the registered case/whitespace/punctuation normalization and fixed category list, including the user-specified short `Language-only` term; tool-misfire labels require original OpenInference TOOL identity, including spans retagged as retrieval by A1. No taxonomy expansion was made.

The scorer uses `pipeline.fired`, independently for each class; it does not use the priority-winning label. Saved split counts reconcile with the aggregate, class denominators, precision/recall and Wilson intervals. No correction, replacement result, or v0 scorer-bug file was created.

**Checkpoint limitation:** despite containing completed IDs and running counters, the checkpoints do not contain per-trace predictions, raw detector scores, original `pipeline.label` outputs, or claim entailment values. Therefore those values cannot be recovered or independently re-aggregated from the historical checkpoints. This is an observability gap, not evidence of a metric bug. The saved aggregates determine: both loop/misfire flags were false on all 63 converted traces; hallucination was positive on all 19 eligible traces and abstained on 44. The remaining A trace was excluded for conversion before detector execution.

The user subsequently authorized fresh offline diagnostics. The following raw distributions and pipeline label counts are **fresh diagnostic observations, not historical saved raw outputs**. The observer delegates to the same pinned model and returns its original probability object unchanged; frozen files, thresholds and extraction code are unchanged. Raw trace/claim observations are private under `data/external/trail/diagnostics/`; no claim text is printed or committed.

Consistency check: **0 trace decision differences** versus the decisions recoverable from the original aggregates. Loop/misfire were compared as false per converted trace; every reconstructable eligible hallucination decision was compared as positive, with abstentions kept separate. Exact original numeric-score nondeterminism cannot be tested because the original numeric scores were discarded.

Fresh raw pipeline label counts (63 converted traces; one separate conversion exclusion):

| Pipeline label | Count |
| --- | ---: |
| `CONTEXT_BLEED` | 0 |
| `HALLUCINATION` | 19 |
| `LOOP_DETECTED` | 0 |
| `NORMAL` | 44 |
| `PLAN_DRIFT` | 0 |
| `TOOL_MISFIRE` | 0 |

Independent raw flags (before label priority):

| Detector | True | False |
| --- | ---: | ---: |
| LOOP_DETECTED | 0 | 63 |
| TOOL_MISFIRE | 0 | 63 |
| CONTEXT_BLEED | 0 | 63 |
| PLAN_DRIFT | 0 | 63 |
| HALLUCINATION | 19 | 44 |

Raw NLI score (non-null): n=19; min=1, p25=1, median=1, p75=1, p90=1, p95=1, max=1, mean=1. Null NLI scores: 44. A null produces a false raw threshold flag but remains an abstention in scored metrics.

## 2. Single-label masking

The frozen pipeline exposes a priority label in this order: LOOP_DETECTED, TOOL_MISFIRE, CONTEXT_BLEED, PLAN_DRIFT, HALLUCINATION; otherwise NORMAL. `compute_scores` returns all detector values, and the scorer used all `fired` flags independently.

Internally firing loop flags masked by another label: **0**. Internally firing misfire flags masked by another label: **0**. Masking does not explain the zero loop/misfire alerts. LOOP is first in the priority order and cannot lose to another class.

## 3. LOOP - 22 mapped positive A traces

The frozen rule filters the flattened, completion-ordered spans to TOOL_CALL/MEMORY_READ, parses JSON arguments and sorts JSON keys, then requires three consecutive identical successful tool/name/argument calls. Agent and LLM spans do not break this filtered sequence. A1 retrieval spans are absent from it.

Longest successful identical-consecutive-run distribution visible to the frozen rule:

| Longest run | Count |
| --- | ---: |
| `0` | 2 |
| `1` | 20 |

Diagnostic-only original-OpenInference-TOOL projection (includes A1 retrieval tools, without changing the detector input):

| Longest run | Count |
| --- | ---: |
| `0` | 2 |
| `1` | 20 |

Visible tool steps: 24; original TOOL-origin steps: 169. Traces containing a run of at least three: 0 visible, 0 in the original-TOOL descriptive projection. Restoring retrieval tool visibility alone would not create the required successful three-call pattern in these 22 traces. These are signal descriptions, not rescored v2 accuracy.

Original tool counts per trace: n=22; min=0, p25=1, median=5, p75=12, p90=16.9, p95=17.95, max=39, mean=7.68182. Visible tool counts per trace: n=22; min=0, p25=1, median=1, p75=1, p90=1, p95=1, max=5, mean=1.09091.

Argument-change categories between successive invocations of the same tool (even if other tools intervene):

| Category | Original-TOOL pairs | Visible pairs | Original traces with category |
| --- | ---: | ---: | ---: |
| `exact` | 24 | 0 | 5 |
| `whitespace_only` | 0 | 0 | 0 |
| `json_formatting_or_key_order_only` | 0 | 0 | 0 |
| `ID_pattern_or_ID_field_only` | 0 | 0 | 0 |
| `small_edit_similarity_at_least_0.90` | 40 | 3 | 10 |
| `other_changed_arguments` | 42 | 0 | 14 |

Definitions: whitespace/key-order-only changes must have identical parsed canonical JSON; they are already normalized by v1 and are not evidence of a missed loop. ID-only changes are a descriptive heuristic using ID/UUID fields and explicit identifier patterns. Small edits use SequenceMatcher similarity >=0.90 on canonical arguments of at most 20,000 characters. These categories do not establish semantic equivalence or faulty repetition.

Exact repetitions separated by other original tool steps occur in 5 traces (18 successive identical-key repeat pairs); visible equivalents: 0 traces / 0 pairs. Equal consecutive tool pairs with intervening filtered-out spans occur in 0 original-TOOL traces and 0 visible traces.

Original-TOOL exact adjacent repeat pairs by success/error status:

| Adjacent identical pair | Count |
| --- | ---: |
| `adjacent_exact_pairs_all_statuses` | 14 |
| `adjacent_exact_pairs_both_successful` | 0 |
| `adjacent_exact_pairs_with_error` | 14 |

Longest original-TOOL identical run if success status is ignored (diagnostic description only):

| Longest run, any status | Count |
| --- | ---: |
| `0` | 2 |
| `1` | 15 |
| `2` | 1 |
| `3` | 3 |
| `7` | 1 |

Nesting: 169/169 original tool steps and 24/24 visible tool steps have an agent-step ancestor. Nesting itself cannot make calls non-consecutive at the rule's level: the adapter flattens them and the helper filters away agent/LLM steps. Other retained tool calls break a run; A1's type projection removes retrieval calls altogether.

## 4. HALLUCINATION - 19 eligible A traces

Claims per trace: n=19; min=1, p25=1, median=4, p75=7, p90=8, p95=8.1, max=9, mean=4.21053. Retrieved characters per trace: n=19; min=1820, p25=7427.5, median=20072, p75=26453, p90=59329, p95=74262.7, max=125614, mean=25993.1.

The local model's maximum is **512 tokens per premise/claim pair**, including special tokens. This is not a 512-character whole-trace limit. Frozen retrieval text is split into premises and premise units before NLI. Tokenization was replayed with the same tokenizer and longest-first pair truncation; model probabilities were not altered.

Full pair token lengths: n=15794; min=13, p25=62, median=123, p75=229, p90=306, p95=370.35, max=671, mean=156.043. Truncated pairs: **29/15794**, across 6/19 traces. Removed tokens across pairs: 1436 (1436 premise-side, 0 claim-side). These are repeated pair-token counts, not unique source-text coverage. Removed-token distribution per pair: n=15794; min=0, p25=0, median=0, p75=0, p90=0, p95=0, max=159, mean=0.0909206.

Best entailment per claim before the entity gate: n=80; min=0.00048042, p25=0.00515434, median=0.0471505, p75=0.858249, p90=0.981627, p95=0.984553, max=0.993998, mean=0.332139. After the frozen entity gate: n=80; min=0, p25=0, median=0, p75=0.000878722, p90=0.00534594, p95=0.238793, max=0.993998, mean=0.0401766.

After-gate best-entailment distribution:

| Best entailment bin | Count |
| --- | ---: |
| `exact_zero` | 54 |
| `gt0.1_to_0.25` | 2 |
| `gt0.25_to_flag_cutoff` | 2 |
| `gt0.75_to_0.9` | 0 |
| `gt0.9_to_1` | 2 |
| `gt0_to_0.1` | 20 |
| `gt_flag_cutoff_to_0.75` | 0 |

The frozen gate permits support only from premise units containing every extracted claim entity. It leaves no eligible premise for **54 claims** across 19/19 traces, forcing their best entailment to zero regardless of NLI probability. 78 claims have best entailment <=0.4966; a single sufficiently unsupported claim can flag the entire trace via its worst claim. Here the gate alone algebraically forces the fresh score to 1 on all 19 traces, irrespective of tokenizer truncation. This does not establish what precision an alternative gate would achieve.

All 80 evaluated claims, including all flagged claims, come from `CompleteTrace.final_output`; 0 intermediate-step claim sets are evaluated. Very short answer claims are augmented with root-input question text by the frozen extractor. This is provenance of the detector input, not a claim that every factual statement occurred only at the end.

Mapped hallucination annotation locations within the eligible cohort (location and span-kind rows describe overlapping dimensions of the same annotations; do not add them together):

| Location/kind | Count |
| --- | ---: |
| `non_final_output_carrier` | 5 |
| `raw_kind_LLM` | 5 |

A final-output carrier is defined structurally as a span whose mapped output equals the trace's final output. A non-carrier is a different annotated span, a proxy for an intermediate/local failure; it is not a semantic judgment about the annotation. The final-answer-only detector does not directly localize or score these other spans.

## 5. TOOL_MISFIRE - n=2 mapped positives

**Nothing about misfire performance or a v2 operating point can be concluded from two positive A traces.** The following error-pattern descriptions are for development hypotheses only, not additional evaluation.

Error counts are historical errored-span occurrences, not independent root-cause incidents; a single failure can propagate through nested spans. Provider-related exception class names describe captured dataset events, not provider calls made by this diagnostic run.

All error types across 63 converted A traces:

| Error type | Count |
| --- | ---: |
| `Exception` | 21 |
| `TypeError` | 41 |
| `litellm.exceptions.InternalServerError` | 1 |
| `litellm.exceptions.RateLimitError` | 2 |
| `requests.exceptions.HTTPError` | 2 |
| `scripts.mdconvert.FileConversionException` | 8 |
| `scripts.mdconvert.UnsupportedFormatException` | 1 |
| `smolagents.utils.AgentExecutionError` | 96 |
| `smolagents.utils.AgentGenerationError` | 9 |
| `smolagents.utils.AgentParsingError` | 3 |

Original TOOL-origin error types (including A1-retagged retrieval calls):

| Error type | Count |
| --- | ---: |
| `Exception` | 21 |
| `TypeError` | 41 |
| `requests.exceptions.HTTPError` | 2 |
| `scripts.mdconvert.FileConversionException` | 8 |
| `scripts.mdconvert.UnsupportedFormatException` | 1 |

Error types still visible to the frozen tool-call helper:

| Error type | Count |
| --- | ---: |
| `Exception` | 4 |

Original tool errors: 73 in 19 traces; 69 are on retrieval-retagged spans and 4 remain visible. The frozen rule requires a failed call followed by the same tool and identical canonical arguments within two retained tool calls; a corrected-argument retry is outside that rule.

Retry patterns on the descriptive original-TOOL sequence:

| Error-event pattern (overlaps allowed) | Count |
| --- | ---: |
| `error_events_followed_by_successful_same_tool_in_next_2_original_tool_calls` | 12 |
| `error_events_with_changed_args_retry_in_next_2_original_tool_calls` | 38 |
| `error_events_with_identical_args_retry_in_next_2_original_tool_calls` | 18 |
| `error_events_with_same_tool_in_next_2_original_tool_calls` | 50 |

Within the two mapped-positive traces: 14 original-tool errors, 14 retrieval-retagged errors, 0 visible tool errors. Their original-tool error types:

| Error type | Count |
| --- | ---: |
| `TypeError` | 13 |
| `scripts.mdconvert.UnsupportedFormatException` | 1 |

## 6. Candidate v2 changes - hypotheses, not implemented

| Finding | Candidate development change on A |
| --- | --- |
| 169 original TOOL-origin steps versus 24 visible steps in loop-positive traces; 69 retagged retrieval errors | Preserve tool execution identity and source-evidence role as separate channels; validate both loop/misfire and grounding inputs. |
| Longest-run and argument/interleaving distributions above | Test progress-aware, argument-aware repetition windows and a separate timeout/resource-budget signal; do not assume ID changes or similar text mean a fault. JSON whitespace/key order already normalizes. |
| 14 adjacent identical pairs contain an error; none are two successful calls | Distinguish failed-retry loops from successful stalls and successful recovery, with an explicit v2 fault taxonomy rather than relabeling the v1 result. |
| Entity gate forces zero for 54 claims in 19 traces | On A, audit entity normalization and compare gate behavior with NLI support; avoid treating absent literal aliases as automatic contradiction without validation. |
| Final-output-only claims versus annotation locations on other spans | Explore span-local, time-aware grounding using only evidence available at that step; retain clear scope labels. |
| Only two mapped misfire positives | Obtain a larger development set and separate failed invocation, corrected retry, and failed recovery before choosing v2 rules. |
| Historical raw values were discarded | Persist per-trace detector values and per-claim numeric diagnostics privately, with provenance, so future metric audits need no model rerun. |
| 29 pairs truncate, with 0 claim tokens removed | Audit claim segmentation and paired token budgets on A before any length-aware v2 design; no v1 result changes. |

No priority-order fix is proposed as an explanation: masking counts are zero and the scored evaluation already uses independent flags. No v2 change, threshold, taxonomy expansion, retrieval modification, or metric correction was implemented. A is development data after this post-hoc inspection; v2 must be frozen before its one future B evaluation.

## Provenance and read-only verification

- Original result SHA-256: `9f7781b03307a7447397e29a0d9a8979a351a69b3574db944feb55f656df8235`.
- Original checkpoint SHA-256: `d6e48d479c722a736d31ae40b86a64e9e23c03650bcc2615ac1b7adb1ca12ede`.
- Fresh diagnostic code commit: `0f6f9b239e1d53417ebeb2b262d388499db7379e`; runtime 2394.96 seconds.
- 168 focused synthetic/compatibility tests passed, including observer preservation, truncation accounting, success/error run separation and aggregate-scope tests. Secret and dev-content-copy scans passed before staging.
- Same dataset revision, A IDs, frozen adapter/detectors/config and pinned local NLI model as scoring; offline flags enabled. No provider calls, container/subsystem commands, B data access, frozen-file changes, or scored-result/report edits.
- Only aggregate statistics and permitted trace IDs appear here. Raw per-trace/per-claim observations remain git-excluded under the private diagnostics directory.
