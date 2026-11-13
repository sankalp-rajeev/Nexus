"""NexusClient — span capture, background export, and trace context.

Design (Section 7.1):
  * Zero-config   — ``nexus.init(agent_name=...)`` is enough.
  * Non-blocking  — capture enqueues to a thread-safe queue; a background
                    worker thread does the actual export.
  * Fail-silent   — any internal error is caught and logged; never raised into
                    user code. (User-function exceptions still propagate, but
                    are recorded on the span first.)

Hardening (Phase 6):
  * Bounded memory — the queue is capped by span COUNT (``max_queue_size``) and by
                    an ESTIMATED byte size (``max_queue_bytes``). Over either
                    cap the newest span is dropped and counted. The byte size
                    is an estimate (see ``estimate_span_bytes``), not exact RSS.
  * One retry     — a failed batch is retried once, on the background thread
                    only, after a jittered 100-300 ms backoff; then dropped and
                    counted. No retry once shutdown has begun, none in
                    ``flush()`` and none in synchronous mode, so the retry adds
                    no waiting to the caller thread or to flush().
  * Counters      — invariant at quiescence (after ``shutdown()`` / idle):
                    ``produced == exported + dropped_total + queued``.
"""

from __future__ import annotations

import contextvars
import logging
import queue
import random
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


# Fixed per-span constant for the byte estimate. A throwaway tracemalloc
# measurement of a pydantic Span with empty text fields was ~1.6-1.7 KiB (object,
# __dict__, datetime, ids, queue tuple), so 2 KiB covers the non-text overhead.
SPAN_OVERHEAD_BYTES = 2048
_NODE_BUDGET = 256  # max metadata nodes visited per span, so sizing stays O(1)-ish
_NODE_COST = 16  # flat charge for non-string leaves and for unwalked remainder


def estimate_span_bytes(span: Span) -> int:
    """Cheap ESTIMATE of the memory a queued span holds. Never raises.

    ``SPAN_OVERHEAD_BYTES`` + the lengths (in characters, not encoded bytes) of
    the span's string fields and of the strings/bytes found in ``metadata``
    (walked up to ``_NODE_BUDGET`` nodes; other leaves cost ``_NODE_COST``).
    No JSON serialisation, so it is safe on the caller thread. It under-counts
    non-ASCII text (up to 4x per character) and the tail of huge metadata.
    """
    try:
        total = SPAN_OVERHEAD_BYTES
        for text in (span.span_id, span.trace_id, span.parent_span_id, span.agent_name,
                     span.input, span.output, span.error_type, span.error_message,
                     span.environment, span.sdk_version):
            if text:
                total += len(text)
        stack: list[Any] = [span.metadata]
        budget = _NODE_BUDGET
        while stack and budget > 0:
            node = stack.pop()
            budget -= 1
            if isinstance(node, (str, bytes, bytearray)):
                total += len(node)
            elif isinstance(node, dict):
                stack.extend(node.keys())
                stack.extend(node.values())
            elif isinstance(node, (list, tuple, set, frozenset)):
                stack.extend(node)
            else:
                total += _NODE_COST
        total += _NODE_COST * len(stack)  # nodes not visited once the budget ran out
        return total
    except Exception:  # noqa: BLE001 — sizing must never break capture
        return SPAN_OVERHEAD_BYTES


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
        # Queue items are (span, estimated_bytes) so the byte cap can be released
        # exactly, without re-estimating on the worker.
        self._queue: queue.Queue[tuple[Span, int]] = queue.Queue(maxsize=config.max_queue_size)
        self._stop = threading.Event()
        self._stats_lock = threading.Lock()
        self._produced = 0  # spans handed to record()
        self._exported = 0
        self._dropped_queue_full = 0  # refused at enqueue: count cap
        self._dropped_bytes_cap = 0  # refused at enqueue: byte cap
        self._export_failed = 0  # spans lost after export (incl. failed retry)
        self._export_retried = 0  # batch retry attempts made
        self._held_bytes = 0  # estimated bytes of queued + in-flight spans
        self._drop_log_count = 0
        # Private RNG: jitter must not consume the application's global `random` stream.
        self._rng = random.Random()
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
        reserved = 0
        try:
            if not self.config.async_export:
                with self._stats_lock:
                    self._produced += 1
                self._export_batch([span])  # synchronous mode: no queue, no retry
                return
            size = estimate_span_bytes(span)
            reason = None
            with self._stats_lock:
                self._produced += 1
                if self._held_bytes + size > self.config.max_queue_bytes:
                    self._dropped_bytes_cap += 1
                    reason = "byte cap"
                else:
                    self._held_bytes += size
                    reserved = size
            if reason is None:
                try:
                    self._queue.put_nowait((span, size))
                    reserved = 0  # ownership passed to the queue
                except queue.Full:
                    with self._stats_lock:
                        self._held_bytes -= size
                        self._dropped_queue_full += 1
                    reserved = 0
                    reason = "count cap"
            if reason is not None:
                self._log_drop(span.span_id, reason)
        except Exception as exc:  # noqa: BLE001 — fail-silent
            # Counted (and any byte reservation released) so the invariant still holds.
            with self._stats_lock:
                self._export_failed += 1
                self._held_bytes -= reserved
            logger.warning("nexus: failed to record span (%s)", exc.__class__.__name__)

    def _log_drop(self, span_id: str, reason: str) -> None:
        # Throttled: an outage can drop thousands of spans; log the 1st, then every 1000th.
        with self._stats_lock:
            n = self._drop_log_count
            self._drop_log_count += 1
        if n % 1000 == 0:
            suffix = "" if n == 0 else f" ({n} drops logged so far)"
            logger.warning("nexus: span queue full (%s); dropped span %s%s", reason, span_id, suffix)

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
            batch, size = self._drain(block=True, timeout=interval)
            if batch:
                self._export_batch(batch, reserved_bytes=size, allow_retry=True)
        # Final drain on shutdown (the stop flag is set, so no retries here).
        batch, size = self._drain(block=False)
        if batch:
            self._export_batch(batch, reserved_bytes=size, allow_retry=True)

    def _drain(self, *, block: bool, timeout: float | None = None) -> tuple[list[Span], int]:
        spans: list[Span] = []
        size = 0
        try:
            if block:
                span, nbytes = self._queue.get(timeout=timeout)
                spans.append(span)
                size += nbytes
        except queue.Empty:
            return spans, size
        while len(spans) < self.config.max_batch_size:
            try:
                span, nbytes = self._queue.get_nowait()
            except queue.Empty:
                break
            spans.append(span)
            size += nbytes
        return spans, size

    def _attempt_export(self, batch: SpanBatch | None, spans: list[Span]) -> tuple[bool, SpanBatch | None]:
        """One export attempt. Never raises. Returns (ok, batch) so a retry reuses the batch."""
        try:
            if batch is None:
                batch = SpanBatch(spans=spans)
            return bool(self._exporter.export(batch)), batch
        except Exception as exc:  # noqa: BLE001 — exporters are fail-silent, belt-and-suspenders
            logger.warning("nexus: export raised unexpectedly (%s)", exc.__class__.__name__)
            return False, batch

    def _export_batch(self, spans: list[Span], reserved_bytes: int = 0, allow_retry: bool = False) -> None:
        """Export a batch; on failure retry once (background thread only), else drop and count.

        ``allow_retry`` is True only from the worker loop. The backoff wait uses
        the stop event, so ``shutdown()`` interrupts it and the retry is skipped:
        the retry never delays shutdown by more than one in-flight attempt.
        """
        if not spans:
            return
        try:
            ok, batch = self._attempt_export(None, spans)
            if not ok and allow_retry and not self._stop.is_set():
                lo = self.config.export_retry_backoff_min_ms / 1000.0
                hi = self.config.export_retry_backoff_max_ms / 1000.0
                if not self._stop.wait(self._rng.uniform(lo, hi)):  # True means shutdown began
                    with self._stats_lock:
                        self._export_retried += 1
                    ok, _ = self._attempt_export(batch, spans)
            with self._stats_lock:
                if ok:
                    self._exported += len(spans)
                else:
                    self._export_failed += len(spans)
        finally:
            if reserved_bytes:
                with self._stats_lock:
                    self._held_bytes -= reserved_bytes

    # ── Flush / shutdown ────────────────────────────────────────────
    def flush(self) -> None:
        """Synchronously export everything currently queued. Fail-silent.

        Runs on the caller thread and never retries, so retries add no time here.
        """
        try:
            while True:
                batch, size = self._drain(block=False)
                if not batch:
                    break
                self._export_batch(batch, reserved_bytes=size)
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
        """Counters. At quiescence ``produced == exported + dropped_total + queued``.

        * ``dropped``: compatibility counter = spans refused at enqueue
          (``dropped_queue_full + dropped_bytes_cap``).
        * ``dropped_total``: every span lost (refused at enqueue or failed export).
        * ``export_retried``: batch retry attempts (not spans).
        * ``queued_bytes_estimate``: estimated bytes of queued + in-flight spans.
        """
        with self._stats_lock:
            produced, exported = self._produced, self._exported
            full, cap = self._dropped_queue_full, self._dropped_bytes_cap
            failed, retried, held = self._export_failed, self._export_retried, self._held_bytes
        return {
            "produced": produced,
            "queued": self._queue.qsize(),
            "exported": exported,
            "dropped": full + cap,
            "dropped_queue_full": full,
            "dropped_bytes_cap": cap,
            "export_retried": retried,
            "export_failed": failed,
            "dropped_total": full + cap + failed,
            "queued_bytes_estimate": held,
            "pending": len(self._pending),
        }
