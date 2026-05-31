"""Phase 3 exit criterion: the classifier correctly labels the 3 manually-
labeled CrewAI example traces. Loads the persisted production model."""

from __future__ import annotations

import importlib.util
import os

import pytest

from services.classifier.classifier import FailureClassifier

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODEL_DIR = os.path.join(_REPO, "data", "classifier_model")
_EX = os.path.join(_REPO, "examples", "crewai_agent", "example_traces.py")


def _load_examples():
    spec = importlib.util.spec_from_file_location("crew_examples", _EX)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore
    return mod.labeled_examples()


pytestmark = pytest.mark.skipif(
    not os.path.exists(os.path.join(MODEL_DIR, "svm.joblib")),
    reason="trained classifier model not found; run python -m services.classifier.train",
)


@pytest.fixture(scope="module")
def classifier():
    return FailureClassifier().load(MODEL_DIR)


def test_crewai_examples_classified_correctly(classifier):
    results = []
    for trace, expected in _load_examples():
        predicted = classifier.classify(trace).failure_type
        results.append((trace.trace_id, expected.value, predicted.value))
        assert predicted == expected, f"{trace.trace_id}: expected {expected}, got {predicted}"
    assert len(results) == 3
