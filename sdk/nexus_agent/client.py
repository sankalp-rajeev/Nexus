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
  * Shutdown      — ``shutdown(timeout=...)`` (default ``shutdown_timeout_ms``, 5 s)
                    stops draining at the deadline; whatever is still queued (or
                    in a stuck in-flight batch) is counted ``dropped_shutdown``.
                    ``flush()`` is unchanged and has no deadline.
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


class _Inflight:
    """The background worker's current batch, so shutdown can account for it if abandoned."""

    __slots__ = ("spans", "reserved", "abandoned")

    def __init__(self, spans: int, reserved: int) -> None:
        self.spans = spans
        self.reserved = reserved
        self.abandoned = False


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
        self._dropped_shutdown = 0  # spans discarded unexported when the shutdown deadline passed
        self._deadline: float | None = None  # monotonic shutdown deadline, set by shutdown()
        self._worker_inflight: _Inflight | None = None  # the worker's current batch
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
    def _past_deadline(self) -> bool:
        deadline = self._deadline
        return deadline is not None and time.monotonic() >= deadline

    def _run_export_loop(self) -> None:
        interval = self.config.flush_interval_ms / 1000.0
        while not self._stop.is_set():
            batch, size = self._drain(block=True, timeout=interval)
            if batch:
                self._export_batch(batch, reserved_bytes=size, allow_retry=True)
        # Final drain on shutdown (the stop flag is set, so no retries here). After the
        # shutdown deadline the worker stops draining; shutdown() counts the remainder.
        if not self._past_deadline():
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
        inflight = _Inflight(len(spans), reserved_bytes) if allow_retry else None
        if inflight is not None:
            self._worker_inflight = inflight
        ok = False  # an unexpected exception below counts the batch as failed, never lost
        try:
            ok, batch = self._attempt_export(None, spans)
            if not ok and allow_retry and not self._stop.is_set():
                lo = self.config.export_retry_backoff_min_ms / 1000.0
                hi = self.config.export_retry_backoff_max_ms / 1000.0
                if not self._stop.wait(self._rng.uniform(lo, hi)):  # True means shutdown began
                    with self._stats_lock:
                        self._export_retried += 1
                    ok, _ = self._attempt_export(batch, spans)
        finally:
            with self._stats_lock:
                if inflight is not None and inflight.abandoned:
                    pass  # shutdown already counted these spans as dropped_shutdown
                else:
                    if ok:
                        self._exported += len(spans)
                    else:
                        self._export_failed += len(spans)
                    self._held_bytes -= reserved_bytes
                if inflight is not None and self._worker_inflight is inflight:
                    self._worker_inflight = None

    # ── Flush / shutdown ────────────────────────────────────────────
    def flush(self) -> None:
        """Synchronously export everything currently queued. Fail-silent.

        Runs on the caller thread and never retries, so retries add no time here.
        Unchanged by the shutdown deadline: flush() has no deadline of its own.
        """
        try:
            while True:
                batch, size = self._drain(block=False)
                if not batch:
                    break
                self._export_batch(batch, reserved_bytes=size)
        except Exception as exc:  # noqa: BLE001
            logger.warning("nexus: flush failed (%s)", exc.__class__.__name__)

    def _drop_queued_for_shutdown(self) -> int:
        """Discard everything still queued, counting it as dropped_shutdown. Thread-safe."""
        dropped = 0
        while True:
            batch, size = self._drain(block=False)
            if not batch:
                break
            dropped += len(batch)
            with self._stats_lock:
                self._dropped_shutdown += len(batch)
                self._held_bytes -= size
        return dropped

    def shutdown(self, timeout: float | None = None) -> None:
        """Stop the exporter, draining for at most ``timeout`` seconds.

        ``timeout`` defaults to ``config.shutdown_timeout_ms``. Draining stops at
        the deadline: spans still queued are counted ``dropped_shutdown`` (part of
        ``dropped_total``) and discarded. Worst-case duration is the deadline plus
        one in-flight HTTP attempt (about the export timeout) and, if the worker is
        stuck in an attempt, a join grace of twice the export timeout. Never raises.
        """
        try:
            seconds = self.config.shutdown_timeout_ms / 1000.0 if timeout is None else max(0.0, float(timeout))
        except Exception:  # noqa: BLE001 — a bad argument must not break process exit
            seconds = self.config.shutdown_timeout_ms / 1000.0
        deadline = time.monotonic() + seconds
        self._deadline = deadline
        self._stop.set()
        try:
            if self._worker is not None:
                grace = 2.0 * self.config.export_timeout_ms / 1000.0
                self._worker.join(timeout=max(0.0, deadline - time.monotonic()) + grace)
                if self._worker.is_alive():
                    self._abandon_worker_batch()
            while not self._past_deadline():
                batch, size = self._drain(block=False)
                if not batch:
                    break
                self._export_batch(batch, reserved_bytes=size)
            self._drop_queued_for_shutdown()
        except Exception as exc:  # noqa: BLE001
            logger.warning("nexus: shutdown failed (%s)", exc.__class__.__name__)
        try:
            self._exporter.close()
        except Exception:  # noqa: BLE001
            pass

    def _abandon_worker_batch(self) -> None:
        """The worker is stuck in an export past the deadline: count its batch as dropped."""
        with self._stats_lock:
            inflight = self._worker_inflight
            if inflight is not None and not inflight.abandoned:
                inflight.abandoned = True
                self._dropped_shutdown += inflight.spans
                self._held_bytes -= inflight.reserved
        logger.warning("nexus: shutdown deadline passed with an export still in flight")

    # ── Introspection (for tests / health) ──────────────────────────
    @property
    def stats(self) -> dict[str, int]:
        """Counters. At quiescence ``produced == exported + dropped_total + queued``.

        * ``dropped``: compatibility counter = spans refused at enqueue
          (``dropped_queue_full + dropped_bytes_cap``).
        * ``dropped_shutdown``: spans discarded unexported at the shutdown deadline.
        * ``dropped_total``: every span lost (refused at enqueue, failed export, or
          discarded at the shutdown deadline).
        * ``export_retried``: batch retry attempts (not spans).
        * ``queued_bytes_estimate``: estimated bytes of queued + in-flight spans.
        """
        with self._stats_lock:
            produced, exported = self._produced, self._exported
            full, cap = self._dropped_queue_full, self._dropped_bytes_cap
            failed, retried, held = self._export_failed, self._export_retried, self._held_bytes
            shut = self._dropped_shutdown
        return {
            "produced": produced,
            "queued": self._queue.qsize(),
            "exported": exported,
            "dropped": full + cap,
            "dropped_queue_full": full,
            "dropped_bytes_cap": cap,
            "export_retried": retried,
            "export_failed": failed,
            "dropped_shutdown": shut,
            "dropped_total": full + cap + failed + shut,
            "queued_bytes_estimate": held,
            "pending": len(self._pending),
        }
