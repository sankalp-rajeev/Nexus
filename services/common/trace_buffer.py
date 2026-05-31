"""Shared trace assembly buffer (Section 8.4).

Groups streaming spans by trace_id and emits a CompleteTrace when a trace is
"done": an explicit completion signal (a span with metadata.final == True),
a hard span cap, or an inactivity timeout. Used by both the assembler and the
classifier, which each consume nexus.spans.raw independently.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from nexus_agent.models import CompleteTrace, Span, TraceStatus

TIMEOUT_SECONDS = 30
MAX_SPANS_PER_TRACE = 500


@dataclass
class _Buffered:
    spans: list[Span] = field(default_factory=list)
    last_update: float = field(default_factory=time.monotonic)


class TraceBuffer:
    def __init__(self, timeout_seconds: int = TIMEOUT_SECONDS,
                 max_spans: int = MAX_SPANS_PER_TRACE) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_spans = max_spans
        self._buf: dict[str, _Buffered] = {}

    def add(self, span: Span) -> CompleteTrace | None:
        """Add a span; return a CompleteTrace if this span completes the trace."""
        entry = self._buf.setdefault(span.trace_id, _Buffered())
        entry.spans.append(span)
        entry.last_update = time.monotonic()

        is_final = bool((span.metadata or {}).get("final"))
        if is_final or len(entry.spans) >= self.max_spans:
            return self._finalize(span.trace_id, TraceStatus.COMPLETED)
        return None

    def sweep(self) -> list[CompleteTrace]:
        """Finalize traces idle longer than the timeout."""
        now = time.monotonic()
        stale = [
            tid for tid, e in self._buf.items()
            if now - e.last_update >= self.timeout_seconds
        ]
        return [self._finalize(tid, TraceStatus.COMPLETED) for tid in stale]

    def _finalize(self, trace_id: str, status: TraceStatus) -> CompleteTrace:
        entry = self._buf.pop(trace_id)
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
