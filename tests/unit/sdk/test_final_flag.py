"""Trace completion signal: the root span of a trace carries metadata final=True."""

from __future__ import annotations

import nexus_llmops as nexus
from services.common.trace_buffer import TraceBuffer


def test_trace_decorator_marks_only_the_root_final(nexus_client):
    _, exporter = nexus_client

    @nexus.trace(span_type="tool_call")
    def child(x):
        return x

    @nexus.trace(span_type="agent_step")
    def root(x):
        child(x)
        child(x + 1)
        return x

    root(1)
    *children, top = exporter.spans  # children end first, the root last
    assert top.parent_span_id is None
    assert top.metadata["final"] is True
    assert len(children) == 2
    assert all(c.parent_span_id == top.span_id for c in children)
    assert all("final" not in c.metadata for c in children)


def test_span_context_manager_marks_only_the_root_final(nexus_client):
    _, exporter = nexus_client
    with nexus.span("agent_step", input="task"):
        with nexus.span("tool_call", input="q") as inner:
            inner.set_output("r")
    inner_span, root_span = exporter.spans
    assert root_span.metadata["final"] is True
    assert "final" not in inner_span.metadata


def test_start_end_span_marks_only_the_root_final(nexus_client):
    _, exporter = nexus_client
    # Explicit spans do not push a context, so each one is a root of its own trace.
    first = nexus.start_span("agent_step")
    nexus.end_span(first, output="done")
    assert exporter.spans[0].parent_span_id is None
    assert exporter.spans[0].metadata["final"] is True


def test_explicit_final_value_is_respected(nexus_client):
    _, exporter = nexus_client
    with nexus.span("agent_step", input="x", final=False):
        pass
    assert exporter.spans[0].metadata["final"] is False


def test_failing_root_is_still_final(nexus_client):
    _, exporter = nexus_client

    @nexus.trace(span_type="agent_step")
    def boom():
        raise RuntimeError("x")

    try:
        boom()
    except RuntimeError:
        pass
    assert exporter.spans[0].error_type == "RuntimeError"
    assert exporter.spans[0].metadata["final"] is True


def test_sdk_trace_completes_in_the_buffer_without_the_idle_timeout(nexus_client):
    _, exporter = nexus_client

    @nexus.trace(span_type="tool_call")
    def child():
        return "ok"

    @nexus.trace(span_type="agent_step")
    def root():
        child()
        child()

    root()
    buf = TraceBuffer(timeout_seconds=30, clock=lambda: 0.0)
    done = [t for s in exporter.spans if (t := buf.add(s)) is not None]
    assert len(done) == 1 and done[0].span_count == 3
    assert buf.pending_traces == 0  # nothing waits for the 30 s sweep


def test_child_arriving_after_its_root_is_dropped_and_counted(nexus_client):
    """Documented edge case: out-of-order delivery (e.g. a retried batch) loses the late child."""
    _, exporter = nexus_client

    @nexus.trace(span_type="tool_call")
    def child():
        return "ok"

    @nexus.trace(span_type="agent_step")
    def root():
        child()

    root()
    child_span, root_span = exporter.spans
    buf = TraceBuffer(timeout_seconds=30, clock=lambda: 0.0)
    done = buf.add(root_span)  # the root arrives first
    assert done is not None and done.span_count == 1
    assert buf.add(child_span) is None
    assert buf.late_spans_after_completion == 1
    assert buf.duplicate_spans_dropped == 1
