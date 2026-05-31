"""PatchCore-style anomaly detection on an embedding memory bank (Section 8.2).

A memory bank of NORMAL trace embeddings. The anomaly score of a new trace is
its nearest-neighbour L2 distance to the bank. score > threshold -> ANOMALY.

This is the IndexFlatL2 (exact, brute-force L2) computation done in NumPy so the
classifier has no native-build dependency (Faiss is an optional drop-in). See
Roth et al., "Towards Total Recall in Industrial Anomaly Detection" (2022).
"""

from __future__ import annotations

import numpy as np

DEFAULT_THRESHOLD = 0.45  # tau (Section 11.4 PATCHCORE_THRESHOLD)


class PatchCoreMemoryBank:
    def __init__(self, threshold: float = DEFAULT_THRESHOLD, max_size: int = 500) -> None:
        self.threshold = threshold
        self.max_size = max_size
        self._bank: np.ndarray | None = None

    @property
    def is_fitted(self) -> bool:
        return self._bank is not None and len(self._bank) > 0

    @property
    def size(self) -> int:
        return 0 if self._bank is None else int(self._bank.shape[0])

    def fit(self, normal_embeddings: np.ndarray) -> None:
        """Populate the bank from NORMAL trace embeddings (calibration)."""
        emb = np.asarray(normal_embeddings, dtype=np.float32)
        if emb.ndim != 2:
            raise ValueError("normal_embeddings must be 2-D (n, dim)")
        if emb.shape[0] > self.max_size:
            emb = emb[: self.max_size]
        self._bank = emb

    def add(self, embedding: np.ndarray) -> None:
        vec = np.asarray(embedding, dtype=np.float32).reshape(1, -1)
        if self._bank is None:
            self._bank = vec
        elif self._bank.shape[0] < self.max_size:
            self._bank = np.vstack([self._bank, vec])

    def score(self, embedding: np.ndarray) -> float:
        """Min L2 distance to any bank entry (the anomaly score)."""
        if not self.is_fitted:
            raise RuntimeError("PatchCore memory bank is not fitted")
        vec = np.asarray(embedding, dtype=np.float32).reshape(1, -1)
        dists = np.linalg.norm(self._bank - vec, axis=1)
        return float(dists.min())

    def is_anomaly(self, embedding: np.ndarray) -> bool:
        return self.score(embedding) > self.threshold

    # ── Persistence ─────────────────────────────────────────────────
    def save(self, path: str) -> None:
        np.savez(path, bank=self._bank, threshold=self.threshold, max_size=self.max_size)

    @classmethod
    def load(cls, path: str) -> "PatchCoreMemoryBank":
        data = np.load(path, allow_pickle=False)
        inst = cls(threshold=float(data["threshold"]), max_size=int(data["max_size"]))
        inst._bank = data["bank"]
        return inst
