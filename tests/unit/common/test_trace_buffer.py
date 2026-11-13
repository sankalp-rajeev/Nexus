"""TraceBuffer duplicate protection: SDK retries can deliver a batch the collector already took."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from nexus_agent.models import Span, SpanType, TraceStatus
from services.assembler.consumer import AssemblerService
from services.common.trace_buffer import (
    COMPLETED_MEMORY_SECONDS, COMPLETED_MEMORY_SIZE, TraceBuffer)

T0 = datetime(2026, 11, 12, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def span(trace_id, i, final=False, tool="search", text="same query"):
    return Span(span_id=f"{trace_id}-s{i}", trace_id=trace_id, agent_name="agent",
                span_type=SpanType.TOOL_CALL, input=text, output=f"out{i}", duration_ms=1.0 + i,
                client_timestamp=T0 + timedelta(seconds=i), sdk_version="test",
                metadata={"tool_name": tool, **({"final": True} if final else {})})


def batch(trace_id="t1"):
    """Two legitimate identical tool calls (below the 3x loop threshold) then the final span."""
    return [span(trace_id, 0), span(trace_id, 1)], [span(trace_id, 2, final=True, tool="finish", text="done")]


def deliver(buffer, spans):
    return [t for t in (buffer.add(s) for s in spans) if t is not None]


# (a) the same batch delivered twice -> identical CompleteTrace
def test_batch_delivered_twice_before_completion_yields_identical_trace():
    first, final = batch()
    once = TraceBuffer()
    expected = deliver(once, first + final)
    twice = TraceBuffer()
    got = deliver(twice, first) + deliver(twice, first) + deliver(twice, final)  # retried batch
    assert len(expected) == len(got) == 1
    assert got[0] == expected[0]
    assert got[0].span_count == 3 and [s.span_id for s in got[0].spans] == ["t1-s0", "t1-s1", "t1-s2"]
    assert twice.duplicate_spans_dropped == 2 and twice.duplicate_spans_in_trace == 2
    assert once.duplicate_spans_dropped == 0


def test_duplicate_is_not_counted_toward_the_span_cap_or_the_idle_timeout():
    clock = Clock()
    buf = TraceBuffer(timeout_seconds=30, max_spans=3, clock=clock)
    a = span("t", 0)
    assert buf.add(a) is None
    for _ in range(50):  # a replay storm must not trip the 3-span cap
        assert buf.add(a) is None
    assert buf.pending_traces == 1 and len(buf._buf["t"].spans) == 1
    clock.now += 29
    buf.add(a)  # replay is not activity: it must not extend the idle timeout
    clock.now += 2
    swept = buf.sweep()
    assert [t.trace_id for t in swept] == ["t"] and swept[0].span_count == 1


# (b) a duplicate after completion is dropped; no new trace is emitted
def test_duplicates_after_completion_are_dropped_and_emit_no_trace():
    first, final = batch()
    buf = TraceBuffer()
    assert len(deliver(buf, first + final)) == 1
    assert buf.pending_traces == 0
    assert deliver(buf, first + final) == []  # whole batch redelivered late
    assert buf.add(final[0]) is None  # even the final span alone must not complete a new trace
    assert buf.pending_traces == 0  # and must not start a partial one
    assert buf.late_spans_after_completion == 4 and buf.duplicate_spans_dropped == 4
    assert buf.duplicate_spans_in_trace == 0


def test_timeout_and_cap_completions_are_also_remembered():
    clock = Clock()
    buf = TraceBuffer(timeout_seconds=30, max_spans=2, clock=clock)
    assert buf.add(span("capped", 0)) is None
    assert buf.add(span("capped", 1)) is not None  # cap
    buf.add(span("idle", 0))
    clock.now += 31
    assert [t.trace_id for t in buf.sweep()] == ["idle"]
    assert buf.add(span("capped", 0)) is None and buf.add(span("idle", 0)) is None
    assert buf.pending_traces == 0 and buf.duplicate_spans_dropped == 2


def test_memory_expires_so_a_reused_trace_id_eventually_starts_a_new_trace():
    clock = Clock()
    buf = TraceBuffer(completed_memory_seconds=60, clock=clock)
    deliver(buf, [span("t", 0, final=True)])
    assert buf.add(span("t", 1)) is None  # inside the window: dropped
    clock.now += 61
    assert buf.add(span("t", 1, final=True)) is not None  # window over: normal behaviour again


def test_memory_can_be_disabled():
    buf = TraceBuffer(completed_memory_size=0)
    deliver(buf, [span("t", 0, final=True)])
    assert buf.add(span("t", 1, final=True)) is not None
    with pytest.raises(ValueError):
        TraceBuffer(completed_memory_size=-1)


# (c) memory stays bounded
def test_completed_memory_is_size_limited():
    buf = TraceBuffer(completed_memory_size=100)
    for i in range(5000):
        buf.add(span(f"t{i}", 0, final=True))
        assert buf.completed_remembered <= 100
    assert buf.completed_remembered == 100 and buf.pending_traces == 0
    assert buf.add(span("t4999", 1)) is None  # newest are the ones kept
    assert "t0" not in buf._completed  # oldest were evicted ...
    assert buf.add(span("t0", 1)) is None and buf.pending_traces == 1  # ... so this starts a new partial


def test_default_bounds_hold_under_a_long_stream_of_traces():
    buf = TraceBuffer()
    for i in range(COMPLETED_MEMORY_SIZE + 1500):
        buf.add(span(f"t{i}", 0, final=True))
    assert buf.completed_remembered == COMPLETED_MEMORY_SIZE
    assert (COMPLETED_MEMORY_SIZE, COMPLETED_MEMORY_SECONDS) == (10_000, 300)


def test_completed_memory_is_time_limited():
    clock = Clock()
    buf = TraceBuffer(completed_memory_seconds=60, clock=clock)
    for i in range(500):
        buf.add(span(f"t{i}", 0, final=True))
        clock.now += 0.1
    assert buf.completed_remembered == 500
    clock.now += 120
    buf.sweep()  # expiry also runs on the idle sweep, not only on add()
    assert buf.completed_remembered == 0


def test_open_trace_state_is_bounded_and_released_on_completion():
    buf = TraceBuffer(max_spans=500)
    a = span("t", 0)
    for _ in range(20_000):
        buf.add(a)
    entry = buf._buf["t"]
    assert len(entry.spans) == 1 and len(entry.span_ids) == 1
    for i in range(1, 499):
        buf.add(span("t", i))
    assert len(buf._buf["t"].span_ids) <= 500
    assert buf.add(span("t", 499)) is not None  # hits the 500-span cap
    assert buf.pending_traces == 0 and "t" not in buf._buf  # ids/spans released


# Assembler: a late duplicate must not rewrite the stored trace with a one-span stub
def test_assembler_writes_once_and_ignores_redelivered_batch():
    db = MagicMock()
    service = AssemblerService(db=db)
    first, final = batch()
    payloads = [s.model_dump_json().encode() for s in first + final]
    for _ in range(2):  # the collector accepted the batch twice (retry)
        for value in payloads:
            service._handle(value)
    assert db.write_trace.call_count == 1
    written = db.write_trace.call_args.args[0]
    assert written.span_count == 3 and written.status == TraceStatus.COMPLETED
    assert service.buffer.duplicate_spans_dropped == 3
