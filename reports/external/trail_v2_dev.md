# TRAIL v2 development evaluation

**development, not a result**

TRAIL dev and TRAIL-A are development data for this iteration. TRAIL-B remains sealed: no B trace or label was loaded, and no B detector evaluation occurred. NexusBench uses DEV only (359 rows); TEST trace JSON was never decoded or evaluated. No provider calls were made.

## Main merge, tests and isolation

- Fetched origin and merged origin/main with merge commit `d9fef595ae95d5c2d051aaf673611e500aa9ad77`; no conflicts or manual conflict resolutions. 328 merge tests passed, the freeze check passed, and the merge was pushed before v2 work.
- Upstream README/dashboard/SDK release changes arrived through that requested merge. V2 work makes no further edits to those paths.
- `detectors-v2` lives in new `services/detectors_v2/` modules. The original live classifier/default remains v1. Shared frozen files and thresholds are unchanged; `scripts/external/check_frozen.py` passes.
- Original TRAIL v1 result, result report, scoring checkpoints and diagnostic observations are not rewritten. All raw new records and NLI memoization remain under excluded `data/external/trail/v2_development/`.
- Final verification: 350 tests pass, including synthetic C1/C2/C4/both-C5 tests, structural DEV isolation, metric/selection contracts and exact-cache behavior. The 75-file shared freeze and unchanged live-path checks pass. Secret and verbatim-content scans cover explicit publication paths against the allowed 79 development traces/labels, never B.

## Fixed design

The implementation and choices were fixed in [DESIGN.md](../../services/detectors_v2/DESIGN.md) before development evaluation:

- C1: call the existing A1 adapter, retaining matched retrieval errors as TOOL_CALL. Recorded error status or explicit structured/prefixed error output qualifies; successful source operations stay retrieval. Output-only errors receive ToolOutputError. Names, arguments, outputs and existing errors are preserved.
- C2: at least three same-tool calls in a window of six consecutive tool operations; lowercase, punctuation/symbol boundaries and whitespace normalization; pairwise token Jaccard >=0.8 for all pairs in the triple, regardless of success. Executed named/original-TOOL retrieval operations count as tool operations for repetition. Parameters were not tuned.
- C4: the frozen entity extractor is retained; entity/source presence uses casefold, accent removal, punctuation/whitespace normalization and thousands-number canonicalization, searching all retrieved text. Claim splitting, NLI premise construction/model/revision and threshold 0.5034 are unchanged.
- C5 final: final answer only. C5 all_llm: LLM outputs after a source operation, with only sources available in that output's prefix. Both preserve the registered readable-source gate and explicit abstentions. Trace hallucination is the worst eligible output.
- Exact algebraic short-circuits skip inference when an entity gate forces a score of 1 or a worst-output score is already 1. Exact pinned-model pair memoization reuses identical entailments; no approximate pruning or fabricated softmax components.

## Sole selection: C5 HALLUCINATION F1

Selection uses pooled eligible trace-level HALLUCINATION F1 on TRAIL dev + A, computed as 2TP/(2TP+FP+FN). A defined score beats undefined; final wins exact ties. This is the only selection step. Each scope's eligibility and abstentions are shown; NexusBench did not influence selection.

| Scope | Pooled F1 | TP / FP / FN | Evaluated | Abstentions | Exclusions | Dev F1 | A F1 |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| final | 0.387097 | 6 / 19 / 0 | 26 | 52 | 1 | 0.285714 | 0.416667 |
| all_llm | 0.363636 | 6 / 21 / 0 | 27 | 51 | 1 | 0.250000 | 0.400000 |

**Selected and frozen scope: `final`**, config/code commit `5660480673c8a4b3b1f2dbbd0dad6b2438ea3284`. No C1/C2/C4 parameter or threshold selection was performed.

## TRAIL dev + A development tables

Membership is 15 dev + 64 A = 79; the previously known duplicate-span A trace remains the single conversion exclusion for both versions, leaving 78 converted traces. Gold labels and tool-origin qualification follow v1/A1. Null NLI/applicability cases are abstentions, never negatives. Wilson intervals are unrounded in private aggregate records; undefined denominators remain undefined.

### Original v1 mapping

| Version | Class | Evaluated | TP / FP / FN / TN | Precision [Wilson 95%] | Recall [Wilson 95%] | F1 | Abstentions | Exclusions |
| --- | --- | ---: | --- | --- | --- | ---: | ---: | ---: |
| v1 | LOOP_DETECTED | 78 | 0 / 0 / 30 / 48 | undefined | 0.0000 [0.0000, 0.1135] | 0.000000 | 0 | 1 |
| v1 | TOOL_MISFIRE | 78 | 0 / 0 / 3 / 75 | undefined | 0.0000 [0.0000, 0.5615] | 0.000000 | 0 | 1 |
| v1 | HALLUCINATION | 26 | 6 / 19 / 0 / 1 | 0.2400 [0.1150, 0.4343] | 1.0000 [0.6097, 1.0000] | 0.387097 | 52 | 1 |
| v2 selected | LOOP_DETECTED | 78 | 12 / 3 / 18 / 45 | 0.8000 [0.5481, 0.9295] | 0.4000 [0.2459, 0.5768] | 0.533333 | 0 | 1 |
| v2 selected | TOOL_MISFIRE | 78 | 2 / 7 / 1 / 68 | 0.2222 [0.0632, 0.5474] | 0.6667 [0.2077, 0.9385] | 0.333333 | 0 | 1 |
| v2 selected | HALLUCINATION | 26 | 6 / 19 / 0 / 1 | 0.2400 [0.1150, 0.4343] | 1.0000 [0.6097, 1.0000] | 0.387097 | 52 | 1 |

### C3 development mapping

Only the v2 Resource Abuse/Timeout (LOOP_DETECTED) prediction changes to **v2 LOOP OR v2 TOOL_MISFIRE**. The v1 baseline remains its original registered mapping in both tables. Other classes and all gold labels stay unchanged.

| Version | Class | Evaluated | TP / FP / FN / TN | Precision [Wilson 95%] | Recall [Wilson 95%] | F1 | Abstentions | Exclusions |
| --- | --- | ---: | --- | --- | --- | ---: | ---: | ---: |
| v1 | LOOP_DETECTED | 78 | 0 / 0 / 30 / 48 | undefined | 0.0000 [0.0000, 0.1135] | 0.000000 | 0 | 1 |
| v1 | TOOL_MISFIRE | 78 | 0 / 0 / 3 / 75 | undefined | 0.0000 [0.0000, 0.5615] | 0.000000 | 0 | 1 |
| v1 | HALLUCINATION | 26 | 6 / 19 / 0 / 1 | 0.2400 [0.1150, 0.4343] | 1.0000 [0.6097, 1.0000] | 0.387097 | 52 | 1 |
| v2 selected | LOOP_DETECTED | 78 | 12 / 3 / 18 / 45 | 0.8000 [0.5481, 0.9295] | 0.4000 [0.2459, 0.5768] | 0.533333 | 0 | 1 |
| v2 selected | TOOL_MISFIRE | 78 | 2 / 7 / 1 / 68 | 0.2222 [0.0632, 0.5474] | 0.6667 [0.2077, 0.9385] | 0.333333 | 0 | 1 |
| v2 selected | HALLUCINATION | 26 | 6 / 19 / 0 / 1 | 0.2400 [0.1150, 0.4343] | 1.0000 [0.6097, 1.0000] | 0.387097 | 52 | 1 |

### Development observations

On these development inputs, v2 LOOP gains 12 true positives and 3 false positives; v1 flags none. C1 restores 96 failed source operations to tool calls. V2 MISFIRE finds 2 of 3 gold positives with 7 false positives; the three-positive denominator is too small for a reliable general claim. All v2 MISFIRE-positive traces already fire v2 LOOP, so C3 has the same confusion counts as the original mapping here. Selected-scope HALLUCINATION confusion counts equal v1: normalization does not improve the trace decisions on this sample. Every-output C5 has more false positives and one more eligible trace than final-answer C5. These observations did not trigger any additional selection or implementation change.

### Cohort dev: original mapping

| Version | Class | Evaluated | TP / FP / FN / TN | Precision [Wilson 95%] | Recall [Wilson 95%] | F1 | Abstentions | Exclusions |
| --- | --- | ---: | --- | --- | --- | ---: | ---: | ---: |
| v1 | LOOP_DETECTED | 15 | 0 / 0 / 8 / 7 | undefined | 0.0000 [0.0000, 0.3244] | 0.000000 | 0 | 0 |
| v1 | TOOL_MISFIRE | 15 | 0 / 0 / 1 / 14 | undefined | 0.0000 [0.0000, 0.7935] | 0.000000 | 0 | 0 |
| v1 | HALLUCINATION | 7 | 1 / 5 / 0 / 1 | 0.1667 [0.0301, 0.5635] | 1.0000 [0.2065, 1.0000] | 0.285714 | 8 | 0 |
| v2 selected | LOOP_DETECTED | 15 | 5 / 0 / 3 / 7 | 1.0000 [0.5655, 1.0000] | 0.6250 [0.3057, 0.8632] | 0.769231 | 0 | 0 |
| v2 selected | TOOL_MISFIRE | 15 | 0 / 3 / 1 / 11 | 0.0000 [0.0000, 0.5615] | 0.0000 [0.0000, 0.7935] | 0.000000 | 0 | 0 |
| v2 selected | HALLUCINATION | 7 | 1 / 5 / 0 / 1 | 0.1667 [0.0301, 0.5635] | 1.0000 [0.2065, 1.0000] | 0.285714 | 8 | 0 |

### Cohort A: original mapping

| Version | Class | Evaluated | TP / FP / FN / TN | Precision [Wilson 95%] | Recall [Wilson 95%] | F1 | Abstentions | Exclusions |
| --- | --- | ---: | --- | --- | --- | ---: | ---: | ---: |
| v1 | LOOP_DETECTED | 63 | 0 / 0 / 22 / 41 | undefined | 0.0000 [0.0000, 0.1487] | 0.000000 | 0 | 1 |
| v1 | TOOL_MISFIRE | 63 | 0 / 0 / 2 / 61 | undefined | 0.0000 [0.0000, 0.6576] | 0.000000 | 0 | 1 |
| v1 | HALLUCINATION | 19 | 5 / 14 / 0 / 0 | 0.2632 [0.1181, 0.4879] | 1.0000 [0.5655, 1.0000] | 0.416667 | 44 | 1 |
| v2 selected | LOOP_DETECTED | 63 | 7 / 3 / 15 / 38 | 0.7000 [0.3968, 0.8922] | 0.3182 [0.1636, 0.5268] | 0.437500 | 0 | 1 |
| v2 selected | TOOL_MISFIRE | 63 | 2 / 4 / 0 / 57 | 0.3333 [0.0968, 0.7000] | 1.0000 [0.3424, 1.0000] | 0.500000 | 0 | 1 |
| v2 selected | HALLUCINATION | 19 | 5 / 14 / 0 / 0 | 0.2632 [0.1181, 0.4879] | 1.0000 [0.5655, 1.0000] | 0.416667 | 44 | 1 |

### Abstention/exclusion reasons, pooled

| Version | Class | Type | Reason | Count |
| --- | --- | --- | --- | ---: |
| v1 | HALLUCINATION | abstentions | `no_checkable_claims` | 1 |
| v1 | HALLUCINATION | abstentions | `no_successful_retrieval_text` | 51 |
| v1 | HALLUCINATION | exclusions | `conversion_failure` | 1 |
| v1 | LOOP_DETECTED | exclusions | `conversion_failure` | 1 |
| v1 | TOOL_MISFIRE | exclusions | `conversion_failure` | 1 |
| v2 selected | HALLUCINATION | abstentions | `no_checkable_claims` | 1 |
| v2 selected | HALLUCINATION | abstentions | `no_successful_retrieval_text` | 51 |
| v2 selected | HALLUCINATION | exclusions | `conversion_failure` | 1 |
| v2 selected | LOOP_DETECTED | exclusions | `conversion_failure` | 1 |
| v2 selected | TOOL_MISFIRE | exclusions | `conversion_failure` | 1 |

C1 restored 96 errored retrieval spans to TOOL_CALL. Private NLI memo statistics: {'hits': 340, 'misses': 5675, 'seeded_A_pairs': 15794}. These are computational counts, not accuracy claims.

## NexusBench DEV regression check

The existing detector_view is used on 359 DEV traces. Non-DEV rows are discarded on their split field before constructing a label record; trace IDs are filtered before trace JSON decoding. OTHER_FAILURE/RUN_ERROR are excluded from per-class metrics as in the original DEV contract. NLI non-applicability retains native NexusBench negative-flag semantics, unlike the TRAIL-specific abstention rule.

Both independent flags and priority-label views are shown to avoid conflating a detector change with label masking. The original three headline classes are HALLUCINATION, CONTEXT_BLEED, PLAN_DRIFT. Five-class macro also includes LOOP_DETECTED and TOOL_MISFIRE.

| Macro recall view | v1 | v2 | Delta | Drop >0.02 |
| --- | ---: | ---: | ---: | --- |
| macro_recall_five_flags | 0.953333 | 0.953333 | +0.000000 | False |
| macro_recall_five_priority | 0.953333 | 0.929804 | -0.023529 | True |
| macro_recall_headline_flags | 0.922222 | 0.922222 | +0.000000 | False |
| macro_recall_headline_priority | 0.922222 | 0.922222 | +0.000000 | False |

| Version | NORMAL traces | False alerts | False alerts / 1,000 NORMAL |
| --- | ---: | ---: | ---: |
| v1 | 118 | 1 | 8.474576 |
| v2 | 118 | 1 | 8.474576 |

**Regression flags:** macro-recall drop >0.02 = **True**; any false-alert increase = **False**. These flags are reported as observed and did not trigger tuning or reselection.

The priority-view regression comes from four gold MISFIRE traces that additionally fire v2 LOOP. The unchanged priority order emits LOOP for them, reducing MISFIRE priority recall from 34/34 to 30/34, while all 34 MISFIRE flags still fire internally. The added LOOP false positives lower its precision from 1.0000 to 0.8947. No additional NORMAL trace is alerted. The five-class priority macro drops by 0.023529, crossing the requested 0.02 warning threshold. V1 remains live.

### Independent detector flags

| Version | Class | Evaluated | TP / FP / FN / TN | Precision [Wilson 95%] | Recall [Wilson 95%] |
| --- | --- | ---: | --- | --- | --- |
| v1 | CONTEXT_BLEED | 274 | 23 / 0 / 7 / 244 | 1.0000 [0.8569, 1.0000] | 0.7667 [0.5907, 0.8821] |
| v1 | HALLUCINATION | 274 | 34 / 1 / 0 / 239 | 0.9714 [0.8547, 0.9949] | 1.0000 [0.8985, 1.0000] |
| v1 | LOOP_DETECTED | 274 | 34 / 0 / 0 / 240 | 1.0000 [0.8985, 1.0000] | 1.0000 [0.8985, 1.0000] |
| v1 | PLAN_DRIFT | 274 | 24 / 0 / 0 / 250 | 1.0000 [0.8620, 1.0000] | 1.0000 [0.8620, 1.0000] |
| v1 | TOOL_MISFIRE | 274 | 34 / 0 / 0 / 240 | 1.0000 [0.8985, 1.0000] | 1.0000 [0.8985, 1.0000] |
| v2 | CONTEXT_BLEED | 274 | 23 / 0 / 7 / 244 | 1.0000 [0.8569, 1.0000] | 0.7667 [0.5907, 0.8821] |
| v2 | HALLUCINATION | 274 | 34 / 1 / 0 / 239 | 0.9714 [0.8547, 0.9949] | 1.0000 [0.8985, 1.0000] |
| v2 | LOOP_DETECTED | 274 | 34 / 4 / 0 / 236 | 0.8947 [0.7587, 0.9583] | 1.0000 [0.8985, 1.0000] |
| v2 | PLAN_DRIFT | 274 | 24 / 0 / 0 / 250 | 1.0000 [0.8620, 1.0000] | 1.0000 [0.8620, 1.0000] |
| v2 | TOOL_MISFIRE | 274 | 34 / 0 / 0 / 240 | 1.0000 [0.8985, 1.0000] | 1.0000 [0.8985, 1.0000] |

### Priority-winning labels

| Version | Class | Evaluated | TP / FP / FN / TN | Precision [Wilson 95%] | Recall [Wilson 95%] |
| --- | --- | ---: | --- | --- | --- |
| v1 | CONTEXT_BLEED | 274 | 23 / 0 / 7 / 244 | 1.0000 [0.8569, 1.0000] | 0.7667 [0.5907, 0.8821] |
| v1 | HALLUCINATION | 274 | 34 / 1 / 0 / 239 | 0.9714 [0.8547, 0.9949] | 1.0000 [0.8985, 1.0000] |
| v1 | LOOP_DETECTED | 274 | 34 / 0 / 0 / 240 | 1.0000 [0.8985, 1.0000] | 1.0000 [0.8985, 1.0000] |
| v1 | PLAN_DRIFT | 274 | 24 / 0 / 0 / 250 | 1.0000 [0.8620, 1.0000] | 1.0000 [0.8620, 1.0000] |
| v1 | TOOL_MISFIRE | 274 | 34 / 0 / 0 / 240 | 1.0000 [0.8985, 1.0000] | 1.0000 [0.8985, 1.0000] |
| v2 | CONTEXT_BLEED | 274 | 23 / 0 / 7 / 244 | 1.0000 [0.8569, 1.0000] | 0.7667 [0.5907, 0.8821] |
| v2 | HALLUCINATION | 274 | 34 / 1 / 0 / 239 | 0.9714 [0.8547, 0.9949] | 1.0000 [0.8985, 1.0000] |
| v2 | LOOP_DETECTED | 274 | 34 / 4 / 0 / 236 | 0.8947 [0.7587, 0.9583] | 1.0000 [0.8985, 1.0000] |
| v2 | PLAN_DRIFT | 274 | 24 / 0 / 0 / 250 | 1.0000 [0.8620, 1.0000] | 1.0000 [0.8620, 1.0000] |
| v2 | TOOL_MISFIRE | 274 | 30 / 0 / 4 / 240 | 1.0000 [0.8865, 1.0000] | 0.8824 [0.7338, 0.9533] |

## Freeze and review boundary

- V2 frozen config/code commit: `5660480673c8a4b3b1f2dbbd0dad6b2438ea3284`; name `detectors-v2`; selected C5 scope `final`.
- NLI revision: `6c749ce3425cd33b46d187e45b92bbf96ee12ec7`; unchanged frozen threshold file and model.
- Candidate evaluation code commit: `866e68b1fbe856e23e1a5e570e2e8487d3ec8eaf`. TRAIL runtime 1115.28s; NexusBench DEV runtime 46.46s.
- Draft [trail_prereg_a3.md](trail_prereg_a3.md) is a local review artifact and is intentionally not committed. No TRAIL-B scoring is authorized or performed by this development run.
- All new commits contain code, synthetic tests, aggregate development numbers and protocol text only; no gated trace content or annotation descriptions.
