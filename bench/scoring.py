"""Pre-registered NexusBench scoring (see reports/phase2/preregistration.md).

* Per-class precision/recall with Clopper-Pearson 95% intervals.
* OTHER_FAILURE traces: excluded from per-class scoring (neither positive nor
  negative for any class); in the binary "any failure" view, flagging one as
  any failure is a true detection.
* Headline: macro recall over HALLUCINATION, CONTEXT_BLEED, PLAN_DRIFT.
* Rule-defined classes (LOOP_DETECTED, TOOL_MISFIRE) are reported, not headline.
* Every result also broken down per model.
* The TEST split is sealed: ``load_rows("test")`` raises unless ``unseal=True``,
  which only the one-time final scoring run may pass.
"""

from __future__ import annotations

import csv
import json
import os
from typing import Any

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA = os.path.join(REPO, "data", "nexusbench")

HEADLINE = ["HALLUCINATION", "CONTEXT_BLEED", "PLAN_DRIFT"]
SECONDARY = ["HALLUCINATION", "PLAN_DRIFT"]
RULE_DEFINED = ["TOOL_MISFIRE", "LOOP_DETECTED"]
CLASSES = HEADLINE + RULE_DEFINED
EXCLUDED = {"OTHER_FAILURE", "RUN_ERROR"}
TARGET_RECALL, TARGET_PRECISION = 0.80, 0.90


class SealedSplitError(RuntimeError):
    pass


def clopper_pearson(k: int, n: int, alpha: float = 0.05) -> tuple[float, float] | None:
    if n == 0:
        return None
    from scipy.stats import beta

    lo = 0.0 if k == 0 else float(beta.ppf(alpha / 2, k, n - k + 1))
    hi = 1.0 if k == n else float(beta.ppf(1 - alpha / 2, k + 1, n - k))
    return (round(lo, 4), round(hi, 4))


def prop(k: int, n: int) -> dict[str, Any]:
    return {"value": round(k / n, 4) if n else None, "k": k, "n": n,
            "ci95_clopper_pearson": clopper_pearson(k, n)}


def load_rows(split: str, *, unseal: bool = False) -> list[dict]:
    if split == "test" and not unseal:
        raise SealedSplitError("the NexusBench test split is sealed until the final, "
                               "pre-registered scoring run")
    with open(os.path.join(DATA, "labels.csv"), encoding="utf-8", newline="") as fh:
        return [r for r in csv.DictReader(fh) if r["split"] == split]


def load_traces(trace_ids: set[str]) -> dict[str, dict]:
    out = {}
    with open(os.path.join(DATA, "traces.jsonl"), encoding="utf-8") as fh:
        for line in fh:
            # cheap prefilter on the id before parsing the full line
            tid = line[line.index('"trace_id": "') + 13:].split('"', 1)[0]
            if tid in trace_ids:
                out[tid] = json.loads(line)
    return out


def _per_class(pairs: list[tuple[str, str]]) -> dict[str, Any]:
    """pairs = [(true_label, predicted_label)]; OTHER_FAILURE rows are dropped."""
    kept = [(t, p) for t, p in pairs if t not in EXCLUDED]
    res = {}
    for c in CLASSES:
        tp = sum(1 for t, p in kept if t == c and p == c)
        fp = sum(1 for t, p in kept if t != c and p == c)
        fn = sum(1 for t, p in kept if t == c and p != c)
        res[c] = {"support": tp + fn, "recall": prop(tp, tp + fn),
                  "precision": prop(tp, tp + fp),
                  "kind": "headline" if c in HEADLINE else "rule-defined"}
    recalls = [res[c]["recall"]["value"] for c in HEADLINE if res[c]["support"]]
    res["macro_recall_headline"] = round(sum(recalls) / len(recalls), 4) if recalls else None
    res["headline_classes_scored"] = [c for c in HEADLINE if res[c]["support"]]
    # Pre-registered secondary headline (preregistration.md §5): CONTEXT_BLEED's
    # structural signal coincides with its label by construction in NexusBench.
    sec = [res[c]["recall"]["value"] for c in SECONDARY if res[c]["support"]]
    res["macro_recall_secondary_H_PD"] = round(sum(sec) / len(sec), 4) if sec else None
    return res


def _any_failure(pairs: list[tuple[str, str]]) -> dict[str, Any]:
    kept = [(t, p) for t, p in pairs if t != "RUN_ERROR"]
    tp = sum(1 for t, p in kept if t != "NORMAL" and p != "NORMAL")
    fp = sum(1 for t, p in kept if t == "NORMAL" and p != "NORMAL")
    fn = sum(1 for t, p in kept if t != "NORMAL" and p == "NORMAL")
    other = [(t, p) for t, p in kept if t == "OTHER_FAILURE"]
    return {"recall": prop(tp, tp + fn), "precision": prop(tp, tp + fp),
            "other_failure_flagged": prop(sum(1 for _, p in other if p != "NORMAL"), len(other))}


def confusion(pairs: list[tuple[str, str]]) -> dict[str, dict[str, int]]:
    m: dict[str, dict[str, int]] = {}
    for t, p in pairs:
        m.setdefault(t, {}).setdefault(p, 0)
        m[t][p] += 1
    return m


def score(rows: list[dict], preds: dict[str, str]) -> dict[str, Any]:
    """rows: labels.csv rows; preds: trace_id -> predicted label."""
    def block(rs):
        pairs = [(r["label"], preds[r["trace_id"]]) for r in rs]
        return {"n": len(rs), "per_class": _per_class(pairs), "any_failure": _any_failure(pairs),
                "confusion": confusion(pairs)}
    out = {"all": block(rows), "per_model": {}}
    for m in sorted({r["model"] for r in rows}):
        out["per_model"][m] = block([r for r in rows if r["model"] == m])
    return out
