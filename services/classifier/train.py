"""Train the production classifier on the full synthetic dataset and persist
artifacts to data/classifier_model/ for the running service to load.

    python -m services.classifier.train
"""

from __future__ import annotations

import importlib.util
import os

from services.classifier.classifier import FailureClassifier
from services.classifier.embedder import SpanEmbedder

MODEL_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "classifier_model"))
_FIX = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "tests", "fixtures", "generate_synthetic_traces.py"))


def _load_synth():
    spec = importlib.util.spec_from_file_location("synth", _FIX)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore
    return mod


def main() -> None:
    synth = _load_synth()
    traces, labels = synth.load_dataset()
    emb = SpanEmbedder().embed_traces(traces)

    clf = FailureClassifier()
    clf.train(traces, labels, emb)
    clf.save(MODEL_DIR)
    print(f"saved classifier model -> {MODEL_DIR} (bank={clf.memory_bank.size})")


if __name__ == "__main__":
    main()
