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
    max_queue_size: int = 10_000  # drop (fail-silent) beyond this backlog

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
