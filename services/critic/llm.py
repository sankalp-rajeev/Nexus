"""LLM client abstraction for the critic agent (Section 9.3).

Priority order:
  1. Gemini 2.0 Flash  — if GEMINI_API_KEY is set
  2. Mock provider     — deterministic, structured, no API key needed

The mock returns realistic-looking but hardcoded responses keyed to failure
type, so all tests and the retry-loop logic work without any API key.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Protocol

logger = logging.getLogger("nexus.critic.llm")

_DEFAULT_MODEL = os.getenv("CRITIC_MODEL", "gemini-2.0-flash")
_MAX_RETRIES = int(os.getenv("CRITIC_MAX_RETRIES", "2"))


# ── Protocol ────────────────────────────────────────────────────────────────

class LLMProvider(Protocol):
    def complete(self, prompt: str) -> str: ...


# ── Gemini provider ──────────────────────────────────────────────────────────

class GeminiProvider:
    def __init__(self, model: str = _DEFAULT_MODEL) -> None:
        import google.generativeai as genai  # noqa: PLC0415

        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set")
        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(model)

    def complete(self, prompt: str) -> str:
        response = self._model.generate_content(prompt)
        return response.text or ""


# ── Mock provider (deterministic, no key needed) ─────────────────────────────

_MOCK_ROOT_CAUSE = """\
FAILURE_SPAN_ID: {span_id}
ROOT_CAUSE: The agent repeated the same {failure_type} operation without any corrective action, indicating a missing guard on the execution path.
CONTRIBUTING_FACTORS:
- No input validation before invoking the operation
- Missing loop-break condition in the planning step
CONFIDENCE: HIGH
REASONING:
Step 1: Examined all spans in the trace.
Step 2: Identified span {span_id} as the origin point of the failure.
Step 3: The operation was triggered with identical inputs on successive calls, confirming a deterministic failure path.
"""

_MOCK_PATCH: dict[str, dict] = {
    "HALLUCINATION": {
        "patch_type": "PROMPT_PATCH",
        "target_component": "llm_system_prompt",
        "explanation": (
            "The LLM produced output unrelated to the input context, indicating the system prompt "
            "lacks a grounding instruction. Adding an explicit instruction to restrict answers to "
            "the provided context prevents hallucinated content from appearing in the output."
        ),
        "patch_content": (
            'SYSTEM: You are a precise assistant. Answer ONLY using information present in the '
            'provided context. If the context does not contain the answer, say '
            '"I cannot answer from the available context." Do not introduce external facts.'
        ),
        "confidence": "HIGH",
        "estimated_impact": "Hallucination rate expected to decrease by 60-80%",
    },
    "CONTEXT_BLEED": {
        "patch_type": "MEMORY_PATCH",
        "target_component": "memory_read_validator",
        "explanation": (
            "The memory read returned context from a different session/user, indicating the "
            "memory key lookup is not scoped to the current session. Adding a session+user "
            "scope assertion before returning memory entries prevents cross-session data leakage."
        ),
        "patch_content": json.dumps({
            "rule": "assert_key_scope",
            "condition": "memory_key.startswith(f'session_{current_session_id}_user_{current_user_id}')",
            "on_violation": "raise MemoryScopeError('Context scope mismatch: expected session {current_session_id}, got {actual_session}')",
        }, indent=2),
        "confidence": "HIGH",
        "estimated_impact": "Context bleed incidents expected to drop to near zero",
    },
    "PLAN_DRIFT": {
        "patch_type": "PROMPT_PATCH",
        "target_component": "executor_system_prompt",
        "explanation": (
            "The executor skipped planned subtasks without any verification step, indicating the "
            "executor prompt does not enforce plan adherence. Adding a mandatory checklist "
            "verification step ensures every planned subtask is executed before moving to the next."
        ),
        "patch_content": (
            "SYSTEM: Before proceeding to the next step, verify that ALL previously planned "
            "subtasks are marked complete. Output a checklist: [ ] task_A  [ ] task_B  [ ] task_C. "
            "Do NOT skip any task. If a task cannot be completed, mark it BLOCKED and explain why."
        ),
        "confidence": "HIGH",
        "estimated_impact": "Plan completion rate expected to improve from ~67% to >95%",
    },
    "TOOL_MISFIRE": {
        "patch_type": "TOOL_CONFIG_PATCH",
        "target_component": "tool_input_validator",
        "explanation": (
            "The tool was invoked with an empty or invalid argument, triggering a predictable "
            "ToolError. Adding input validation at the tool boundary rejects empty inputs before "
            "the call is made, preventing the retry loop from wasting calls."
        ),
        "patch_content": json.dumps({
            "validator": "tool_input_guard",
            "rules": [
                {"field": "query", "min_length": 3, "error": "Tool query must be at least 3 characters"},
                {"field": "query", "pattern": r"\S+", "error": "Tool query must not be blank"},
            ],
            "on_violation": "raise ToolInputValidationError with message",
        }, indent=2),
        "confidence": "HIGH",
        "estimated_impact": "Tool error rate expected to drop by >90%",
    },
    "LOOP_DETECTED": {
        "patch_type": "RETRY_POLICY_PATCH",
        "target_component": "agent_execution_loop",
        "explanation": (
            "The agent repeated the same tool call with identical inputs three or more times, "
            "indicating the execution loop has no deduplication guard. Adding a seen-inputs set "
            "and capping identical retries at 1 breaks the loop early and prevents wasted calls."
        ),
        "patch_content": json.dumps({
            "max_identical_retries": 1,
            "deduplication": {
                "enabled": True,
                "key_fields": ["tool_name", "input_hash"],
                "on_duplicate": "raise LoopDetectedError('Identical call detected, breaking loop')",
            },
            "max_total_steps": 20,
        }, indent=2),
        "confidence": "HIGH",
        "estimated_impact": "Infinite loop incidents eliminated; loop detection latency <100ms",
    },
}

_MOCK_PATCH["NORMAL"] = _MOCK_PATCH["HALLUCINATION"]  # fallback for unexpected type


class MockProvider:
    """Returns structured mock responses for all 5 failure types.
    Used when GEMINI_API_KEY is absent or in test mode."""

    def __init__(self, failure_type: str = "HALLUCINATION", span_id: str = "span_00") -> None:
        self._failure_type = failure_type
        self._span_id = span_id

    def complete(self, prompt: str) -> str:
        # root_cause prompt always contains the word "FAILURE_SPAN_ID" in the instructions
        if "FAILURE_SPAN_ID:" in prompt or "Only diagnose" in prompt:
            return _MOCK_ROOT_CAUSE.format(
                span_id=self._span_id, failure_type=self._failure_type
            )
        # patch_proposer prompt contains the JSON schema keyword
        patch = _MOCK_PATCH.get(self._failure_type, _MOCK_PATCH["HALLUCINATION"])
        return json.dumps(patch, indent=2)


# ── Factory ──────────────────────────────────────────────────────────────────

def make_provider(failure_type: str = "HALLUCINATION", span_id: str = "span_00") -> LLMProvider:
    """Return a Gemini provider if the API key is present, else the mock."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if api_key and api_key != "your_gemini_api_key_here":
        logger.info("nexus-critic: using Gemini provider (model=%s)", _DEFAULT_MODEL)
        try:
            return GeminiProvider(_DEFAULT_MODEL)
        except Exception as exc:
            logger.warning("nexus-critic: Gemini init failed (%s); falling back to mock", exc)
    logger.info("nexus-critic: using mock LLM provider (failure_type=%s)", failure_type)
    return MockProvider(failure_type=failure_type, span_id=span_id)
