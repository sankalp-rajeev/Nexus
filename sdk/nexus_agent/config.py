"""Nexus SDK configuration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class NexusConfig:
    """Runtime configuration for the Nexus SDK.

    Created by ``nexus.init(...)``. All export work is non-blocking and
    fail-silent: if the collector is unreachable the SDK logs a warning and
    drops spans rather than raising into user code.
    """

    agent_name: str  # required: identifies this agent system
    collector_url: str = "http://localhost:8000"
    environment: str = "development"
    async_export: bool = True
    export_timeout_ms: int = 200
    debug: bool = False

    # Background exporter tuning (Section 7.3)
    flush_interval_ms: int = 100  # exporter wakes at least this often
    max_batch_size: int = 50  # also flush when the queue hits this many spans
    max_queue_size: int = 10_000  # drop (fail-silent) beyond this many queued spans
    # Byte cap on queued spans, on top of the count cap. The size of each span is
    # an ESTIMATE (string/bytes lengths + a fixed per-span constant), not an exact
    # measurement of process memory. Same policy as the count cap: drop newest.
    max_queue_bytes: int = 32 * 1024 * 1024
    # One retry per failed batch on the background thread, after a jittered
    # backoff drawn uniformly from [min, max] ms. Never in flush() or sync mode.
    export_retry_backoff_min_ms: int = 100
    export_retry_backoff_max_ms: int = 300

    # Capture limits (Section 13.1)
    max_input_chars: int = 2000
    max_output_chars: int = 2000
    max_error_chars: int = 500

    def __post_init__(self) -> None:
        if not self.agent_name or not str(self.agent_name).strip():
            raise ValueError("nexus.init() requires a non-empty agent_name")
        if self.export_timeout_ms <= 0:
            raise ValueError("export_timeout_ms must be > 0")
        if self.max_batch_size <= 0:
            raise ValueError("max_batch_size must be > 0")
        # No unbounded queues: queue.Queue(maxsize<=0) is infinite, so reject it.
        for name in ("max_queue_size", "max_queue_bytes"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer (got {value!r}); "
                                 "unbounded queues are not allowed")
        lo, hi = self.export_retry_backoff_min_ms, self.export_retry_backoff_max_ms
        if (isinstance(lo, bool) or isinstance(hi, bool) or not isinstance(lo, int)
                or not isinstance(hi, int) or lo < 0 or hi < lo):
            raise ValueError("export_retry_backoff_min_ms/max_ms must be integers with 0 <= min <= max")
