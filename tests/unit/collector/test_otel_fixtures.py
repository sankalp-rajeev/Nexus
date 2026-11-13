"""The DEV-trace -> OTLP converter used for parity (hand-made spans; no NexusBench data)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

from nexus_agent.integrations.otel import span_batches
from nexus_agent.models import CompleteTrace, Span, SpanType
from scripts.phase6 import otel_fixtures as fx

T0 = datetime(2026, 11, 11, 0, 48, 22, 753233, tzinfo=timezone.utc)


def make(span_id, kind, parent=None, **overrides):
    values = dict(span_id=span_id, trace_id="nb-test", parent_span_id=parent, agent_name="nexusbench_agent",
                  span_type=kind, input="in " + span_id, output="out " + span_id, duration_ms=1.5,
                  client_timestamp=T0, environment="nexusbench", sdk_version="0.1.0", metadata={})
    values.update(overrides)
    return Span(**values)


@pytest.fixture
def trace():
    spans = [
        make("s1", SpanType.LLM_CALL, "s0", metadata={"model": "m", "provider": "p", "input_tokens": 7, "output_tokens": 3,
                                                       "tokens_used": 10, "role": "actor", "cached": True}),
        make("s2", SpanType.TOOL_CALL, "s0", error_type="ToolError", error_message="bad args", output=None,
             metadata={"tool_name": "get_order"}),
        make("s3", SpanType.MEMORY_READ, "s0", metadata={"tool_name": "read_memory", "user_id": "u1"}),
        make("s0", SpanType.AGENT_STEP, None, metadata={"role": "planner", "plan_steps": ["a", "b"]}),
    ]
    return CompleteTrace(trace_id="nb-test", agent_name="nexusbench_agent", environment="nexusbench",
                         started_at=T0, span_count=4, spans=spans)


def mapped(trace, **kwargs):
    request = ExportTraceServiceRequest()
    request.ParseFromString(fx.trace_to_otlp(trace, **kwargs).SerializeToString())
    return [s for batch in span_batches(request) for s in batch.spans]


def test_round_trip_preserves_what_the_classifier_reads(trace):
    out = mapped(trace)
    assert [s.span_type for s in out] == [s.span_type for s in trace.spans]
    for a, b in zip(trace.spans, out, strict=True):
        assert (a.input, a.output, a.error_type, a.error_message) == (b.input, b.output, b.error_type, b.error_message)
        assert a.client_timestamp == b.client_timestamp
        assert abs(a.duration_ms - b.duration_ms) < 1e-6
        assert (a.agent_name, a.environment) == (b.agent_name, b.environment)
    llm, tool, memory, agent = out
    assert (llm.metadata["model"], llm.metadata["provider"], llm.metadata["tokens_used"]) == ("m", "p", 10)
    assert tool.metadata["tool_name"] == "get_order"
    # documented limit: a memory read has no semconv tool name
    assert "tool_name" not in memory.metadata
    assert "nexus.content_missing" not in llm.metadata


def test_parents_follow_the_span_order(trace):
    out = mapped(trace)
    ids = {s.span_id: i for i, s in enumerate(out)}
    assert [ids.get(s.parent_span_id) for s in out] == [3, 3, 3, None]


def test_unmapped_metadata_is_kept_only_as_custom_attributes(trace):
    llm = mapped(trace, plan_attributes=False)[0]
    assert llm.metadata["otel.attributes"]["app.role"] == "actor"
    assert llm.metadata["otel.attributes"]["app.cached"] is True
    assert "role" not in llm.metadata
    assert mapped(trace)[0].metadata["role"] == "actor"  # the documented attribute carries it on any span


def test_synthetic_marker_is_a_boolean_on_every_mapped_span(trace):
    assert all(s.metadata["nexus.synthetic"] is True for s in mapped(trace, synthetic=True))
    assert all("nexus.synthetic" not in s.metadata for s in mapped(trace))


def test_ids_are_valid_otlp_and_deterministic_per_salt(trace):
    first, again, salted = mapped(trace, trace_salt="a"), mapped(trace, trace_salt="a"), mapped(trace, trace_salt="b")
    assert [s.span_id for s in first] == [s.span_id for s in again]
    assert first[0].trace_id != salted[0].trace_id
    assert all(len(s.trace_id) == 32 and len(s.span_id) == 16 for s in first)


def test_native_spans_are_rekeyed_and_marked_without_touching_content(trace):
    spans = fx.native_spans(trace, trace_id="t-new", id_salt="n", synthetic=True)
    assert {s.trace_id for s in spans} == {"t-new"}
    assert spans[0].input == trace.spans[0].input and spans[0].metadata["nexus.synthetic"] is True
    assert {s.parent_span_id for s in spans} - {None} <= {s.span_id for s in spans}
    assert trace.spans[0].metadata.get("nexus.synthetic") is None  # the source is not mutated


def test_end_before_start_never_occurs_for_zero_or_fractional_durations():
    short = CompleteTrace(trace_id="t", agent_name="a", started_at=T0, spans=[make("z", SpanType.LLM_CALL, duration_ms=0.0)])
    assert mapped(short)[0].duration_ms == 0.0
    later = make("y", SpanType.LLM_CALL, duration_ms=0.0252, client_timestamp=T0 + timedelta(microseconds=5))
    assert mapped(CompleteTrace(trace_id="t", agent_name="a", started_at=T0, spans=[later]))[0].duration_ms == 0.0252


def test_only_whitelisted_dev_traces_can_be_loaded():
    with pytest.raises(ValueError, match="DEV whitelist"):
        fx.load_dev_traces(["nb-not-a-dev-trace"])


def test_unsupported_span_types_are_rejected_not_guessed(trace):
    odd = trace.model_copy(update={"spans": [make("c", SpanType.CUSTOM)]})
    with pytest.raises(ValueError, match="does not cover"):
        fx.trace_to_otlp(odd)


def test_plan_reaches_detector_metadata_only_through_the_documented_attributes(trace):
    planner = next(s for s in mapped(trace) if s.span_type == SpanType.AGENT_STEP)
    assert planner.metadata["role"] == "planner" and planner.metadata["plan_steps"] == ["a", "b"]
    unaware = next(s for s in mapped(trace, plan_attributes=False) if s.span_type == SpanType.AGENT_STEP)
    assert "role" not in unaware.metadata and "plan_steps" not in unaware.metadata
    assert unaware.metadata["otel.attributes"]["app.plan_steps"] == ["a", "b"]
