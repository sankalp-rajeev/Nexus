"""Unit tests: @trace decorator, span() context manager, fail-silent behavior."""

from __future__ import annotations

import pytest

import nexus_agent as nexus
from nexus_agent.models import SpanType


def test_trace_returns_result(nexus_client):
    _, exporter = nexus_client

    @nexus.trace(span_type="llm_call")
    def f(x):
        return x * 2

    assert f(21) == 42
    assert len(exporter.spans) == 1


def test_trace_captures_input_and_output(nexus_client):
    _, exporter = nexus_client

    @nexus.trace(span_type="llm_call")
    def greet(name):
        return f"hi {name}"

    greet("world")
    span = exporter.spans[0]
    assert "world" in span.input
    assert span.output == "hi world"


def test_trace_passes_metadata_and_span_type(nexus_client):
    _, exporter = nexus_client

    @nexus.trace(span_type="llm_call", model="gemini-2.0-flash")
    def call(p):
        return p

    call("x")
    span = exporter.spans[0]
    assert span.span_type == SpanType.LLM_CALL
    assert span.metadata["model"] == "gemini-2.0-flash"


def test_trace_agent_name_override(nexus_client):
    _, exporter = nexus_client

    @nexus.trace(span_type="agent_step", agent_name="planner")
    def step(t):
        return t

    step("task")
    assert exporter.spans[0].agent_name == "planner"


def test_trace_records_exception_and_reraises(nexus_client):
    _, exporter = nexus_client

    @nexus.trace(span_type="tool_call")
    def boom():
        raise ValueError("bad args")

    with pytest.raises(ValueError):
        boom()
    span = exporter.spans[0]
    assert span.error_type == "ValueError"
    assert "bad args" in span.error_message
    assert span.output is None


def test_nested_trace_shares_trace_and_sets_parent(nexus_client):
    _, exporter = nexus_client

    @nexus.trace(span_type="tool_call")
    def child():
        return "c"

    @nexus.trace(span_type="agent_step")
    def parent():
        return child()

    parent()
    by_type = {s.span_type: s for s in exporter.spans}
    child_span = by_type[SpanType.TOOL_CALL]
    parent_span = by_type[SpanType.AGENT_STEP]
    assert child_span.trace_id == parent_span.trace_id
    assert child_span.parent_span_id == parent_span.span_id
    assert parent_span.parent_span_id is None


def test_span_context_manager(nexus_client):
    _, exporter = nexus_client

    with nexus.span(span_type="memory_read", key="user_context") as s:
        s.set_output({"cache_hit": True})
        s.set_metadata({"latency": 5})

    span = exporter.spans[0]
    assert span.span_type == SpanType.MEMORY_READ
    assert "cache_hit" in span.output
    assert span.metadata["key"] == "user_context"
    assert span.metadata["latency"] == 5


def test_span_context_manager_captures_exception(nexus_client):
    _, exporter = nexus_client

    with pytest.raises(RuntimeError):
        with nexus.span(span_type="custom"):
            raise RuntimeError("oops")

    assert exporter.spans[0].error_type == "RuntimeError"


def test_explicit_start_end_span_public_api(nexus_client):
    _, exporter = nexus_client
    sid = nexus.start_span(SpanType.AGENT_HANDOFF, from_agent="planner", to_agent="executor")
    nexus.end_span(sid, output="handed off", metadata={"tokens_used": 312})
    span = exporter.spans[0]
    assert span.metadata["from_agent"] == "planner"
    assert span.metadata["tokens_used"] == 312


def test_passthrough_when_not_initialized():
    # No nexus_client fixture → global client is None (autouse cleanup ensures this).
    assert nexus.get_client() is None

    @nexus.trace(span_type="llm_call")
    def f(x):
        return x + 1

    assert f(1) == 2  # returns result, records nothing, no error


def test_fail_silent_when_collector_unreachable():
    # Real HTTP exporter pointed at a closed port; must not raise into user code.
    nexus.init(agent_name="t", collector_url="http://127.0.0.1:1", async_export=False)

    @nexus.trace(span_type="llm_call")
    def f():
        return "ok"

    assert f() == "ok"
    nexus.flush()  # also fail-silent


@pytest.mark.asyncio
async def test_trace_async_function(nexus_client):
    _, exporter = nexus_client

    @nexus.trace(span_type="llm_call")
    async def acall(x):
        return x * 3

    result = await acall(4)
    assert result == 12
    assert exporter.spans[0].output == "12"
