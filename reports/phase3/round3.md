# Phase 3 round 3: Phase 4 detector-evidence handoff

**Status: complete.** The authoritative set is the 59 pre-registered Phase 4 failures, checked against origin/main's bench-v1.1 labels. Only `new` and `v1_structured`, with DETECTOR evidence, are exported for Phase 4. No oracle arm was run.

## Failure-set reconciliation and preservation

Read `reports/phase4/prereg_sets.json` and `bench/heal/{critic,config}.py` by git show at `c2e9df76b6eb8dd3012a98da88600c06bb09c8fa`; no checkout or merge. Compared all 59 against origin/main `46366990ff240753d5d405448092ddbe13ca72b8`, whose labels Git object matches bench-v1.1. **0 mismatches** in the 59, including label, split, task, fault, provider/model and family checks.

The legacy 60-row selection contains one stale row: `nb-b88ecbb93f704868`, PLAN_DRIFT in the selection, NORMAL in main. Phase 4 excludes it. The authoritative set has 12 HALLUCINATION, 12 TOOL_MISFIRE, 12 CONTEXT_BLEED, 11 PLAN_DRIFT and 12 LOOP_DETECTED failures. The legacy selection content is read from Phase 4's committed input copy; it was not tracked at 7d95b15.

The previous run had already finished before the stop request, so no active generation remained. All prior files are preserved byte-for-byte in [prior_selection](round3/prior_selection/preservation_manifest.json). Out-of-set records are in `round3/excluded/`, unused. The original arm is historical and explicitly non-deployable; its 33 in-set and 27 excluded records are retained, and no more original-arm calls were made.

| Detector arm | Kept completed records | Excluded records | Additional records | Final records | Proposals |
|---|---:|---:|---:|---:|---:|
| new | 33 | 27 | 26 | 59 | 57 |
| v1_structured | 33 | 27 | 26 | 59 | 57 |

Completed misses, fallbacks and rejected proposals were kept, not resent. Verification found **0 calls for already completed trace/arm pairs**, no duplicate exports, and no changes to kept model outputs, provenance or call IDs. Reporting-only tags were normalized for Phase 4, with the original tag preserved as `phase3_exact_restore_tag`. See [reconciliation](round3/phase4_reconciliation.json), [migration](round3/phase4_migration.json), and [verification](round3/phase4_verification.json).

## Corrected leak gate

The initial injection-text ban was mis-specified and was corrected before any LLM call in commit fd80793. All 27 prior hits are verbatim observed text: 12 loop messages, 9 misfire errors and 6 drift notes (33 pattern matches). [The 27-hit diagnosis](leak_gate_diagnosis.md) lists the pattern, evidence field and detector-view match for each.

On the authoritative 59 inputs, the corrected gate checked **57 evidence objects and 114 wire string values, with 0 real leaks**. Two detector misses produce no evidence. Reused packets and final exported packets also pass. Every evidence string, including the complete supporting span excerpt, is a literal substring of its official canonical detector_view serialization; embedded JSON is checked for prohibited keys and label values. Raw registry canaries and the raw drift target are forbidden. Observed notes/loading/errors are preserved, not redacted.

Detector labels remain outside FailureEvidence in the Alert/prompt context; the evidence label field is null and contains no authored localization prose. Ground-truth labels, ownership/injection metadata and the raw injection registry never enter critic inputs. The registry is read only by the privileged checker/scorer. See [59-input assertion](round3/phase4_leak_assert.json) and final `phase4_export_leak_<arm>.json` assertions.

## Arm table

C1 is schema/validator validity without fallback over generated proposals. C2 is a successful hardened config-copy dry run among C1-valid proposals. Phase 4's loader adds its own deployed-config checks. These are mechanical checks, not evidence of repair. Exact/near specificity below sums within-class unique strings/components; near uses pinned MiniLM, chunk pooling and cosine >=0.9, with transitive components. Fallbacks are included; LLM-only and per-class results are in JSON.

| Metric | New | v1 structured |
|---|---:|---:|
| C1 | 56/57 (98.2%) | 56/57 (98.2%) |
| C2 (conditional on C1) | 56/56 (100.0%) | 48/56 (85.7%) |
| No-op rejections | 0 | 0 |
| Bad-reference rejections | 0 | 2 |
| Fallbacks | 1/57 (1.8%) | 1/57 (1.8%) |
| Exact distinct (within class) | 57/57 | 57/57 |
| Near-distinct components (within class) | 20/57 | 26/57 |
| Grounded string-match proxy | UNVALIDATED; not used | UNVALIDATED; not used |
| C3 proposal/envelope type match | 56/59 (94.9%) | 56/59 (94.9%) |
| C3 independent diagnosis type match | 36/59 (61.0%) | 55/59 (93.2%) |
| C3 strict step/span match | 2/59 (3.4%) | 21/59 (35.6%) |
| p50 latency (seconds) | 3.889 | 7.248 |
| Cost attributable to retained proposals | $0.152508288 | $0.370064124 |
| Dollars per retained proposal | $0.002676 | $0.006492 |

Latency includes calls/retries and graph work, before scoring/embedding. Cost in the table is attributed to retained exported proposals; total authorized spend below ALSO includes excluded and original-arm history. No-op and bad-reference counts concern returned proposals; counts may overlap other rejection causes. Arbitrary natural-language semantics/dynamic tool dispatch are not proven safe by the deterministic reference grammar.

Both arms use deepseek-flash, temperature 0.2, a maximum of 800 output tokens per call, and disabled thinking. v1_structured makes a structured diagnosis call followed by a structured patch call; new makes the structured patch call directly. Per-call usage, managed model versions/fingerprints and all retries are logged. Retained records span the initial and continuation batches; no model response was regenerated to improve a score.

## C3 per class and detector-wrong split

The envelope type is inherited from the detector and is not an independent diagnosis. The independent type is explicitly returned by the critic. Exact citation scoring uses zero-based positions in full_trace.spans, not actor-step numbers. A conflicting span/index fails. Truth conventions: final-answer root for hallucination, original tool error for misfire, first foreign memory read for bleed, first executed injected-target call for drift, and third repeated successful call for loop. These are operational origin conventions, not causal proof. Missing/fallback diagnoses fail; detector misses remain in pipeline denominators.

### Independent diagnosis type match

| Class | New | v1 structured |
|---|---:|---:|
| HALLUCINATION | 12/12 (100.0%) | 12/12 (100.0%) |
| TOOL_MISFIRE | 0/12 (0.0%) | 11/12 (91.7%) |
| CONTEXT_BLEED | 3/12 (25.0%) | 9/12 (75.0%) |
| PLAN_DRIFT | 10/11 (90.9%) | 11/11 (100.0%) |
| LOOP_DETECTED | 11/12 (91.7%) | 12/12 (100.0%) |

### Strict step/span match

| Class | New | v1 structured |
|---|---:|---:|
| HALLUCINATION | 0/12 (0.0%) | 0/12 (0.0%) |
| TOOL_MISFIRE | 0/12 (0.0%) | 11/12 (91.7%) |
| CONTEXT_BLEED | 1/12 (8.3%) | 10/12 (83.3%) |
| PLAN_DRIFT | 0/11 (0.0%) | 0/11 (0.0%) |
| LOOP_DETECTED | 1/12 (8.3%) | 0/12 (0.0%) |

### Proposal/envelope type match (detector propagation)

| Class | New | v1 structured |
|---|---:|---:|
| HALLUCINATION | 12/12 (100.0%) | 12/12 (100.0%) |
| TOOL_MISFIRE | 12/12 (100.0%) | 11/12 (91.7%) |
| CONTEXT_BLEED | 10/12 (83.3%) | 10/12 (83.3%) |
| PLAN_DRIFT | 11/11 (100.0%) | 11/11 (100.0%) |
| LOOP_DETECTED | 11/12 (91.7%) | 12/12 (100.0%) |


### Detector-wrong split

Each cell is independent type match / strict step match; each has the shown common denominator.

| Class | New | v1 structured |
|---|---:|---:|
| HALLUCINATION | N/A (no detector errors) | N/A (no detector errors) |
| TOOL_MISFIRE | N/A (no detector errors) | N/A (no detector errors) |
| CONTEXT_BLEED | 0/2 / 0/2 | 0/2 / 0/2 |
| PLAN_DRIFT | N/A (no detector errors) | N/A (no detector errors) |
| LOOP_DETECTED | N/A (no detector errors) | N/A (no detector errors) |

The only detector errors in this set are the two CONTEXT_BLEED traces predicted NORMAL. They have no critic call and count as misses in pipeline C3; there are no wrong-class alerted traces on which to measure a critic correcting the detector's class.

## Reporting-only fault-reversal tags

The exported fix_tag uses the exact Phase 4 config.injection_tag contract: normalize _BASE_SYSTEM and _GUESS_SYSTEM to system_prompt, compare with clean/deployed config, and tag restoration or removal of an injected string segment as reverts_injection. This differs from the earlier exact-key/whole-value-only Phase 3 tag; that value is retained in phase3_exact_restore_tag. Tags are computed after generation and never exposed to the critic. Other injectors alter backend/runtime data rather than this config. other_fix is a category, not proof of a valid or effective fix. Each cell is reverts_injection / other_fix, over returned proposals.

| Class | New | v1 structured |
|---|---:|---:|
| HALLUCINATION | 12 / 0 | 12 / 0 |
| TOOL_MISFIRE | 0 / 12 | 0 / 12 |
| CONTEXT_BLEED | 0 / 10 | 0 / 10 |
| PLAN_DRIFT | 0 / 11 | 0 / 11 |
| LOOP_DETECTED | 0 / 12 | 0 / 12 |

## Phase 4 loader validation

Validated with the actual loader read from the pinned Phase 4 commit; no Phase 4 agent execution or healing run occurred. Each JSONL has the expected trace_id, arm, evidence_mode, proposal, c1_valid and dry_run_applied fields, plus top-level and nested source/provenance/tag metadata. Detector misses are explicit no-proposal records. Fallbacks and failed dry runs remain no_patch, never fabricated successes.

| Arm | Loader patch | Loader no_patch | Loader inapplicable | Missing records |
|---|---:|---:|---:|---:|
| new | 56 | 3 | 0 | 0 |
| v1_structured | 48 | 11 | 0 | 0 |

The common critic registry is a baseline snapshot, not a label-selected injected prompt. Phase 4 maps prompt aliases onto the deployed config and makes its own applicability decision. Proposals were not regenerated to improve applicability, and no winner is selected.

## Proxy status, spend and validation

The literal grounded proxy is **UNVALIDATED**, with review kappa **0.20 / 0.03** when unclear is treated as ungrounded/grounded. It is not aggregated or used for arm comparisons. Review was model-reviewed and author-confirmed, revised after feedback, not independent human validation. Historical review agreement is diagnostic only.

**Total accounted spend: $0.912377166 / $1.00**, including $0.680459838 already spent before alignment. Additional spend: $0.231917328. All 393 calls are settled; no reservation is unresolved. Excluded and original-arm costs remain in this total. No new original or oracle calls were made.

| Active arm | All arm spend including excluded history | Retained-proposal attributable spend |
|---|---:|---:|
| new | $0.225313032 | $0.152508288 |
| v1_structured | $0.553915584 | $0.370064124 |

Historical original-arm spend: $0.133148550. Dollar accounting uses the existing conservative token-rate/reservation ledger, not an independently reconciled wallet statement. Source calls, commits and per-proposal call IDs remain auditable in calls.jsonl. Explicit API egress approval covered synthetic DEV data sent to DeepSeek, with the same aggregate cap.

CI command `pytest tests/unit/ tests/e2e/ -v`: **347 passed, 1 existing auxiliary provenance skip**, including both TEST-integrity tests. Ruff clean. Tests cover main-label reconciliation, stream gating, trace/arm idempotence, no-op/reference checks, corrected leak checks, and the actual Phase 4 loader. [CI log](phase4_handoff_ci.log). TEST data was used only by the previously authorized integrity/CI checks, not critic selection/generation. No Docker, push, merge, tags, task replay or dataset edits occurred.

Handoff implementation commit: `82c689aeea0b6bbc687d691e58d622d4e7c08365`. Original generation commit: `1804d3be0acb153b31970ecf194cdb62e2a1d777`. The authoritative export-tag metrics are [phase4_summary.json](round3/phase4_summary.json); raw generation summary remains in summary.json. [Final verification](round3/phase4_verification.json) confirms preserved files, unchanged kept model outputs and zero calls resent for kept pairs.
