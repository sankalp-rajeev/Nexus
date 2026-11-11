# Phase 3 round 3: stopped at the required leak gate

**Result:** rebase and implementation completed; CI passed. The Part B command stopped before any LLM call because **27 of 58 detector evidence objects contained residual injection text**. No generation results exist. **Spend: $0.00 of the $1.00 cap.**

## Rebase and validation

- Rebased `phase-3-critic` onto `origin/main` merge commit `4636699` (PR #1). No merge commit, push or tag was created.
- The sole rebase conflict was `services/critic/requirements.txt`; main's exact version won. `pytest.ini`, development pins and CI also match main.
- The filled review sheet was committed before rebasing, retaining its verdicts and correcting provenance to model-reviewed and author-confirmed.
- Post-rebase hardening/runner adjustments are a separate implementation commit: `1016c356de4d865944a9cec6a7f3eeee2734a058`.
- CI command: `pytest tests/unit/ tests/e2e/ -v`. **332 passed, 1 skipped**. Both TEST-integrity tests passed. The existing auxiliary `phase2_dev_predictions.json` provenance check is skipped because it is not a result row; no integrity test was excluded.
- `ruff check .` passed. The CI process used local cached classifiers and fixture/mock generative transports; it made no paid generation calls.
- TEST data was read only through the explicitly authorized integrity/CI checks. Critic selection, offline audits and attempted experiment inputs were DEV only. Data and shared files were not edited.
- Evidence: [final CI log](partb_ci_final.log), [initial post-rebase CI log](partb_ci_initial.log), [run status](round3/run_status.json).

## Dry-run hardening and retrospective round-2 audit

Exact no-ops now flag `no_op_patch` and fail the dry run. String comparison is exact; JSON/Python literal config replacements are decoded before comparison. Tool names/arguments are checked against `TOOL_SPECS`. Unknown explicit names/arguments fail the dry run and are recorded in `bad_references`. C1 schema validity remains separate from C2 applicability. The original arm receives these checks post hoc; the two structured arms use them in their dry-run path.

The reference grammar covers JSON/Python literal tool declarations and schemas, literal call syntax, explicit call/invoke/tool-named prose, and tool-specific argument clauses. It distinguishes ordinary parenthetical prose and data helpers from agent tool calls. Dynamic variable-only dispatch and arbitrary natural-language semantics are not proven safe by this deterministic checker. Missing registries are marked unavailable; actual Part B inputs supply the full registry.

All **240 saved round-2 proposals** were inspected against the original benchmark constants read as literals from `phase-1-nexusbench`, with the active fault selected only in the scoring/audit process. Counts below are rule hits, including proposals already rejected by older registry rules; they are not necessarily additional newly rejected proposals. Original round-2 records were not overwritten.

| Saved round-2 arm | Proposals | Exact no-op hits | Bad-reference hits | Both | Hardened dry runs |
|---|---:|---:|---:|---:|---:|
| old_deepseek | 60 | 0 | 5 | 0 | 0 |
| new_deepseek | 60 | 0 | 0 | 0 | 56 |
| new_gemini | 60 | 0 | 0 | 0 | 60 |
| new_qwen | 60 | 0 | 3 | 0 | 0 |

The original arm's five reference hits include the nonexistent `memory_read` tool and unsupported `read_memory` parameters (`key`, `user_id`, `session_id`, `customer_id`). The Qwen hits include unsupported `read_memory.user_id` and `read_memory.consistency_check`. Exact restoration of an injected guessing prompt to the base prompt is a real change, not a no-op.

Per-proposal copies, flags, rejection reasons, source hashes and tags are under [round3_preflight](round3_preflight/round2_hardening.json).

## Reporting-only fault reversal

Every audited round-2 proposal has `fix_tag` and a deterministic `clean_config_diff`; the runner also computes these after each future proposal returns. These fields are excluded from the model response schemas and critic prompts. Exact restoration of any leaf changed between the injected and CLEAN configuration yields `reverts_injection`; otherwise the tag is `other_fix`. Changed values are hashed in the diff. Unknown targets cannot claim a reversal. Partial textual similarity is not an exact restoration.

For this benchmark, the hallucination system prompt is a known injected agent-config value. Other injectors alter runtime data or backend behavior, not this agent-config snapshot, so a fix to those mechanisms is not credited as a config reversal. These tags do not establish successful repair.

The following table is **round-2 retrospective**, not round-3 generation. Each cell is `reverts_injection / other_fix` among 12 proposals per class.

| Class | old_deepseek | new_deepseek | new_gemini | new_qwen |
|---|---:|---:|---:|---:|
| HALLUCINATION | 0 / 12 | 0 / 12 | 6 / 6 | 0 / 12 |
| TOOL_MISFIRE | 0 / 12 | 0 / 12 | 0 / 12 | 0 / 12 |
| CONTEXT_BLEED | 0 / 12 | 0 / 12 | 0 / 12 | 0 / 12 |
| PLAN_DRIFT | 0 / 12 | 0 / 12 | 0 / 12 | 0 / 12 |
| LOOP_DETECTED | 0 / 12 | 0 / 12 | 0 / 12 | 0 / 12 |

Thus 6/12 Gemini hallucination proposals (50%) are exact config reversals, and 6/12 are other fixes. All other class/arm cells have 0/12 reversals and 12/12 other fixes. No round-3 share can be estimated because no proposals were generated.

## Actual-input leak assertion and stop

Invoked once after committing the implementation:

```powershell
python -m services.critic.round3_part_b --env-file C:/Umich/Projects/Nexus/.env
```

The rebased branch is explicitly allowed only when `origin/main` is its ancestor; benchmark trace/label Git objects must match `bench-v1.1` (`afef9aad684630336b543ec3c73e716f8a7c5d3c`). Code must be committed; report artifacts may be dirty. No checkout of main, rebase during the run, or dataset regeneration occurs.

The selection contains 60 DEV failures (12 per class). The detector predicted NORMAL on two, producing no FailureEvidence. **58 unique evidence objects were checked**, shared across the two structured detector arms (**116 planned arm/evidence instances**). **27 unique evidence objects failed**:

| Residual injection text rule | Evidence objects matching |
|---|---:|
| Loop: `is still loading` | 12 |
| Drift: `SYSTEM NOTICE TO ASSISTANT` | 6 |
| Drift: `this order is under audit` | 6 |
| Misfire: `request failed (code 422)` | 9 |

The two drift rules occur in the same six evidence objects; do not sum the rule rows as unique leaks. There were **zero hits** for `dev_label`, `item_users`, `item_sessions`, `item_owners`, or raw `CANARY-...` tokens. The failures are observed injection text that Phase 2 deliberately retains in `detector_view`, not a bypass of its metadata stripping. The adapter currently copies that observed text into supporting evidence.

Per the instruction to stop on any leak, evidence was not redacted, rewritten or regenerated and no retry was made. The exception occurred before original critic construction, embedding-model construction, environment loading, provider construction or any reservation. There is no generation `protocol.json` or `calls.jsonl`; **zero model calls and zero generated proposals**. Details: [leak assertion](round3/leak_assert.json), [command log](partb_run.log).

## Three-arm generation comparison

All three arms stopped at the shared input gate. `N/A` means **not measured**, not zero performance. Round-2 results are not substituted into these cells.

| Metric | Original | v1-prompt-structured | New structured |
|---|---:|---:|---:|
| Generated proposals | 0 | 0 | 0 |
| C1 | N/A | N/A | N/A |
| C2 | N/A | N/A | N/A |
| No-op / bad-reference rejections | N/A | N/A | N/A |
| Exact / near / grounded specificity | N/A | N/A | N/A |
| C3 proposal-type / independent-type / step match | N/A | N/A | N/A |
| reverts_injection / other_fix shares | N/A | N/A | N/A |
| p50 wall latency | N/A | N/A | N/A |
| Dollars per proposal | N/A | N/A | N/A |
| API spend | $0.00 | $0.00 | $0.00 |

C3 type/step results are unavailable for every class (HALLUCINATION, TOOL_MISFIRE, CONTEXT_BLEED, PLAN_DRIFT, LOOP_DETECTED), and for both the detector-correct and detector-wrong splits. No diagnosis denominators exist. The two detector misses are input coverage facts, not critic diagnoses. Likewise all round-3 fault-reversal shares are unavailable per class. No winner or repair-effectiveness conclusion is drawn.

## Specificity proxy agreement

The reviewer sheet contains 10 grounded, 6 ungrounded and 4 unclear judgments. The literal proxy marks 4/20 as grounded. These are model-reviewed, author-confirmed labels revised after Codex feedback; this is not independent human validation. The original hidden key and completed review sheet were scored without changing either.

| Sensitivity treatment | N | Agreements | Agreement | Cohen's kappa |
|---|---:|---:|---:|---:|
| unclear as ungrounded | 20 | 12 | 60.0% | 0.200000 |
| unclear as grounded | 20 | 8 | 40.0% | 0.032258 |
| unclear excluded (supplemental) | 16 | 8 | 50.0% | 0.111111 |

Kappa uses `(observed agreement - expected agreement) / (1 - expected agreement)` with expected agreement from the two observed binary marginals. Confusion counts and file hashes are in [proxy_agreement.json](round3_preflight/proxy_agreement.json). Grounding is judged separately from applicability: a trace-specific harmful patch may still be grounded. No uncertainty interval is inferred from this small stratified, model-assisted review.

## Spend and outstanding work

Aggregate authorized cap: **$1.00**. Actual spend for this Part B attempt: **$0.00**. No billable request or reservation occurred.

The requested three-arm generation and its C1/C2/specificity/C3/latency/cost table remain unmeasured because the required leak gate failed. Continuing would require a deliberate decision about the evidence contract, followed by a fresh clean-input assertion; this attempt did not silently change that contract. The complete preflight work, audit and stop evidence are committed.
