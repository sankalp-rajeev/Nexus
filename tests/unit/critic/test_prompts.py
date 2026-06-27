"""Unit tests: prompt formatting helpers."""

from __future__ import annotations

from datetime import datetime, timezone


from nexus_agent.models import CompleteTrace, Span, SpanType, TraceStatus

from services.critic.validator import format_failure_span, format_trace_for_prompt


def _span(idx: int, stype=SpanType.LLM_CALL, inp="input text", out="output text",
          *, err=None) -> Span:
    return Span(
        span_id=f"span_{idx:02d}", trace_id="t", agent_name="a", span_type=stype,
        input=inp, output=out, duration_ms=50.0, error_type=err,
        error_message="boom" if err else None, metadata={},
        client_timestamp=datetime.now(timezone.utc), sdk_version="1.0.0",
    )


def _trace(*spans) -> CompleteTrace:
    return CompleteTrace(
        trace_id="t", agent_name="a", started_at=datetime.now(timezone.utc),
        status=TraceStatus.COMPLETED, span_count=len(spans), spans=list(spans),
    )


def test_format_trace_contains_span_ids():
    t = _trace(_span(0), _span(1))
    formatted = format_trace_for_prompt(t)
    assert "span_00" in formatted
    assert "span_01" in formatted


def test_format_trace_includes_span_type():
    t = _trace(_span(0, SpanType.TOOL_CALL, "query", "result"))
    formatted = format_trace_for_prompt(t)
    assert "TOOL_CALL" in formatted


def test_format_trace_includes_error():
    t = _trace(_span(0, err="ToolError"))
    formatted = format_trace_for_prompt(t)
    assert "ToolError" in formatted


def test_format_trace_truncates_long_input():
    long_input = "x" * 1000
    t = _trace(_span(0, inp=long_input))
    formatted = format_trace_for_prompt(t)
    assert "x" * 501 not in formatted


def test_format_failure_span_by_id():
    spans = [_span(0), _span(1), _span(2)]
    t = _trace(*spans)
    content = format_failure_span(t, "span_01")
    assert "span_01" in content


def test_format_failure_span_falls_back_to_last():
    t = _trace(_span(0), _span(1))
    content = format_failure_span(t, "nonexistent_span_id")
    assert "span_01" in content


def test_format_failure_span_unknown_id_uses_last():
    t = _trace(_span(0), _span(3))
    content = format_failure_span(t, None)
    assert "span_03" in content
