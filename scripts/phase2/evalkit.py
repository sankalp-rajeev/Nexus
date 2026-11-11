"""Shared evaluation code for the Phase 2 dev tuning and the one-time test run.

Uses bench.scoring (pre-registered rules) unchanged and adds F1, false alerts
per 1,000 NORMAL traces, latency percentiles and markdown rendering.
"""

from __future__ import annotations

import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for _p in (REPO, os.path.join(REPO, "sdk")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np  # noqa: E402

from bench.detector_view import detector_view  # noqa: E402
from bench.scoring import CLASSES, EXCLUDED, HEADLINE, TARGET_PRECISION, prop, score  # noqa: E402
from services.detectors import judge as judge_mod  # noqa: E402
from services.detectors import pipeline  # noqa: E402

DETECTOR_KEYS = {"HALLUCINATION": "halluc", "CONTEXT_BLEED": "bleed", "PLAN_DRIFT": "drift"}


def views_for(rows, traces):
    return {r["trace_id"]: detector_view(traces[r["trace_id"]]) for r in rows}


def compute_all(views: dict) -> dict:
    return {tid: pipeline.compute_scores(v) for tid, v in views.items()}


def judge_all(views: dict) -> dict:
    return {tid: judge_mod.judge(v) for tid, v in views.items()}


def class_pr(rows, flags: dict[str, bool], cls: str):
    rs = [r for r in rows if r["label"] not in EXCLUDED]
    tp = sum(1 for r in rs if r["label"] == cls and flags[r["trace_id"]])
    fp = sum(1 for r in rs if r["label"] != cls and flags[r["trace_id"]])
    fn = sum(1 for r in rs if r["label"] == cls and not flags[r["trace_id"]])
    return prop(tp, tp + fp), prop(tp, tp + fn)


def choose(curve: list[dict]) -> dict:
    """Pre-registered: max dev recall s.t. dev precision >= 0.90; else max precision.

    Tie-break (fixed before the freeze; the pre-registration was silent): when
    several thresholds give the same best (precision, recall), use the midpoint
    of the tied threshold range (maximum margin), not an endpoint.
    """
    def key_ok(p):
        return (p["recall"]["value"], p["precision"]["value"])

    def key_fallback(p):
        return ((p["precision"]["value"] or 0), p["recall"]["value"] or 0)

    ok = [p for p in curve if (p["precision"]["value"] or 0) >= TARGET_PRECISION]
    pool, key, meets = (ok, key_ok, True) if ok else (curve, key_fallback, False)
    top = max(key(p) for p in pool)
    tied = [p for p in pool if key(p) == top]
    best = dict(tied[0])
    if "threshold" in best and len(tied) > 1:
        lo, hi = min(p["threshold"] for p in tied), max(p["threshold"] for p in tied)
        best["threshold"] = round((lo + hi) / 2, 4)
        best["tied_threshold_range"] = [lo, hi]
    return {**best, "meets_precision_floor": meets}


def f1(pc: dict) -> float | None:
    p, r = pc["precision"]["value"], pc["recall"]["value"]
    if p is None or r is None or p + r == 0:
        return None if p is None or r is None else 0.0
    return round(2 * p * r / (p + r), 4)


def false_alerts_per_1000(rows, preds) -> dict:
    normal = [r for r in rows if r["label"] == "NORMAL"]
    k = sum(1 for r in normal if preds[r["trace_id"]] != "NORMAL")
    return {"per_1000": round(1000 * k / len(normal), 1) if normal else None, **prop(k, len(normal))}


def latency(scores: dict) -> dict:
    s = np.array([v.seconds for v in scores.values()]) * 1000
    return {"p50_ms": round(float(np.percentile(s, 50)), 1),
            "p95_ms": round(float(np.percentile(s, 95)), 1),
            "max_ms": round(float(s.max()), 1), "n": int(len(s))}


def full_report(rows, preds) -> dict:
    res = score(rows, preds)
    for block in [res["all"], *res["per_model"].values()]:
        for c in CLASSES:
            block["per_class"][c]["f1"] = f1(block["per_class"][c])
    res["false_alerts"] = {"all": false_alerts_per_1000(rows, preds),
                           "per_model": {m: false_alerts_per_1000(
                               [r for r in rows if r["model"] == m], preds)
                               for m in sorted({r["model"] for r in rows})}}
    return res


def _fmt(p) -> str:
    if p is None or p["value"] is None:
        return "n/a"
    lo, hi = p["ci95_clopper_pearson"]
    return f"{p['value']:.3f} ({p['k']}/{p['n']}; {lo:.2f}–{hi:.2f})"


def class_table(block: dict, baseline: dict | None = None) -> list[str]:
    pc = block["per_class"]
    head = "| Class | Kind | Support | Precision | Recall | F1 |"
    sep = "|---|---|---|---|---|---|"
    if baseline:
        head += " Baseline P / R |"
        sep += "---|"
    lines = [head, sep]
    for c in CLASSES:
        d = pc[c]
        row = (f"| {c} | {d['kind']} | {d['support']} | {_fmt(d['precision'])} | "
               f"{_fmt(d['recall'])} | {d['f1'] if d['f1'] is not None else 'n/a'} |")
        if baseline:
            b = baseline["per_class"][c]
            row += f" {b['precision']['value']} / {b['recall']['value']} |"
        lines.append(row)
    lines += ["", f"Headline macro recall (H, CB, PD): **{pc['macro_recall_headline']}** over "
              f"{', '.join(pc['headline_classes_scored']) or '—'}; secondary (H, PD): "
              f"**{pc['macro_recall_secondary_H_PD']}**"
              + (f" — baseline {baseline['per_class']['macro_recall_headline']} / "
                 f"{baseline['per_class']['macro_recall_secondary_H_PD']}" if baseline else "")]
    return lines


def confusion_table(conf: dict) -> list[str]:
    cols = sorted({p for d in conf.values() for p in d})
    lines = ["| label \\ pred | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    for t in sorted(conf):
        lines.append(f"| {t} | " + " | ".join(str(conf[t].get(c, 0)) for c in cols) + " |")
    return lines


_ = HEADLINE
