"""Unit tests: LangGraph state machine transitions."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from nexus_agent.models import Alert, CompleteTrace, FailureType, Span, SpanType, TraceStatus

from services.critic.graph import (
    CriticState,
    make_context_loader,
    make_fallback_node,
    validator_node,
)


def _span(idx: int) -> Span:
    return Span(
        span_id=f"span_{idx:02d}", trace_id="t", agent_name="a", span_type=SpanType.LLM_CALL,
        input="some input", output="some output", duration_ms=50.0, metadata={},
        client_timestamp=datetime.now(timezone.utc), sdk_version="1.0.0",
    )


def _trace() -> CompleteTrace:
    return CompleteTrace(
        trace_id="t", agent_name="a", started_at=datetime.now(timezone.utc),
        status=TraceStatus.COMPLETED, span_count=2, spans=[_span(0), _span(1)],
    )


def _base_state(**overrides) -> CriticState:
    base: CriticState = {
        "alert_id": "alert_01",
        "trace_id": "trace_01",
        "agent_name": "testAgent",
        "failure_type": "HALLUCINATION",
        "failure_span_id": None,
        "retry_count": 0,
        "validation_passed": False,
        "patch_proposal": None,
        "final_proposal": None,
        "root_cause_analysis": "",
    }
    base.update(overrides)
    return base


def test_context_loader_calls_db_load_trace():
    mock_db = MagicMock()
    mock_db.load_trace.return_value = _trace()
    loader = make_context_loader(mock_db)
    result = loader(_base_state())
    mock_db.load_trace.assert_called_once_with("trace_01")
    assert result["trace"] is not None


def test_context_loader_handles_missing_trace():
    mock_db = MagicMock()
    mock_db.load_trace.return_value = None
    loader = make_context_loader(mock_db)
    result = loader(_base_state())
    assert result["trace"] is None


def test_validator_passes_good_proposal():
    good = {
        "patch_type": "PROMPT_PATCH",
        "target_component": "llm_system_prompt",
        "explanation": "The system prompt lacked a grounding instruction preventing hallucinations.",
        "patch_content": "SYSTEM: Answer only using provided context. If absent, say so explicitly.",
        "confidence": "HIGH",
        "estimated_impact": "Hallucination rate expected to decrease by 60-80%",
    }
    result = validator_node(_base_state(patch_proposal=good, retry_count=0))
    assert result["validation_passed"] is True


def test_validator_rejects_missing_field():
    bad = {
        "patch_type": "PROMPT_PATCH",
        "target_component": "llm_system_prompt",
        "confidence": "HIGH",
    }
    result = validator_node(_base_state(patch_proposal=bad, retry_count=0))
    assert result["validation_passed"] is False
    assert "explanation" in result["rejection_reason"] or "patch_content" in result["rejection_reason"]


def test_validator_increments_retry_count_on_rejection():
    result = validator_node(_base_state(patch_proposal=None, retry_count=1))
    assert result["retry_count"] == 2


def test_validator_does_not_increment_retry_on_pass():
    good = {
        "patch_type": "PROMPT_PATCH",
        "target_component": "llm_system_prompt",
        "explanation": "The LLM system prompt lacked a context-restriction instruction for grounding.",
        "patch_content": "SYSTEM: Answer only using information present in the provided context.",
        "confidence": "HIGH",
        "estimated_impact": "Hallucination rate expected to decrease by 60-80%",
    }
    result = validator_node(_base_state(patch_proposal=good, retry_count=0))
    assert result["retry_count"] == 0
    assert result["validation_passed"] is True


def test_fallback_node_produces_proposal():
    fallback = make_fallback_node()
    result = fallback(_base_state(failure_type="LOOP_DETECTED", root_cause_analysis="loop found"))
    proposal = result["final_proposal"]
    assert proposal is not None
    assert proposal.failure_type == FailureType.LOOP_DETECTED
    assert proposal.patch_type is not None


def test_fallback_node_all_failure_types():
    fallback = make_fallback_node()
    for ft in [f.value for f in FailureType]:
        result = fallback(_base_state(failure_type=ft, root_cause_analysis="rca"))
        assert result["final_proposal"] is not None


def test_full_graph_runs_end_to_end():
    """Graph should complete without raising and return a PatchProposal."""
    from services.critic.graph import run_critic

    mock_db = MagicMock()
    mock_db.load_trace.return_value = _trace()
    mock_db.write_patch.return_value = None

    alert = Alert(
        trace_id="trace_01",
        agent_name="testAgent",
        failure_type=FailureType.HALLUCINATION,
    )
    proposal = run_critic(alert, mock_db)
    assert proposal is not None
    assert proposal.trace_id == "trace_01"
    mock_db.write_patch.assert_called_once()
