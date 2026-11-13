# Nexus Critic - Pipeline Smoke Test (mock LLM)

> Legacy, pre-rework (before Phase 0). Superseded by RESULTS.md; kept for the record.

- **Provider:** mock
- **Model:** MockProvider
- **Mock:** yes
- **Generated:** 2026-11-10 at commit `9ce9535` by `python tests/fixtures/run_critic_eval.py`
- **Result file:** [`results/critic_smoke_mock.json`](../../results/critic_smoke_mock.json)

> **This is not an evaluation of the critic.** It runs the LangGraph pipeline with a deterministic mock LLM to check that every failure type yields a schema-valid `PatchProposal`. It provides no evidence about real diagnosis or patch quality. Real-model experiments (C1-C5) are tracked in [RESULTS.md](../../RESULTS.md).

- Traces: 20 synthetic (4 per failure type)
- Schema-valid proposal produced: 20/20
- Proposal source: LLM path 0/20, generic fallback template 20/20

## Proposals

| # | Trace ID | Failure Type | Patch Type | Confidence | Source |
|---|---|---|---|---|---|
| 1 | ace_hall0000 | HALLUCINATION | PROMPT_PATCH | LOW | fallback |
| 2 | ace_hall0001 | HALLUCINATION | PROMPT_PATCH | LOW | fallback |
| 3 | ace_hall0002 | HALLUCINATION | PROMPT_PATCH | LOW | fallback |
| 4 | ace_hall0003 | HALLUCINATION | PROMPT_PATCH | LOW | fallback |
| 5 | ce_bleed0000 | CONTEXT_BLEED | MEMORY_PATCH | LOW | fallback |
| 6 | ce_bleed0001 | CONTEXT_BLEED | MEMORY_PATCH | LOW | fallback |
| 7 | ce_bleed0002 | CONTEXT_BLEED | MEMORY_PATCH | LOW | fallback |
| 8 | ce_bleed0003 | CONTEXT_BLEED | MEMORY_PATCH | LOW | fallback |
| 9 | ce_drift0000 | PLAN_DRIFT | PROMPT_PATCH | LOW | fallback |
| 10 | ce_drift0001 | PLAN_DRIFT | PROMPT_PATCH | LOW | fallback |
| 11 | ce_drift0002 | PLAN_DRIFT | PROMPT_PATCH | LOW | fallback |
| 12 | ce_drift0003 | PLAN_DRIFT | PROMPT_PATCH | LOW | fallback |
| 13 | _misfire0000 | TOOL_MISFIRE | TOOL_CONFIG_PATCH | LOW | fallback |
| 14 | _misfire0001 | TOOL_MISFIRE | TOOL_CONFIG_PATCH | LOW | fallback |
| 15 | _misfire0002 | TOOL_MISFIRE | TOOL_CONFIG_PATCH | LOW | fallback |
| 16 | _misfire0003 | TOOL_MISFIRE | TOOL_CONFIG_PATCH | LOW | fallback |
| 17 | ace_loop0000 | LOOP_DETECTED | RETRY_POLICY_PATCH | LOW | fallback |
| 18 | ace_loop0001 | LOOP_DETECTED | RETRY_POLICY_PATCH | LOW | fallback |
| 19 | ace_loop0002 | LOOP_DETECTED | RETRY_POLICY_PATCH | LOW | fallback |
| 20 | ace_loop0003 | LOOP_DETECTED | RETRY_POLICY_PATCH | LOW | fallback |
