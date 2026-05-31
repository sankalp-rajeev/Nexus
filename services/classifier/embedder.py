"""Stage 2 — span/trace embedding via sentence-transformers (Section 8.2).

Produces a 384-d trace embedding by mean-pooling per-span feature embeddings.
Embeddings are L2-normalized so PatchCore L2 distances live in a stable range
(making the default threshold tau=0.45 meaningful).

Also provides NLIScorer — a cross-encoder NLI model that measures whether an
LLM output is *contradicted* by its input context, adding a direct hallucination
signal beyond embedding cosine similarity.
"""

from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np

from nexus_agent.models import CompleteTrace, Span

from services.classifier.features import span_feature_string

logger = logging.getLogger("nexus.classifier.embedder")

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
NLI_MODEL = "cross-encoder/nli-MiniLM2-L6-H768"
EMBED_DIM = 384


@lru_cache(maxsize=2)
def _load_model(model_name: str):
    from sentence_transformers import SentenceTransformer

    logger.info("nexus-classifier: loading embedding model %s", model_name)
    return SentenceTransformer(model_name, device="cpu")


# ── NLI scorer ────────────────────────────────────────────────────────────────

class _NullNLIScorer:
    """Fallback scorer that always returns 0.0 when NLI model unavailable."""

    def contradiction_score(self, premise: str, hypothesis: str) -> float:  # noqa: ARG002
        return 0.0


class NLIScorer:
    """Cross-encoder NLI scorer: returns the CONTRADICTION probability.

    Lazy singleton — the model is downloaded only on the first call to
    NLIScorer.get(). Keeps import-time and test startup fast.

    If the model fails to load (no internet, disk error, etc.) the instance
    is replaced with a NullNLIScorer so inference never crashes.
    """

    MODEL_NAME = NLI_MODEL
    _instance: "NLIScorer | _NullNLIScorer | None" = None

    @classmethod
    def get(cls) -> "NLIScorer | _NullNLIScorer":
        if cls._instance is None:
            try:
                cls._instance = cls()
            except Exception as exc:
                logger.warning(
                    "nexus-classifier: NLI model failed to load (%s); "
                    "contradiction_score will be 0.0 for all traces",
                    exc,
                )
                cls._instance = _NullNLIScorer()
        return cls._instance

    def __init__(self) -> None:
        from sentence_transformers import CrossEncoder

        logger.info("nexus-classifier: loading NLI model %s", self.MODEL_NAME)
        self.model = CrossEncoder(self.MODEL_NAME)

    def contradiction_score(self, premise: str, hypothesis: str) -> float:
        """Probability that *hypothesis* is CONTRADICTED by *premise*.

        Cross-encoder NLI output order: [CONTRADICTION, ENTAILMENT, NEUTRAL].
        Returns the softmax-normalised CONTRADICTION probability in [0, 1].
        Returns 0.0 when either string is too short to carry meaningful signal.
        """
        if len(premise.strip()) < 10 or len(hypothesis.strip()) < 10:
            return 0.0
        scores = self.model.predict(
            [(premise[:512], hypothesis[:512])],
            apply_softmax=True,
        )
        # scores shape: (1, 3) — [contradiction, entailment, neutral]
        return float(scores[0][0])


class SpanEmbedder:
    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self.model_name = model_name
        self.dim = EMBED_DIM

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        model = _load_model(self.model_name)
        vecs = model.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return np.asarray(vecs, dtype=np.float32)

    def embed_trace(self, trace: CompleteTrace) -> np.ndarray:
        """Mean-pool per-span feature embeddings -> single 384-d vector."""
        spans: list[Span] = trace.spans
        if not spans:
            return np.zeros(self.dim, dtype=np.float32)
        features = [span_feature_string(s) for s in spans]
        per_span = self.encode(features)
        pooled = per_span.mean(axis=0)
        # Re-normalize the pooled vector for consistent L2 geometry.
        norm = np.linalg.norm(pooled)
        if norm > 0:
            pooled = pooled / norm
        return pooled.astype(np.float32)

    def embed_traces(self, traces: list[CompleteTrace]) -> np.ndarray:
        return np.vstack([self.embed_trace(t) for t in traces]) if traces else np.zeros((0, self.dim), dtype=np.float32)
