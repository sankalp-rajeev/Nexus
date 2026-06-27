"""Evaluate the failure classifier with source-stratified split.

Methodology (v2): trained on synthetic data, evaluated on real-world
out-of-distribution data (HaluEval + ToolBench).

    python -m services.classifier.evaluate
writes docs/classifier_report.md
"""

from __future__ import annotations

import json
import os
from collections import defaultdict

import numpy as np

from nexus_agent.models import CompleteTrace, FailureType

from services.classifier.classifier import SEMANTIC_TYPES, FailureClassifier
from services.classifier.embedder import SpanEmbedder

REPORT_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "docs", "classifier_report.md")
)
_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_MASTER = os.path.join(_REPO, "tests", "fixtures", "master_traces.json")
_SYNTHETIC = os.path.join(_REPO, "tests", "fixtures", "synthetic_traces.json")

EMB_CACHE = os.path.join(_REPO, "data", "master_embeddings.npy")
EMB_CACHE_SYN = os.path.join(_REPO, "data", "synthetic_embeddings.npy")


def _load_dataset(path: str):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    traces = [CompleteTrace.model_validate(t) for t in data["traces"]]
    labels = [FailureType(l) for l in data["labels"]]
    sources = [t.get("source", "synthetic") for t in data["traces"]]
    return traces, labels, sources


def _embed_all(traces, cache_path: str) -> np.ndarray:
    cache = os.path.abspath(cache_path)
    if os.path.exists(cache):
        arr = np.load(cache)
        if arr.shape[0] == len(traces):
            return arr
    emb = SpanEmbedder().embed_traces(traces)
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    np.save(cache, emb)
    return emb


def _binary_metrics(y_true, y_pred):
    tp = sum(1 for t, p in zip(y_true, y_pred) if t != FailureType.NORMAL and p != FailureType.NORMAL)
    fp = sum(1 for t, p in zip(y_true, y_pred) if t == FailureType.NORMAL and p != FailureType.NORMAL)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t != FailureType.NORMAL and p == FailureType.NORMAL)
    tn = sum(1 for t, p in zip(y_true, y_pred) if t == FailureType.NORMAL and p == FailureType.NORMAL)
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    acc = sum(1 for t, p in zip(y_true, y_pred) if t == p) / len(y_true) if y_true else 0.0
    return prec, rec, f1, acc, tp, fp, fn, tn


def main() -> None:
    # Prefer master dataset; fall back to synthetic-only
    dataset_path = _MASTER if os.path.exists(_MASTER) else _SYNTHETIC
    use_stratified = dataset_path == _MASTER
    cache_path = EMB_CACHE if use_stratified else EMB_CACHE_SYN

    print(f"Loading dataset: {dataset_path}")
    traces, labels, sources = _load_dataset(dataset_path)

    print(f"Embedding {len(traces)} traces...")
    emb = _embed_all(traces, cache_path)

    # Train on synthetic, test on real-world (or random 60/40 if synthetic-only)
    if use_stratified:
        train_idx = [i for i, s in enumerate(sources) if s == "synthetic"]
        test_idx  = [i for i, s in enumerate(sources) if s != "synthetic"]
        strategy_label = "source-stratified (train=synthetic, test=real-world)"
    else:
        rng = np.random.RandomState(0)
        by_label: dict = {}
        for i, l in enumerate(labels):
            by_label.setdefault(l, []).append(i)
        train_idx, test_idx = [], []
        for l, idxs in by_label.items():
            idxs = list(idxs); rng.shuffle(idxs)
            n_test = int(round(len(idxs) * 0.4))
            test_idx += idxs[:n_test]; train_idx += idxs[n_test:]
        train_idx.sort(); test_idx.sort()
        strategy_label = "random stratified 60/40"

    if not test_idx:
        print("WARNING: no test traces; aborting evaluation")
        return

    print(f"Strategy: {strategy_label}")
    print(f"  Train: {len(train_idx)} | Test: {len(test_idx)}")

    clf = FailureClassifier(embedder=SpanEmbedder())
    clf.train(
        [traces[i] for i in train_idx],
        [labels[i] for i in train_idx],
        emb[train_idx],
    )

    # Evaluate on test set
    y_true = [labels[i] for i in test_idx]
    y_pred = [clf.classify(traces[i], embedding=emb[i]).failure_type for i in test_idx]
    test_sources = [sources[i] for i in test_idx]

    prec, rec, f1, acc, tp, fp, fn, tn = _binary_metrics(y_true, y_pred)

    # Per-source breakdown
    source_groups: dict[str, tuple[list, list]] = defaultdict(lambda: ([], []))
    for t, p, s in zip(y_true, y_pred, test_sources):
        source_groups[s][0].append(t)
        source_groups[s][1].append(p)

    per_source = {}
    for src, (yt, yp) in source_groups.items():
        sp, sr, sf, sa, stp, sfp, sfn, stn = _binary_metrics(yt, yp)
        per_source[src] = (sp, sr, sf, sa, len(yt))

    # Per-class multiclass
    classes = [FailureType.NORMAL, *SEMANTIC_TYPES, FailureType.TOOL_MISFIRE, FailureType.LOOP_DETECTED]
    per_class = {}
    for c in classes:
        c_tp = sum(1 for t, p in zip(y_true, y_pred) if t == c and p == c)
        c_fp = sum(1 for t, p in zip(y_true, y_pred) if t != c and p == c)
        c_fn = sum(1 for t, p in zip(y_true, y_pred) if t == c and p != c)
        cp = c_tp / (c_tp + c_fp) if (c_tp + c_fp) else 0.0
        cr = c_tp / (c_tp + c_fn) if (c_tp + c_fn) else 0.0
        per_class[c.value] = (cp, cr, sum(1 for t in y_true if t == c))

    report = _format_report(
        strategy_label, len(train_idx), len(test_idx),
        prec, rec, f1, acc, tp, fp, fn, tn, per_class, per_source,
    )
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as fh:
        fh.write(report)
    print(report)
    print(f"\nGATE: precision>=0.85 {'PASS' if prec >= 0.85 else 'FAIL'} | "
          f"recall>=0.80 {'PASS' if rec >= 0.80 else 'FAIL'}")


def _format_report(strategy, n_train, n_test, prec, rec, f1, acc,
                   tp, fp, fn, tn, per_class, per_source) -> str:
    lines = [
        "# Nexus Failure Classifier - Evaluation Report",
        "",
        "## Evaluation v2 - Source-Stratified (Real-World Test Set)",
        "",
        f"- Methodology: {strategy}",
        f"- Train set: {n_train} traces | Test set: {n_test} traces",
        "- Stage 2: supervised SVM over [embedding ; PatchCore anomaly_score ; io_divergence]",
        "",
        "## OVERALL (real-world test set)",
        "",
        "### Binary failure detection (non-NORMAL = positive)",
        "",
        "| Metric | Value | Target |",
        "|---|---|---|",
        f"| Precision | **{prec:.3f}** | >= 0.85 |",
        f"| Recall | **{rec:.3f}** | >= 0.80 |",
        f"| F1 | **{f1:.3f}** | |",
        f"| Confusion | TP={tp} FP={fp} FN={fn} TN={tn} | |",
        "",
        f"Overall multiclass accuracy: **{acc:.3f}**",
        "",
        "### Per-class breakdown",
        "",
        "| Class | Precision | Recall | Support |",
        "|---|---|---|---|",
    ]
    for c, (p, r, s) in per_class.items():
        lines.append(f"| {c} | {p:.3f} | {r:.3f} | {s} |")

    if per_source:
        lines += [
            "",
            "## BY SOURCE",
            "",
            "| Source | N | Precision | Recall | F1 | Accuracy |",
            "|---|---|---|---|---|---|",
        ]
        for src, (sp, sr, sf, sa, n) in sorted(per_source.items()):
            lines.append(f"| {src} | {n} | {sp:.3f} | {sr:.3f} | {sf:.3f} | {sa:.3f} |")

    lines += [""]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
