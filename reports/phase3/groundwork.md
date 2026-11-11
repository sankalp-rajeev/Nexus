# Phase 3 critic groundwork

**Provider:** DeepSeek API for C1/C2/C5; Ollama only for aborted backend diagnostics.

**Model:** `deepseek-flash`, DeepSeek V4.1 Flash; response fingerprint `bc19ba97cbe016479903222bb1578db6`. The API exposes an alias rather than immutable checkpoint selection.

**Mock:** false for every experiment.

**Date:** 2026-11-10 America/New_York (2026-11-11 UTC).

**Implementation commit:** `7d95b152fce05704d9c4bc8a0b04c8a3987d0c3d` (includes initial groundwork commit `7eef3ab`).

**Temperature / prompt:** 0.2 / `critic-groundwork-v1`.


The worktree and branch were verified before any implementation: `nexus-phase3`, `phase-3-critic`, initially exactly at `phase-1-nexusbench` (`75c17e2`). Only the authorized critic, critic unit-test, DEV result, and Phase 3 report paths were changed. No push, merge, tag, Docker Compose invocation, C3, C4, or Phase 4 work was performed.

## Implementation

The critic requests its patch through DeepSeek's strict `propose_patch` function-call schema (the local Qwen provider uses Ollama's JSON-schema `format` parameter), parses the entire response with a strict Pydantic schema, validates against the shared SDK `PatchProposal`, and retains all existing deterministic validator rules. It no longer extracts JSON from prose or Markdown. Diagnosis is part of the same structured call, with at most two generation attempts for schema/validator rejection. The complete trace object, exact current config snapshot, and `FailureEvidence` are sent together without the old 500-character truncation. Trace content is marked untrusted.

`FailureEvidence` identifies a failure type, span or zero-based span index, and supporting observed text. The DEV adapter provides that contract now; production callers can supply it through `run_critic`, the store interface, or the alert's `failure_evidence` field. Trace/agent identity, evidence type, and evidence location must agree before generation.

`ConfigRegistry` permits replacement of existing keys only, enforces value/patch compatibility, and performs the replacement on a deep copy. Clean dry runs are required before writing to the patch store or publishing. Rejections are audited, not promoted. Fallbacks always carry `source=fallback`, are rejected, never count as valid, and never reach the applicable patch store. Mock results carry an explicit mock flag and cannot enter experiment metrics.

Every returned proposal carries source, model, model version or provider alias/fingerprint, temperature, prompt version, input/output tokens, dollars and latency. An unavailable immutable checkpoint is stated explicitly. Retries are included in proposal totals; each generation call has its own append-only ledger entry. Missing usage after a transport failure is recorded as unknown, rather than invented zero tokens. Local diagnostics have $0 API cost. Every paid call first persists a worst-case reservation using the UTF-8 request-byte token bound plus protocol overhead and the maximum output budget. Settlement replaces that reservation logically in the append-only ledger; unknown transport costs retain the full reservation. The branch ledger checks its $0.75 cap before generation. No automatic HTTP retries are used. Gemini is disabled without verified billing credit. Qwen digest changes and DeepSeek fingerprint changes fail closed.

Provenance and rejection metadata use a critic-local `PatchProposal` subclass and append-only audit sidecar because the shared SDK/SQL schema is outside this task's allowlist. The legacy SQL patch row does not retain these extra fields; the sidecar and accepted Kafka payload do. See the integration requests below.

The provider implementations follow the official [DeepSeek strict tool-call documentation](https://api-docs.deepseek.com/guides/tool_calls/) and [Ollama structured-output API documentation](https://github.com/ollama/ollama/blob/main/docs/api.md). DeepSeek accounting uses the published [peak rates](https://api-docs.deepseek.com/quick_start/pricing/): $0.30/M input cache misses, $0.006/M input cache hits and $1.20/M output. All experimental requests began during the weekday 01:00-04:00 UTC peak window; these are token-derived costs, not an independently reconciled billing statement.

## Experiment design and interpretation

C1/C2 use 60 DEV failures: 12 per class, selected deterministically with seed 20261110, preferring distinct tasks and alternating source models where available. This gives 46 distinct tasks. The source-agent mix is 36 DeepSeek traces and 24 Qwen traces: hallucination and misfire each have 12 DeepSeek; drift has 12 Qwen; context bleed and loop each have 6 of each. This is source-agent stratification, not the C4 critic-model comparison. The critic for all scored experiments is the one DeepSeek alias/fingerprint above. Local Qwen diagnostics did not produce completed proposals and were never scored.

The packed CSV/JSONL files are filtered at their split/trace-ID boundaries. Non-DEV payloads are discarded without deserializing them; only DEV labels and selected DEV trace objects are loaded. No TEST labels or trace content were inspected or scored. The sealed-data manifest and relabel integrity tests were deliberately excluded, since they would load TEST records.

C1 is strict structured/shared-schema plus unchanged-validator validity, from the real model without fallback. Registry/dry-run applicability is measured separately as C2 among C1-valid proposals; rejected candidates remain in the audit output. C5 uses two DEV traces per class, three fresh calls per trace, with no response cache or fixed sampling seed. Its joint endpoint requires all three outputs to be C1-valid and to agree on both patch type and target key. Type-only and key-only endpoints are also recorded. C5 trials are separate calls from C1/C2.

All intervals are two-sided exact 95% Clopper-Pearson binomial intervals. C5's unit is the trace, not the 30 calls. The intervals are nominal: traces share tasks, injected fault mechanisms and source models, so they do not establish independent population performance. Per-class stability samples are only two traces.

Applicability here means a replacement can be made safely to a copy of the real constant snapshot. NexusBench does not yet read an injected runtime config. Its current exposed constants provide only the active system prompt, tool specs and step budget; the unchanged validator excludes short target/value text such as `MAX_STEPS` and small numeric replacements. This restricts the patch surface, makes type/key agreement easier, and does not demonstrate repair, diagnosis accuracy, generalization or safety. Those claims require later authorized work.

## Validation

The unit and in-process end-to-end suite passed: **191 passed**. Ruff and `git diff --check` passed. The two tests in `tests/unit/nexusbench/test_dataset_integrity.py` were excluded to keep TEST records sealed; infrastructure integration tests were not run. Classifier model loading used the already installed Hugging Face cache in offline mode after the initial online availability probe was blocked by the sandbox. No classifier code or models were changed.

Command: `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python -m pytest tests/unit/ tests/e2e/ --ignore=tests/unit/nexusbench/test_dataset_integrity.py -q -p no:cacheprovider --basetemp=reports/phase3/pytest_tmp` (PowerShell environment-variable syntax was used when executing). Temporary test files were removed afterward.

## Integration requests

The complete list is in [requests_for_phase2.md](requests_for_phase2.md): detector evidence transport; actual per-agent config registration/runtime consumption; shared provenance/SQL persistence; shared Ollama/DeepSeek provider descriptions; infrastructure-test fixtures for the new fail-closed contract; shared result-index aggregation. No requested change outside the allowlist was made.

## Results

C1: **60/60 (100.0%; 95% CI 94.04-100.00%)**. C2: **59/60 (98.3%; 95% CI 91.06-99.96%)**. C5 joint type/key stability: **10/10 (100.0%; 95% CI 69.15-100.00%)**. C5 type-only and key-only results are identical. The combined C1-valid and applicable share is 59/60; C1 alone is not an applicability claim.

Per class (C5 counts traces, with three fresh outputs each):

- **HALLUCINATION:** C1 12/12 (100.0%; 95% CI 73.54-100.00%); C2 12/12 (100.0%; 95% CI 73.54-100.00%); C5 type, key, and joint each 2/2 (100.0%; 95% CI 15.81-100.00%).
- **TOOL_MISFIRE:** C1 12/12 (100.0%; 95% CI 73.54-100.00%); C2 12/12 (100.0%; 95% CI 73.54-100.00%); C5 type, key, and joint each 2/2 (100.0%; 95% CI 15.81-100.00%).
- **CONTEXT_BLEED:** C1 12/12 (100.0%; 95% CI 73.54-100.00%); C2 11/12 (91.7%; 95% CI 61.52-99.79%); C5 type, key, and joint each 2/2 (100.0%; 95% CI 15.81-100.00%).
- **PLAN_DRIFT:** C1 12/12 (100.0%; 95% CI 73.54-100.00%); C2 12/12 (100.0%; 95% CI 73.54-100.00%); C5 type, key, and joint each 2/2 (100.0%; 95% CI 15.81-100.00%).
- **LOOP_DETECTED:** C1 12/12 (100.0%; 95% CI 73.54-100.00%); C2 12/12 (100.0%; 95% CI 73.54-100.00%); C5 type, key, and joint each 2/2 (100.0%; 95% CI 15.81-100.00%).

Per source-agent model (the critic remains DeepSeek throughout):

- **deepseek/deepseek-flash:** overall C1 36/36 (100.0%; 95% CI 90.26-100.00%); C2 35/36 (97.2%; 95% CI 85.47-99.93%); C5 joint 6/6 (100.0%; 95% CI 54.07-100.00%).
  - HALLUCINATION: C1 12/12 (100.0%; 95% CI 73.54-100.00%); C2 12/12 (100.0%; 95% CI 73.54-100.00%).
  - TOOL_MISFIRE: C1 12/12 (100.0%; 95% CI 73.54-100.00%); C2 12/12 (100.0%; 95% CI 73.54-100.00%).
  - CONTEXT_BLEED: C1 6/6 (100.0%; 95% CI 54.07-100.00%); C2 5/6 (83.3%; 95% CI 35.88-99.58%).
  - LOOP_DETECTED: C1 6/6 (100.0%; 95% CI 54.07-100.00%); C2 6/6 (100.0%; 95% CI 54.07-100.00%).
  - Not represented: PLAN_DRIFT. No estimate or interval is assigned.
- **ollama/qwen2.5:7b-instruct:** overall C1 24/24 (100.0%; 95% CI 85.75-100.00%); C2 24/24 (100.0%; 95% CI 85.75-100.00%); C5 joint 4/4 (100.0%; 95% CI 39.76-100.00%).
  - CONTEXT_BLEED: C1 6/6 (100.0%; 95% CI 54.07-100.00%); C2 6/6 (100.0%; 95% CI 54.07-100.00%).
  - PLAN_DRIFT: C1 12/12 (100.0%; 95% CI 73.54-100.00%); C2 12/12 (100.0%; 95% CI 73.54-100.00%).
  - LOOP_DETECTED: C1 6/6 (100.0%; 95% CI 54.07-100.00%); C2 6/6 (100.0%; 95% CI 54.07-100.00%).
  - Not represented: HALLUCINATION, TOOL_MISFIRE. No estimate or interval is assigned.

## Spend, fallback and rejection audit

**Total spend: $0.183932244**, below the $0.75 cap. C1/C2 cost $0.162160836; C5 cost $0.021771408. All 90 paid calls settled successfully. Paid usage was 664,795 input tokens (including 244,224 cache-hit tokens) and 46,913 output tokens. Input caching reduces billing; no generated output was reused.

**Fallback: 0/60 C1/C2 and 0/30 C5 outputs; zero schema/validator retries.** The one context-bleed dry-run rejection was `nb-d718182cfb24a4e7`, from a DeepSeek-generated source trace: the model proposed `TOOL_CONFIG_PATCH` targeting `read_memory`, a tool name absent from the actual config. It passed the C1 text/schema validator, failed the config registry, received `REJECTED` status, and was not stored. This was a rejected model proposal, not a fallback.

Before the scored run, three local Qwen full-trace requests produced no completed proposal: one timed out after 240 seconds, and two were stopped while waiting. A separate one-token backend probe succeeded (34 input, 1 output). Their API cost was $0; token usage for the three interrupted/timed-out requests is unknown and is recorded as null. Their root cause was not established. They are preserved as diagnostics, excluded from experiment denominators, and do not constitute C4. No Gemini calls were made.

Across the scored run, 76 proposals used `PROMPT_PATCH` and 14 used `TOOL_CONFIG_PATCH`, including the rejected `read_memory` candidate. Accepted tool-spec replacements preserve existing tool names and argument schemas and can change their descriptions. The JSON records preserve every C5 type/target pair. This reinforces the restricted-config-surface limitation above; high validity/stability does not establish repair effectiveness.

Independent result verification recomputed the metrics from the 90 trial records, matched each paid call to its trial tokens/cost/trace, checked the single fingerprint, and reapplied every candidate to an untouched config copy: 89 clean dry runs and the same one rejection across C1/C2/C5.

## Artifacts and reproduction

- [C1 JSON](../../results/critic_dev/c1.json), [C2 JSON](../../results/critic_dev/c2.json), [C5 JSON](../../results/critic_dev/c5.json): counts and full-precision exact intervals, class/source breakdowns, model, implementation commit and date.
- [Trial records](../../results/critic_dev/trials.jsonl), [DEV selection](../../results/critic_dev/selection.json), [call ledger](../../results/critic_dev/calls.jsonl), [cost summary](../../results/critic_dev/cost_summary.json), [verification](../../results/critic_dev/verification.json), [local diagnostics](../../results/critic_dev/local_backend_attempt.json).

The call ledger is append-only: paid calls have reservation and settlement events sharing a `call_id`. Use `CostLedger.rows()` to read each call's latest state and avoid double-counting reservations. `local_selection.json` preserves the selection/provenance from the aborted local attempt.

Selection preflight: `python -m services.critic.experiments --preflight`. Recorded run: `python -m services.critic.experiments --provider deepseek --env-file C:/Umich/Projects/Nexus/.env`. Use the existing key locally; never commit it. The runner refuses to overwrite existing trial records. Generation sampling is deliberately unseeded; selection seed and model fingerprint are recorded.

C3, C4 and Phase 4 were not started.
