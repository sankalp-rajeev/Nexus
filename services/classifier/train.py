"""Train the production classifier and persist artifacts.

Usage:
    python -m services.classifier.train
    python -m services.classifier.train --dataset tests/fixtures/master_traces.json
    python -m services.classifier.train --dataset tests/fixtures/master_traces.json \\
        --eval-strategy stratified

--eval-strategy options:
    random      — random 80/20 split on the full dataset (original behaviour)
    stratified  — train on source=synthetic, test on source!=synthetic (default)
"""

from __future__ import annotations

import argparse
import json
import os

import numpy as np

from nexus_agent.models import CompleteTrace, FailureType

from services.classifier.classifier import FailureClassifier
from services.classifier.embedder import SpanEmbedder

MODEL_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "classifier_model")
)
_DEFAULT_DATASET = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "tests", "fixtures",
                 "synthetic_traces.json")
)
_MASTER_DATASET = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "tests", "fixtures",
                 "master_traces.json")
)


def _load_dataset(path: str) -> tuple[list[CompleteTrace], list[FailureType], list[str]]:
    """Returns (traces, labels, sources)."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    raw_traces = data["traces"]
    raw_labels = data["labels"]
    traces = [CompleteTrace.model_validate(t) for t in raw_traces]
    labels = [FailureType(l) for l in raw_labels]
    sources = [t.get("source", "synthetic") for t in raw_traces]
    return traces, labels, sources


def _random_split(labels, sources, rng, train_frac=0.8):
    idx = list(range(len(labels)))
    rng.shuffle(idx)
    n_train = int(len(idx) * train_frac)
    return sorted(idx[:n_train]), sorted(idx[n_train:])


def _source_split(sources):
    train_idx = [i for i, s in enumerate(sources) if s == "synthetic"]
    test_idx = [i for i, s in enumerate(sources) if s != "synthetic"]
    return train_idx, test_idx


def main() -> None:
    parser = argparse.ArgumentParser(description="Train Nexus failure classifier")
    parser.add_argument(
        "--dataset",
        default=_MASTER_DATASET if os.path.exists(_MASTER_DATASET) else _DEFAULT_DATASET,
        help="Path to traces JSON dataset (default: master_traces.json if present)",
    )
    parser.add_argument(
        "--eval-strategy",
        choices=["random", "stratified"],
        default="stratified",
        help="Split strategy: 'random' (80/20) or 'stratified' (train=synthetic, test=real)",
    )
    args = parser.parse_args()

    print(f"Loading dataset: {args.dataset}")
    traces, labels, sources = _load_dataset(args.dataset)

    rng = np.random.RandomState(0)
    if args.eval_strategy == "stratified":
        train_idx, test_idx = _source_split(sources)
        if not train_idx:
            print("WARNING: no synthetic traces found; falling back to random split")
            train_idx, test_idx = _random_split(labels, sources, rng)
        else:
            print(
                f"Stratified split: {len(train_idx)} train (synthetic) / "
                f"{len(test_idx)} test (real-world)"
            )
    else:
        train_idx, test_idx = _random_split(labels, sources, rng)
        print(f"Random split: {len(train_idx)} train / {len(test_idx)} test")

    train_traces = [traces[i] for i in train_idx]
    train_labels = [labels[i] for i in train_idx]

    print(f"Embedding {len(traces)} traces...")
    embedder = SpanEmbedder()
    all_emb = embedder.embed_traces(traces)

    clf = FailureClassifier(embedder=embedder)
    clf.train(train_traces, train_labels, all_emb[train_idx])
    clf.save(MODEL_DIR)
    print(
        f"Saved classifier model -> {MODEL_DIR} "
        f"(bank={clf.memory_bank.size}, tau={clf.memory_bank.threshold:.4f})"
    )


if __name__ == "__main__":
    main()
