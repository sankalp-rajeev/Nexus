"""NexusClient — span capture, background export, and trace context.

Design (Section 7.1):
  * Zero-config   — ``nexus.init(agent_name=...)`` is enough.
  * Non-blocking  — capture enqueues to a thread-safe queue; a background
                    worker thread does the actual export.
  * Fail-silent   — any internal error is caught and logged; never raised into
                    user code. (User-function exceptions still propagate, but
                    are recorded on the span first.)
"""

from __future__ import annotations

import contextvars
import logging
import queue
import threading
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from nexus_agent.config import NexusConfig
from nexus_agent.exporters.http import HttpExporter
from nexus_agent.exporters.stdout import StdoutExporter
from nexus_agent.models import Span, SpanBatch, SpanType

logger = logging.getLogger("nexus_agent.client")

# Trace context propagated across (possibly nested / async) calls.
_current_trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "nexus_trace_id", default=None
)
_current_span_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "nexus_span_id", default=None
)


def new_trace_id() -> str:
    return f"trace_{uuid4().hex[:16]}"


def new_span_id() -> str:
    return f"span_{uuid4().hex[:12]}"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_text(value: Any, limit: int) -> str:
    """Best-effort, never-raising serialization to a length-capped string."""
    if value is None:
        return ""
    try:
        text = value if isinstance(value, str) else repr(value)
    except Exception:  # noqa: BLE001
        text = "<unserializable>"
    return text[:limit]


class NexusClient:
    def __init__(self, config: NexusConfig) -> None:
        from nexus_agent import __version__

        self.config = config
        self.sdk_version = __version__
        self._queue: queue.Queue[Span] = queue.Queue(maxsize=config.max_queue_size)
        self._stop = threading.Event()
        self._dropped = 0  # spans dropped due to a full queue
        self._exported = 0
        self._pending: dict[str, dict[str, Any]] = {}  # explicit start/end spans
        self._pending_lock = threading.Lock()

        if config.debug:
            self._exporter: Any = StdoutExporter()
        else:
            self._exporter = HttpExporter(config.collector_url, config.export_timeout_ms)

        self._worker: threading.Thread | None = None
        if config.async_export:
            self._worker = threading.Thread(
                target=self._run_export_loop, name="nexus-exporter", daemon=True
            )
            self._worker.start()

    # ── Trace context ───────────────────────────────────────────────
    @staticmethod
    def current_trace_id() -> str | None:
        return _current_trace_id.get()

    @staticmethod
    def current_span_id() -> str | None:
        return _current_span_id.get()

    # ── Span construction ───────────────────────────────────────────
    def build_span(
        self,
        *,
        span_type: SpanType | str,
        span_id: str,
        trace_id: str,
        parent_span_id: str | None,
        input_text: str,
        output_text: str | None,
        duration_ms: float,
        error_type: str | None = None,
        error_message: str | None = None,
        agent_name: str | None = None,
        metadata: dict[str, Any] | None = None,
        client_timestamp: datetime | None = None,
    ) -> Span:
        return Span(
            span_id=span_id,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            agent_name=agent_name or self.config.agent_name,
            span_type=SpanType(span_type) if not isinstance(span_type, SpanType) else span_type,
            input=to_text(input_text, self.config.max_input_chars),
            output=(to_text(output_text, self.config.max_output_chars) if output_text is not None else None),
            duration_ms=duration_ms,
            error_type=error_type,
            error_message=(to_text(error_message, self.config.max_error_chars) if error_message else None),
            metadata=metadata or {},
            client_timestamp=client_timestamp or _utcnow(),
            environment=self.config.environment,
            sdk_version=self.sdk_version,
        )

    # ── Recording / enqueue (non-blocking, fail-silent) ─────────────
    def record(self, span: Span) -> None:
        try:
            if self.config.async_export:
                self._queue.put_nowait(span)
            else:
                self._export_batch([span])
        except queue.Full:
            self._dropped += 1
            logger.warning("nexus: span queue full; dropped span %s", span.span_id)
        except Exception as exc:  # noqa: BLE001 — fail-silent
            logger.warning("nexus: failed to record span (%s)", exc.__class__.__name__)

    # ── Explicit start_span / end_span ──────────────────────────────
    def start_span(
        self, span_type: SpanType | str, agent_name: str | None = None, **metadata: Any
    ) -> str:
        span_id = new_span_id()
        trace_id = _current_trace_id.get() or new_trace_id()
        parent = _current_span_id.get()
        with self._pending_lock:
            self._pending[span_id] = {
                "span_type": span_type,
                "trace_id": trace_id,
                "parent_span_id": parent,
                "agent_name": agent_name,
                "metadata": dict(metadata),
                "start": time.perf_counter(),
                "client_timestamp": _utcnow(),
            }
        return span_id

    def end_span(
        self,
        span_id: str,
        output: Any = None,
        metadata: dict[str, Any] | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        with self._pending_lock:
            info = self._pending.pop(span_id, None)
        if info is None:
            logger.warning("nexus: end_span called for unknown span_id %s", span_id)
            return
        duration_ms = (time.perf_counter() - info["start"]) * 1000.0
        md = info["metadata"]
        if metadata:
            md.update(metadata)
        span = self.build_span(
            span_type=info["span_type"],
            span_id=span_id,
            trace_id=info["trace_id"],
            parent_span_id=info["parent_span_id"],
            input_text="",
            output_text=output,
            duration_ms=duration_ms,
            error_type=error_type,
            error_message=error_message,
            agent_name=info["agent_name"],
            metadata=md,
            client_timestamp=info["client_timestamp"],
        )
        self.record(span)

    # ── Background export loop ──────────────────────────────────────
    def _run_export_loop(self) -> None:
        interval = self.config.flush_interval_ms / 1000.0
        while not self._stop.is_set():
            batch = self._drain(block=True, timeout=interval)
            if batch:
                self._export_batch(batch)
        # Final drain on shutdown.
        batch = self._drain(block=False)
        if batch:
            self._export_batch(batch)

    def _drain(self, *, block: bool, timeout: float | None = None) -> list[Span]:
        spans: list[Span] = []
        try:
            if block:
                spans.append(self._queue.get(timeout=timeout))
        except queue.Empty:
            return spans
        while len(spans) < self.config.max_batch_size:
            try:
                spans.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return spans

    def _export_batch(self, spans: list[Span]) -> None:
        if not spans:
            return
        try:
            ok = self._exporter.export(SpanBatch(spans=spans))
            if ok:
                self._exported += len(spans)
        except Exception as exc:  # noqa: BLE001 — exporters are fail-silent, belt-and-suspenders
            logger.warning("nexus: export raised unexpectedly (%s)", exc.__class__.__name__)

    # ── Flush / shutdown ────────────────────────────────────────────
    def flush(self) -> None:
        """Synchronously export everything currently queued. Fail-silent."""
        try:
            while True:
                batch = self._drain(block=False)
                if not batch:
                    break
                self._export_batch(batch)
        except Exception as exc:  # noqa: BLE001
            logger.warning("nexus: flush failed (%s)", exc.__class__.__name__)

    def shutdown(self) -> None:
        self._stop.set()
        if self._worker is not None:
            self._worker.join(timeout=2.0)
        self.flush()
        try:
            self._exporter.close()
        except Exception:  # noqa: BLE001
            pass

    # ── Introspection (for tests / health) ──────────────────────────
    @property
    def stats(self) -> dict[str, int]:
        return {
            "queued": self._queue.qsize(),
            "exported": self._exported,
            "dropped": self._dropped,
            "pending": len(self._pending),
        }
