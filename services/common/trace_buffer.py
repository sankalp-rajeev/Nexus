"""Shared trace assembly buffer (Section 8.4).

Groups streaming spans by trace_id and emits a CompleteTrace when a trace is
"done": an explicit completion signal (a span with metadata.final == True),
a hard span cap, or an inactivity timeout. Used by both the assembler and the
classifier, which each consume nexus.spans.raw independently.

Duplicate protection (the SDK retries a failed batch once, so a batch the
collector already accepted can arrive twice):
  * spans are de-duplicated by ``span_id`` within a trace;
  * a bounded memory (size- and time-limited) of recently completed trace_ids
    drops late spans for those traces instead of starting a new partial trace.
Both are counted in ``duplicate_spans_dropped``. Spans that arrive for a trace
completed within the memory window are dropped even if their span_id is new
(e.g. a genuinely late span after an inactivity timeout); that trade is
deliberate and counted too (``late_spans_after_completion``).
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field

from nexus_agent.models import CompleteTrace, Span, TraceStatus

logger = logging.getLogger("nexus.common.trace_buffer")

TIMEOUT_SECONDS = 30
MAX_SPANS_PER_TRACE = 500
# Recently completed trace_ids are remembered at most this many, for at most this
# long. 300 s is 10x the inactivity timeout and far beyond the SDK retry (100-300 ms
# backoff) plus normal consumer lag; 10,000 ids is roughly 1-2 MB.
COMPLETED_MEMORY_SIZE = 10_000
COMPLETED_MEMORY_SECONDS = 300


@dataclass
class _Buffered:
    spans: list[Span] = field(default_factory=list)
    span_ids: set[str] = field(default_factory=set)
    last_update: float = 0.0


class TraceBuffer:
    def __init__(self, timeout_seconds: int = TIMEOUT_SECONDS,
                 max_spans: int = MAX_SPANS_PER_TRACE,
                 completed_memory_size: int = COMPLETED_MEMORY_SIZE,
                 completed_memory_seconds: float = COMPLETED_MEMORY_SECONDS,
                 clock: Callable[[], float] = time.monotonic) -> None:
        if completed_memory_size < 0 or completed_memory_seconds < 0:
            raise ValueError("completed memory size/seconds must be >= 0 (0 disables it)")
        self.timeout_seconds = timeout_seconds
        self.max_spans = max_spans
        self.completed_memory_size = completed_memory_size
        self.completed_memory_seconds = completed_memory_seconds
        self._clock = clock
        self._buf: dict[str, _Buffered] = {}
        # trace_id -> completion time, oldest first (so expiry only looks at the front)
        self._completed: OrderedDict[str, float] = OrderedDict()
        self.duplicate_spans_dropped = 0  # total of the two kinds below
        self.duplicate_spans_in_trace = 0  # same span_id seen again while the trace is open
        self.late_spans_after_completion = 0  # span for a recently completed trace

    def add(self, span: Span) -> CompleteTrace | None:
        """Add a span; return a CompleteTrace if this span completes the trace.

        A span whose span_id is already in the open trace, or that belongs to a
        recently completed trace, is dropped (counted) and returns None.
        """
        now = self._clock()
        self._expire_completed(now)
        if span.trace_id in self._completed:
            self.late_spans_after_completion += 1
            self._note_duplicate(span, "after trace completion")
            return None
        entry = self._buf.get(span.trace_id)
        if entry is None:
            entry = self._buf[span.trace_id] = _Buffered()
        elif span.span_id in entry.span_ids:
            # Not counted as activity: a replayed span must not extend the idle timeout.
            self.duplicate_spans_in_trace += 1
            self._note_duplicate(span, "within open trace")
            return None
        entry.spans.append(span)
        entry.span_ids.add(span.span_id)
        entry.last_update = now

        is_final = bool((span.metadata or {}).get("final"))
        if is_final or len(entry.spans) >= self.max_spans:
            return self._finalize(span.trace_id, TraceStatus.COMPLETED)
        return None

    def _note_duplicate(self, span: Span, where: str) -> None:
        self.duplicate_spans_dropped += 1
        n = self.duplicate_spans_dropped
        if n == 1 or n % 100 == 0:  # throttled: a replayed batch can be large
            logger.warning("trace buffer: dropped duplicate span %s of trace %s (%s); "
                           "duplicate_spans_dropped=%d", span.span_id, span.trace_id, where, n)

    def sweep(self) -> list[CompleteTrace]:
        """Finalize traces idle longer than the timeout."""
        now = self._clock()
        self._expire_completed(now)
        stale = [
            tid for tid, e in self._buf.items()
            if now - e.last_update >= self.timeout_seconds
        ]
        return [self._finalize(tid, TraceStatus.COMPLETED) for tid in stale]

    def _expire_completed(self, now: float) -> None:
        horizon = now - self.completed_memory_seconds
        while self._completed:
            oldest_id, completed_at = next(iter(self._completed.items()))
            if completed_at > horizon:
                break
            del self._completed[oldest_id]

    def _remember_completed(self, trace_id: str) -> None:
        if self.completed_memory_size == 0 or self.completed_memory_seconds == 0:
            return
        self._completed[trace_id] = self._clock()
        self._completed.move_to_end(trace_id)
        while len(self._completed) > self.completed_memory_size:
            self._completed.popitem(last=False)

    def _finalize(self, trace_id: str, status: TraceStatus) -> CompleteTrace:
        entry = self._buf.pop(trace_id)
        self._remember_completed(trace_id)
        spans = sorted(entry.spans, key=lambda s: s.client_timestamp)
        any_error = any(s.error_type for s in spans)
        return CompleteTrace(
            trace_id=trace_id,
            agent_name=spans[0].agent_name,
            environment=spans[0].environment,
            root_input=spans[0].input,
            final_output=spans[-1].output,
            span_count=len(spans),
            total_duration_ms=sum(s.duration_ms for s in spans),
            started_at=spans[0].client_timestamp,
            completed_at=spans[-1].client_timestamp,
            status=TraceStatus.FAILED if any_error else status,
            spans=spans,
        )

    @property
    def pending_traces(self) -> int:
        return len(self._buf)

    @property
    def completed_remembered(self) -> int:
        return len(self._completed)

    def stats(self) -> dict[str, int]:
        return {"duplicate_spans_dropped": self.duplicate_spans_dropped,
                "duplicate_spans_in_trace": self.duplicate_spans_in_trace,
                "late_spans_after_completion": self.late_spans_after_completion,
                "pending_traces": self.pending_traces,
                "completed_remembered": self.completed_remembered}
