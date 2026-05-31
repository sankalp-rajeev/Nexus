"""Two-stage failure classifier (Section 8.2).

Stage 1: deterministic rules -> LOOP_DETECTED / TOOL_MISFIRE.
Stage 2: embed trace, compute the PatchCore anomaly score against a memory bank
         of NORMAL traces, then a supervised SVM over
         [embedding ; anomaly_score ; io_divergence ; contradiction_score]
         predicts among NORMAL / HALLUCINATION / CONTEXT_BLEED / PLAN_DRIFT.

DEVIATION from the literal PRD (hard PatchCore threshold gate): the anomaly
score is fed to the SVM as a feature rather than used as a brittle cutoff. A
learned boundary generalizes to novel-but-normal traces, directly mitigating
Risk R1 (high false-positive rate on novel traces).

Feature vector dimensions: 384 (MiniLM embedding) + 1 (PatchCore) +
1 (io_divergence) + 1 (NLI contradiction_score) = 387 total.
"""

from __future__ import annotations

import logging
import os

import numpy as np

from nexus_agent.models import Classification, CompleteTrace, FailureType, SpanType

from services.classifier.embedder import NLIScorer, SpanEmbedder
from services.classifier.patchcore import PatchCoreMemoryBank
from services.classifier.rules import apply_rules

logger = logging.getLogger("nexus.classifier")

# Semantic anomaly types (resolved by the SVM alongside NORMAL).
SEMANTIC_TYPES = (
    FailureType.HALLUCINATION,
    FailureType.CONTEXT_BLEED,
    FailureType.PLAN_DRIFT,
)
# Types decided in Stage 2 (rule types LOOP/TOOL_MISFIRE are caught in Stage 1).
STAGE2_TYPES = (FailureType.NORMAL, *SEMANTIC_TYPES)


class SubClassifier:
    """SVM over [trace embedding ; anomaly_score] for Stage-2 types."""

    def __init__(self) -> None:
        self._model = None
        self._classes: list[str] = []

    def fit(self, features: np.ndarray, labels: list[FailureType]) -> None:
        from sklearn.svm import SVC

        y = [l.value for l in labels]
        self._model = SVC(kernel="rbf", C=10.0, gamma="scale", probability=True, random_state=0)
        self._model.fit(features, y)
        self._classes = list(self._model.classes_)

    def predict(self, features: np.ndarray) -> tuple[FailureType, float]:
        if self._model is None:
            return FailureType.NORMAL, 0.0
        vec = np.asarray(features, dtype=np.float32).reshape(1, -1)
        proba = self._model.predict_proba(vec)[0]
        idx = int(np.argmax(proba))
        return FailureType(self._classes[idx]), float(proba[idx])


class FailureClassifier:
    def __init__(
        self,
        embedder: SpanEmbedder | None = None,
        memory_bank: PatchCoreMemoryBank | None = None,
        sub_classifier: SubClassifier | None = None,
        threshold: float = PatchCoreMemoryBank().threshold,
        calib_size: int = 50,
    ) -> None:
        self.embedder = embedder or SpanEmbedder()
        self.memory_bank = memory_bank or PatchCoreMemoryBank(threshold=threshold)
        self.sub_classifier = sub_classifier or SubClassifier()
        self.threshold = threshold
        self.calib_size = calib_size

    def _io_divergence(self, trace: CompleteTrace) -> float:
        """Max input->output semantic divergence over llm_call spans.

        1 - cosine(embed(input), embed(output)). High for hallucinations whose
        output is unrelated to their input context (PRD hallucination signal).
        """
        pairs = [
            (s.input, s.output)
            for s in trace.spans
            if s.span_type == SpanType.LLM_CALL and s.input and s.output
        ]
        if not pairs:
            return 0.0
        texts = [p[0] for p in pairs] + [p[1] for p in pairs]
        vecs = self.embedder.encode(texts)  # already L2-normalized
        n = len(pairs)
        divs = [1.0 - float(np.dot(vecs[i], vecs[n + i])) for i in range(n)]
        return float(max(divs))

    def _contradiction_score(self, trace: CompleteTrace) -> float:
        """Max NLI contradiction probability over llm_call spans.

        Uses a cross-encoder NLI model to measure whether the LLM output is
        logically *contradicted* by its input context.  Unlike io_divergence
        (which only catches off-topic outputs), this fires on same-domain
        factual errors — the primary signal for HaluEval-style hallucinations.

        Returns the max contradiction probability across all llm_call spans,
        or 0.0 if there are no llm_call spans.
        """
        scorer = NLIScorer.get()
        scores = [
            scorer.contradiction_score(s.input or "", s.output or "")
            for s in trace.spans
            if s.span_type == SpanType.LLM_CALL
        ]
        return float(max(scores)) if scores else 0.0

    def _feature(self, embedding: np.ndarray, score: float, io_div: float,
                 contradiction: float) -> np.ndarray:
        return np.concatenate(
            [np.asarray(embedding, dtype=np.float32),
             [np.float32(score), np.float32(io_div), np.float32(contradiction)]]
        )

    # ── Training ────────────────────────────────────────────────────
    def train(
        self,
        traces: list[CompleteTrace],
        labels: list[FailureType],
        embeddings: np.ndarray | None = None,
    ) -> None:
        if embeddings is None:
            embeddings = self.embedder.embed_traces(traces)

        normal_idx = [i for i, l in enumerate(labels) if l == FailureType.NORMAL]
        stage2_idx = [i for i, l in enumerate(labels) if l in STAGE2_TYPES]
        if not normal_idx:
            raise ValueError("training set has no NORMAL traces for the memory bank")

        # PatchCore memory bank from a calibration subset of NORMAL traces.
        self.memory_bank.fit(embeddings[normal_idx[: self.calib_size]])

        feats = np.vstack([
            self._feature(
                embeddings[i],
                self.memory_bank.score(embeddings[i]),
                self._io_divergence(traces[i]),
                self._contradiction_score(traces[i]),
            )
            for i in stage2_idx
        ])
        self.sub_classifier.fit(feats, [labels[i] for i in stage2_idx])

    # ── Inference ───────────────────────────────────────────────────
    def classify(self, trace: CompleteTrace, embedding: np.ndarray | None = None) -> Classification:
        rule = apply_rules(trace)
        if rule is not None:
            return Classification(
                trace_id=trace.trace_id,
                failure_type=rule.failure_type,
                anomaly_score=None,
                confidence=1.0,
                triggered_rule=rule.triggered_rule,
                failure_span_id=rule.failure_span_id,
            )

        if embedding is None:
            embedding = self.embedder.embed_trace(trace)
        score = self.memory_bank.score(embedding)
        feature = self._feature(
            embedding, score,
            self._io_divergence(trace),
            self._contradiction_score(trace),
        )
        failure_type, conf = self.sub_classifier.predict(feature)
        is_failure = failure_type != FailureType.NORMAL
        return Classification(
            trace_id=trace.trace_id,
            failure_type=failure_type,
            anomaly_score=score,
            confidence=conf,
            triggered_rule="embedding+svm",
            failure_span_id=(trace.spans[-1].span_id if (is_failure and trace.spans) else None),
        )

    # ── Persistence ─────────────────────────────────────────────────
    def save(self, directory: str) -> None:
        import joblib

        os.makedirs(directory, exist_ok=True)
        self.memory_bank.save(os.path.join(directory, "memory_bank.npz"))
        joblib.dump(
            {"model": self.sub_classifier._model, "classes": self.sub_classifier._classes},
            os.path.join(directory, "svm.joblib"),
        )

    def load(self, directory: str) -> "FailureClassifier":
        import joblib

        self.memory_bank = PatchCoreMemoryBank.load(os.path.join(directory, "memory_bank.npz"))
        self.threshold = self.memory_bank.threshold
        payload = joblib.load(os.path.join(directory, "svm.joblib"))
        self.sub_classifier._model = payload["model"]
        self.sub_classifier._classes = payload["classes"]
        return self
