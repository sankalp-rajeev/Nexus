"""Generic fallback patch proposals for each failure type (Section 9.2).

Emitted by the `fallback` LangGraph node when the validator rejects a
proposal twice and retry_count >= 2.
"""

from __future__ import annotations

import json

from nexus_agent.models import FailureType, PatchProposal, PatchType


_FALLBACKS: dict[FailureType, dict] = {
    FailureType.HALLUCINATION: {
        "patch_type": PatchType.PROMPT_PATCH,
        "target_component": "llm_system_prompt",
        "explanation": (
            "Hallucination detected: the LLM output was inconsistent with the provided context. "
            "This generic patch adds a grounding instruction to the system prompt. "
            "A targeted patch requires manual inspection of the specific prompt used."
        ),
        "patch_content": (
            "INSTRUCTION: Respond only using information explicitly present in the context provided. "
            "Do not generate facts, names, or details not present in the context. "
            "If uncertain, respond: 'Insufficient context to answer.'"
        ),
        "confidence": "LOW",
        "estimated_impact": "Hallucination frequency expected to decrease; exact improvement unknown without targeted analysis",
    },
    FailureType.CONTEXT_BLEED: {
        "patch_type": PatchType.MEMORY_PATCH,
        "target_component": "memory_store",
        "explanation": (
            "Context bleed detected: memory retrieved from a different session/user. "
            "This generic patch adds a namespace isolation rule to the memory store. "
            "Full fix requires identifying the memory key construction logic."
        ),
        "patch_content": json.dumps({
            "rule": "namespace_isolation",
            "key_prefix_required": "session_{session_id}_user_{user_id}",
            "on_violation": "return empty memory",
        }, indent=2),
        "confidence": "LOW",
        "estimated_impact": "Cross-session data leakage reduced; exact improvement requires targeted audit",
    },
    FailureType.PLAN_DRIFT: {
        "patch_type": PatchType.PROMPT_PATCH,
        "target_component": "planner_system_prompt",
        "explanation": (
            "Plan drift detected: the agent deviated from its declared plan. "
            "This generic patch injects a plan-adherence reminder into the planner prompt. "
            "A targeted fix requires analysis of the specific steps skipped."
        ),
        "patch_content": (
            "RULE: You must execute ALL steps in the plan in the declared order. "
            "Before marking a task complete, confirm it was explicitly performed. "
            "If a step must be skipped, output SKIP_REASON: <reason> before continuing."
        ),
        "confidence": "LOW",
        "estimated_impact": "Plan adherence expected to improve; degree depends on root cause",
    },
    FailureType.TOOL_MISFIRE: {
        "patch_type": PatchType.TOOL_CONFIG_PATCH,
        "target_component": "tool_call_wrapper",
        "explanation": (
            "Tool misfire detected: a tool call failed and was retried with identical bad input. "
            "This generic patch adds minimum input length validation to all tool calls. "
            "Targeted fix requires identifying which tool and argument caused the error."
        ),
        "patch_content": json.dumps({
            "global_tool_guard": {
                "min_input_length": 1,
                "reject_empty_strings": True,
                "on_violation": "skip_call_and_log_warning",
            }
        }, indent=2),
        "confidence": "LOW",
        "estimated_impact": "Empty-input tool errors eliminated; other tool errors require targeted config",
    },
    FailureType.LOOP_DETECTED: {
        "patch_type": PatchType.RETRY_POLICY_PATCH,
        "target_component": "agent_loop_controller",
        "explanation": (
            "Infinite loop detected: the agent repeated the same operation 3+ times. "
            "This generic patch caps total agent steps and enables identical-call deduplication. "
            "Targeted fix requires identifying the missing exit condition in the planning logic."
        ),
        "patch_content": json.dumps({
            "max_steps": 15,
            "max_identical_calls": 1,
            "dedup_key": "tool_name+input_hash",
            "on_loop": "raise LoopLimitError",
        }, indent=2),
        "confidence": "LOW",
        "estimated_impact": "Loop incidents eliminated; agent will fail fast instead of hanging",
    },
    FailureType.NORMAL: {
        "patch_type": PatchType.PROMPT_PATCH,
        "target_component": "agent_system_prompt",
        "explanation": (
            "No specific failure detected; issuing generic health patch as a precaution. "
            "The trace may contain latent issues not captured by the current classifier. "
            "Manual review recommended."
        ),
        "patch_content": "No concrete patch required; trace classified as NORMAL. Review manually.",
        "confidence": "LOW",
        "estimated_impact": "No measurable impact expected",
    },
}


def make_fallback_proposal(alert_id: str, trace_id: str, failure_type: FailureType,
                           root_cause_analysis: str) -> PatchProposal:
    data = _FALLBACKS.get(failure_type, _FALLBACKS[FailureType.NORMAL])
    return PatchProposal(
        alert_id=alert_id,
        trace_id=trace_id,
        failure_type=failure_type,
        root_cause_analysis=root_cause_analysis,
        **{k: v for k, v in data.items()},
    )
