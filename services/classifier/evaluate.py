"""Train + evaluate the failure classifier on the synthetic dataset.

Produces a precision/recall report (Phase 3 gate: binary failure-detection
precision >= 0.85 and recall >= 0.80 on a held-out test set).

    python -m services.classifier.evaluate
writes docs/classifier_report.md
"""

from __future__ import annotations

import os

import numpy as np

from nexus_agent.models import FailureType

from services.classifier.classifier import SEMANTIC_TYPES, FailureClassifier
from services.classifier.embedder import SpanEmbedder

import importlib.util

# Load the dataset module by path (tests/fixtures is not a package).
_FIX = os.path.join(os.path.dirname(__file__), "..", "..", "tests", "fixtures", "generate_synthetic_traces.py")
_spec = importlib.util.spec_from_file_location("synth", os.path.abspath(_FIX))
synth = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(synth)  # type: ignore

REPORT_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "classifier_report.md")
EMB_CACHE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "synthetic_embeddings.npy")

RNG = np.random.RandomState(0)


def _embed_all(traces) -> np.ndarray:
    cache = os.path.abspath(EMB_CACHE)
    if os.path.exists(cache):
        arr = np.load(cache)
        if arr.shape[0] == len(traces):
            return arr
    emb = SpanEmbedder().embed_traces(traces)
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    np.save(cache, emb)
    return emb


def _stratified_split(labels, test_frac=0.4):
    train_idx, test_idx = [], []
    by_label: dict = {}
    for i, l in enumerate(labels):
        by_label.setdefault(l, []).append(i)
    for l, idxs in by_label.items():
        idxs = list(idxs)
        RNG.shuffle(idxs)
        n_test = int(round(len(idxs) * test_frac))
        test_idx += idxs[:n_test]
        train_idx += idxs[n_test:]
    return sorted(train_idx), sorted(test_idx)


def main() -> None:
    traces, labels = synth.load_dataset()
    emb = _embed_all(traces)
    train_idx, test_idx = _stratified_split(labels)

    # --- train on the train split ---
    clf = FailureClassifier(embedder=SpanEmbedder())
    clf.train([traces[i] for i in train_idx], [labels[i] for i in train_idx], emb[train_idx])
    tau = clf.memory_bank.threshold

    # --- evaluate on held-out test set ---
    y_true, y_pred = [], []
    for i in test_idx:
        pred = clf.classify(traces[i], embedding=emb[i]).failure_type
        y_true.append(labels[i])
        y_pred.append(pred)

    # binary failure detection (non-NORMAL = positive)
    tp = sum(1 for t, p in zip(y_true, y_pred) if t != FailureType.NORMAL and p != FailureType.NORMAL)
    fp = sum(1 for t, p in zip(y_true, y_pred) if t == FailureType.NORMAL and p != FailureType.NORMAL)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t != FailureType.NORMAL and p == FailureType.NORMAL)
    tn = sum(1 for t, p in zip(y_true, y_pred) if t == FailureType.NORMAL and p == FailureType.NORMAL)
    det_prec = tp / (tp + fp) if (tp + fp) else 0.0
    det_rec = tp / (tp + fn) if (tp + fn) else 0.0

    # multiclass accuracy + per-class
    classes = [FailureType.NORMAL, *SEMANTIC_TYPES, FailureType.TOOL_MISFIRE, FailureType.LOOP_DETECTED]
    per_class = {}
    for c in classes:
        c_tp = sum(1 for t, p in zip(y_true, y_pred) if t == c and p == c)
        c_fp = sum(1 for t, p in zip(y_true, y_pred) if t != c and p == c)
        c_fn = sum(1 for t, p in zip(y_true, y_pred) if t == c and p != c)
        cp = c_tp / (c_tp + c_fp) if (c_tp + c_fp) else 0.0
        cr = c_tp / (c_tp + c_fn) if (c_tp + c_fn) else 0.0
        support = sum(1 for t in y_true if t == c)
        per_class[c.value] = (cp, cr, support)
    accuracy = sum(1 for t, p in zip(y_true, y_pred) if t == p) / len(y_true)

    report = _format_report(tau, len(test_idx), det_prec, det_rec, tp, fp, fn, tn,
                            accuracy, per_class)
    os.makedirs(os.path.dirname(os.path.abspath(REPORT_PATH)), exist_ok=True)
    with open(os.path.abspath(REPORT_PATH), "w", encoding="utf-8") as fh:
        fh.write(report)
    print(report)
    print(f"\nGATE: precision>=0.85 {'PASS' if det_prec >= 0.85 else 'FAIL'} | "
          f"recall>=0.80 {'PASS' if det_rec >= 0.80 else 'FAIL'}")


def _format_report(tau, n_test, prec, rec, tp, fp, fn, tn, acc, per_class) -> str:
    lines = [
        "# Nexus Failure Classifier - Evaluation Report",
        "",
        f"- Dataset: 200 synthetic traces (100 NORMAL + 20x5 failures)",
        f"- Held-out test set: {n_test} traces (stratified 40%)",
        f"- Stage 2: supervised SVM over [embedding ; PatchCore anomaly_score]",
        "",
        "## Binary failure detection (non-NORMAL = positive)",
        "",
        f"| Metric | Value | Target |",
        f"|---|---|---|",
        f"| Precision | **{prec:.3f}** | >= 0.85 |",
        f"| Recall | **{rec:.3f}** | >= 0.80 |",
        f"| Confusion | TP={tp} FP={fp} FN={fn} TN={tn} | |",
        "",
        "## Multiclass (per failure type)",
        "",
        "| Class | Precision | Recall | Support |",
        "|---|---|---|---|",
    ]
    for c, (p, r, s) in per_class.items():
        lines.append(f"| {c} | {p:.3f} | {r:.3f} | {s} |")
    lines += ["", f"Overall multiclass accuracy: **{acc:.3f}**", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
