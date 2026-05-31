"""HTTP exporter — ships span batches to the nexus-collector.

Fail-silent: any transport error is caught, logged as a warning, and the batch
is dropped. The exporter never raises into the SDK's worker loop or user code.
"""

from __future__ import annotations

import logging

import httpx

from nexus_agent.models import SpanBatch

logger = logging.getLogger("nexus_agent.exporters.http")


class HttpExporter:
    # Throttle repeated failure warnings so an unreachable collector can't
    # flood logs (warn on the 1st failure, then every Nth).
    _WARN_EVERY = 100

    def __init__(self, collector_url: str, timeout_ms: int = 200) -> None:
        self._url = collector_url.rstrip("/") + "/v1/spans"
        self._timeout_s = timeout_ms / 1000.0
        self._client = httpx.Client(timeout=self._timeout_s)
        self._consecutive_failures = 0

    def _note_failure(self, reason: str, batch_id: str) -> None:
        n = self._consecutive_failures
        self._consecutive_failures += 1
        if n == 0 or n % self._WARN_EVERY == 0:
            suffix = "" if n == 0 else f" ({n} failures so far)"
            logger.warning(
                "nexus: failed to export batch %s (%s); dropping%s", batch_id, reason, suffix
            )

    def export(self, batch: SpanBatch) -> bool:
        """Return True on a 2xx response, False otherwise (never raises)."""
        try:
            resp = self._client.post(
                self._url,
                json=batch.model_dump(mode="json"),
            )
            if resp.status_code // 100 == 2:
                self._consecutive_failures = 0
                return True
            self._note_failure(f"status={resp.status_code}", batch.batch_id)
            return False
        except Exception as exc:  # noqa: BLE001 — fail-silent by design
            self._note_failure(exc.__class__.__name__, batch.batch_id)
            return False

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:  # noqa: BLE001
            pass
