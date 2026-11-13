"""Shared pytest fixtures. Puts the SDK and repo root on sys.path and provides
a deterministic, synchronous span-collecting Nexus client."""

from __future__ import annotations

import os
import sys

import pytest

# Tests use the deterministic mock LLM, selected explicitly (never by a
# missing key). Real-model runs live in scripts/experiments, not in pytest.
os.environ["NEXUS_LLM"] = "mock"

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
    import nexus_llmops as nexus

    nexus.shutdown()
    yield
    nexus.shutdown()


@pytest.fixture
def nexus_client():
    """Synchronous client whose exporter collects spans in memory."""
    import nexus_llmops as nexus

    client = nexus.init(agent_name="test-agent", async_export=False)
    exporter = CollectingExporter()
    client._exporter = exporter
    yield client, exporter


@pytest.fixture(scope="session")
def required_classifier_nli():
    """Require real NLI inference before testing its scores or classifications."""
    from services.classifier.embedder import NLIScorer

    scorer = NLIScorer.get()
    if not isinstance(scorer, NLIScorer) or getattr(scorer,"model",None) is None:
        pytest.fail(
            f"NLI model not loaded: {NLIScorer.MODEL_NAME}. "
            "Run python scripts/ci/prepare_models.py to stage pinned inference files; "
            "a zero-score fallback is not valid for these tests.", pytrace=False)
    return scorer
