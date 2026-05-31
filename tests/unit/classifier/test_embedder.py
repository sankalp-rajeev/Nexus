"""Unit tests: SpanEmbedder (loads the cached MiniLM model)."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest

from nexus_agent.models import CompleteTrace, Span, SpanType, TraceStatus

from services.classifier.embedder import EMBED_DIM, SpanEmbedder


@pytest.fixture(scope="module")
def embedder():
    return SpanEmbedder()


def _trace(n_spans=3) -> CompleteTrace:
    spans = [
        Span(
            span_id=f"s{i}", trace_id="t", agent_name="a", span_type=SpanType.LLM_CALL,
            input=f"input number {i}", output=f"output number {i}", duration_ms=1.0,
            client_timestamp=datetime.now(timezone.utc), sdk_version="1.0.0",
        )
        for i in range(n_spans)
    ]
    return CompleteTrace(trace_id="t", agent_name="a", started_at=datetime.now(timezone.utc),
                         status=TraceStatus.COMPLETED, span_count=n_spans, spans=spans)


def test_encode_shape_and_normalized(embedder):
    vecs = embedder.encode(["hello world", "tool call failed"])
    assert vecs.shape == (2, EMBED_DIM)
    norms = np.linalg.norm(vecs, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-3)


def test_embed_trace_shape_and_normalized(embedder):
    vec = embedder.embed_trace(_trace())
    assert vec.shape == (EMBED_DIM,)
    assert np.linalg.norm(vec) == pytest.approx(1.0, abs=1e-3)


def test_empty_trace_returns_zeros(embedder):
    empty = CompleteTrace(trace_id="t", agent_name="a", started_at=datetime.now(timezone.utc),
                          status=TraceStatus.COMPLETED, span_count=0, spans=[])
    vec = embedder.embed_trace(empty)
    assert vec.shape == (EMBED_DIM,)
    assert np.allclose(vec, 0.0)


def test_embed_traces_stacks(embedder):
    mat = embedder.embed_traces([_trace(), _trace(2)])
    assert mat.shape == (2, EMBED_DIM)


def test_embedding_is_deterministic(embedder):
    t = _trace()
    a = embedder.embed_trace(t)
    b = embedder.embed_trace(t)
    assert np.allclose(a, b)


# ── NLIScorer tests ────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def nli():
    from services.classifier.embedder import NLIScorer
    return NLIScorer.get()


def test_nli_contradiction_high(nli):
    score = nli.contradiction_score(
        "The Eiffel Tower is in Paris France",
        "The Eiffel Tower is in Berlin Germany",
    )
    assert score > 0.5, f"expected high contradiction, got {score:.3f}"


def test_nli_contradiction_low(nli):
    score = nli.contradiction_score(
        "The Eiffel Tower is in Paris France",
        "The Eiffel Tower is in Paris France",
    )
    assert score < 0.3, f"expected low contradiction, got {score:.3f}"


def test_nli_empty_input_returns_zero(nli):
    score = nli.contradiction_score("", "some output text that is fairly long")
    assert score == 0.0
