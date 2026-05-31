"""Shared pytest fixtures. Puts the SDK and repo root on sys.path and provides
a deterministic, synchronous span-collecting Nexus client."""

from __future__ import annotations

import os
import sys

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SDK = os.path.join(_REPO_ROOT, "sdk")
for _p in (_SDK, _REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class CollectingExporter:
    """Test double: stores exported spans instead of shipping them."""

    def __init__(self) -> None:
        self.spans: list = []
        self.batches: int = 0

    def export(self, batch) -> bool:
        self.spans.extend(batch.spans)
        self.batches += 1
        return True

    def close(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _clean_nexus_state():
    """Ensure each test starts and ends with no global client."""
    import nexus_agent as nexus

    nexus.shutdown()
    yield
    nexus.shutdown()


@pytest.fixture
def nexus_client():
    """Synchronous client whose exporter collects spans in memory."""
    import nexus_agent as nexus

    client = nexus.init(agent_name="test-agent", async_export=False)
    exporter = CollectingExporter()
    client._exporter = exporter
    yield client, exporter
