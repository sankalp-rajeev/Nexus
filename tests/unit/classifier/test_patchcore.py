"""Unit tests: PatchCore memory bank."""

from __future__ import annotations

import numpy as np
import pytest

from services.classifier.patchcore import PatchCoreMemoryBank


def _bank(threshold=0.45):
    b = PatchCoreMemoryBank(threshold=threshold, max_size=5)
    b.fit(np.eye(3, dtype=np.float32))  # 3 orthonormal vectors
    return b


def test_fit_sets_state():
    b = _bank()
    assert b.is_fitted
    assert b.size == 3


def test_score_zero_for_member():
    b = _bank()
    assert b.score(np.array([1.0, 0.0, 0.0])) == pytest.approx(0.0, abs=1e-6)


def test_score_positive_for_far_vector():
    b = _bank()
    assert b.score(np.array([5.0, 5.0, 5.0])) > 1.0


def test_is_anomaly_threshold_behavior():
    b = _bank(threshold=0.5)
    assert b.is_anomaly(np.array([5.0, 0.0, 0.0])) is True
    near = np.array([1.0, 0.05, 0.0])  # close to a member -> small distance
    assert b.is_anomaly(near) is False


def test_score_requires_fit():
    b = PatchCoreMemoryBank()
    with pytest.raises(RuntimeError):
        b.score(np.zeros(3))


def test_add_respects_max_size():
    b = PatchCoreMemoryBank(max_size=2)
    for _ in range(5):
        b.add(np.ones(3, dtype=np.float32))
    assert b.size == 2


def test_fit_truncates_to_max_size():
    b = PatchCoreMemoryBank(max_size=2)
    b.fit(np.random.RandomState(0).rand(10, 4).astype(np.float32))
    assert b.size == 2


def test_save_load_round_trip(tmp_path):
    b = _bank(threshold=0.33)
    p = str(tmp_path / "bank.npz")
    b.save(p)
    loaded = PatchCoreMemoryBank.load(p)
    assert loaded.size == 3
    assert loaded.threshold == pytest.approx(0.33)
    assert loaded.score(np.array([1.0, 0.0, 0.0])) == pytest.approx(0.0, abs=1e-6)
