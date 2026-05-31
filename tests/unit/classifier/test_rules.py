"""Unit tests: Stage 1 rule-based pre-filter."""

from __future__ import annotations

from datetime import datetime, timezone

from nexus_agent.models import CompleteTrace, FailureType, Span, SpanType, TraceStatus

from services.classifier.features import input_hash, tool_key
from services.classifier.rules import apply_rules, loop_detector, tool_error_retry


def _span(idx, stype, inp, *, err=None, tool=None, out="ok") -> Span:
    md = {}
    if tool:
        md["tool_name"] = tool
    return Span(
        span_id=f"span_{idx:02d}",
        trace_id="t",
        agent_name="a",
        span_type=stype,
        input=inp,
        output=None if err else out,
        duration_ms=1.0,
        error_type=err,
        error_message="boom" if err else None,
        metadata=md,
        client_timestamp=datetime.now(timezone.utc),
        sdk_version="1.0.0",
    )


def _trace(spans) -> CompleteTrace:
    return CompleteTrace(
        trace_id="t", agent_name="a", started_at=datetime.now(timezone.utc),
        status=TraceStatus.COMPLETED, span_count=len(spans), spans=spans,
    )


def test_loop_detector_fires_on_three_identical():
    spans = [_span(i, SpanType.TOOL_CALL, "q", tool="search") for i in range(3)]
    res = loop_detector(_trace(spans))
    assert res is not None and res.failure_type == FailureType.LOOP_DETECTED
    assert res.triggered_rule == "loop_detector"


def test_loop_detector_no_fire_below_threshold():
    spans = [_span(i, SpanType.TOOL_CALL, "q", tool="search") for i in range(2)]
    assert loop_detector(_trace(spans)) is None


def test_loop_detector_no_fire_distinct_inputs():
    spans = [_span(i, SpanType.TOOL_CALL, f"q{i}", tool="search") for i in range(3)]
    assert loop_detector(_trace(spans)) is None


def test_tool_error_retry_fires_on_identical_retry():
    spans = [
        _span(0, SpanType.TOOL_CALL, "", err="ToolError", tool="search"),
        _span(1, SpanType.TOOL_CALL, "", err="ToolError", tool="search"),
    ]
    res = tool_error_retry(_trace(spans))
    assert res is not None and res.failure_type == FailureType.TOOL_MISFIRE


def test_tool_error_retry_no_fire_without_error():
    spans = [
        _span(0, SpanType.TOOL_CALL, "", tool="search"),
        _span(1, SpanType.TOOL_CALL, "", tool="search"),
    ]
    assert tool_error_retry(_trace(spans)) is None


def test_tool_error_retry_no_fire_different_input():
    spans = [
        _span(0, SpanType.TOOL_CALL, "a", err="ToolError", tool="search"),
        _span(1, SpanType.TOOL_CALL, "b", tool="search"),
    ]
    assert tool_error_retry(_trace(spans)) is None


def test_tool_error_retry_respects_window():
    spans = [_span(0, SpanType.TOOL_CALL, "x", err="ToolError", tool="search")]
    spans += [_span(i, SpanType.AGENT_STEP, f"step{i}") for i in range(1, 5)]
    spans.append(_span(5, SpanType.TOOL_CALL, "x", tool="search"))  # beyond window of 3
    assert tool_error_retry(_trace(spans)) is None


def test_apply_rules_returns_none_on_clean_trace():
    spans = [
        _span(0, SpanType.AGENT_STEP, "plan"),
        _span(1, SpanType.LLM_CALL, "answer"),
    ]
    assert apply_rules(_trace(spans)) is None


def test_input_hash_stable_and_distinct():
    s1 = _span(0, SpanType.TOOL_CALL, "same", tool="t")
    s2 = _span(1, SpanType.TOOL_CALL, "same", tool="t")
    s3 = _span(2, SpanType.TOOL_CALL, "different", tool="t")
    assert input_hash(s1) == input_hash(s2)
    assert input_hash(s1) != input_hash(s3)
    assert len(input_hash(s1)) == 16


def test_tool_key_prefers_tool_name_then_type():
    with_tool = _span(0, SpanType.TOOL_CALL, "x", tool="web_search")
    without = _span(1, SpanType.LLM_CALL, "x")
    assert tool_key(with_tool) == "web_search"
    assert tool_key(without) == SpanType.LLM_CALL.value


def test_apply_rules_loop_takes_priority():
    spans = [_span(i, SpanType.TOOL_CALL, "q", tool="search") for i in range(3)]
    res = apply_rules(_trace(spans))
    assert res.failure_type == FailureType.LOOP_DETECTED
