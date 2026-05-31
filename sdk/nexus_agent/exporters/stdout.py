"""Stdout exporter — debug mode. Prints spans instead of shipping them."""

from __future__ import annotations

import json
import logging
import sys

from nexus_agent.models import SpanBatch

logger = logging.getLogger("nexus_agent.exporters.stdout")


class StdoutExporter:
    def __init__(self, stream=None) -> None:
        self._stream = stream or sys.stdout

    def export(self, batch: SpanBatch) -> bool:
        try:
            for span in batch.spans:
                self._stream.write(
                    "[nexus] " + json.dumps(span.model_dump(mode="json")) + "\n"
                )
            self._stream.flush()
            return True
        except Exception as exc:  # noqa: BLE001 — fail-silent by design
            logger.warning("nexus: stdout export failed (%s)", exc.__class__.__name__)
            return False

    def close(self) -> None:
        pass
