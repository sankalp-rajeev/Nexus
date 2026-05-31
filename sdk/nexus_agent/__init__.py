"""nexus-agent — zero-config observability SDK for multi-agent AI systems.

Quickstart::

    import nexus_agent as nexus
    nexus.init(agent_name="my-pipeline")

    @nexus.trace(span_type="llm_call", model="gemini-2.0-flash")
    def call_llm(prompt: str) -> str:
        ...

    nexus.flush()  # before process exit in short-lived scripts
"""

from __future__ import annotations

import atexit
import logging
import threading
from typing import Any

from nexus_agent import models  # noqa: F401
from nexus_agent.config import NexusConfig
from nexus_agent.client import NexusClient

__version__ = "1.0.0"

logger = logging.getLogger("nexus_agent")

_client: NexusClient | None = None
_lock = threading.Lock()


def init(
    agent_name: str,
    collector_url: str = "http://localhost:8000",
    environment: str = "development",
    async_export: bool = True,
    export_timeout_ms: int = 200,
    debug: bool = False,
    **kwargs: Any,
) -> NexusClient:
    """Initialize the global Nexus client. Safe to call once per process."""
    global _client
    with _lock:
        if _client is not None:
            logger.warning("nexus: already initialized; reusing existing client")
            return _client
        config = NexusConfig(
            agent_name=agent_name,
            collector_url=collector_url,
            environment=environment,
            async_export=async_export,
            export_timeout_ms=export_timeout_ms,
            debug=debug,
            **kwargs,
        )
        _client = NexusClient(config)
        atexit.register(_client.shutdown)
        return _client


def get_client() -> NexusClient | None:
    """Return the active client, or None if init() was never called."""
    return _client


def is_initialized() -> bool:
    return _client is not None


def shutdown() -> None:
    """Flush and stop the background exporter. Resets global state."""
    global _client
    with _lock:
        if _client is not None:
            _client.shutdown()
            _client = None


def flush() -> None:
    """Force-export all queued spans (call before process exit in scripts)."""
    if _client is not None:
        _client.flush()


def start_span(span_type: Any, agent_name: str | None = None, **metadata: Any) -> str | None:
    if _client is None:
        return None
    return _client.start_span(span_type, agent_name=agent_name, **metadata)


def end_span(span_id: str | None, output: Any = None, metadata: dict | None = None) -> None:
    if _client is None or span_id is None:
        return
    _client.end_span(span_id, output=output, metadata=metadata)


# Imported last to avoid a circular import (decorators import get_client).
from nexus_agent.decorators import span, trace  # noqa: E402

__all__ = [
    "__version__",
    "models",
    "NexusConfig",
    "NexusClient",
    "init",
    "get_client",
    "is_initialized",
    "shutdown",
    "flush",
    "trace",
    "span",
    "start_span",
    "end_span",
]
