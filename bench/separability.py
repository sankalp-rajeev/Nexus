"""Amendment 1 gate: can a trivial single-field rule separate CONTEXT_BLEED? (DEV only)

    python -m bench.separability

Every rule sees only bench.detector_view output. Scored two ways: per the
pre-registered rule (OTHER_FAILURE excluded) and against every other dev trace.
If any rule reaches precision >= 0.95 AND recall >= 0.95, the headline falls
back to the secondary macro (HALLUCINATION + PLAN_DRIFT).
"""

from __future__ import annotations

import json
import os
import re
import sys
from itertools import combinations

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _p in (REPO, os.path.join(REPO, "sdk")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bench.detector_view import detector_view_dict  # noqa: E402
from bench.scoring import load_rows, load_traces, prop  # noqa: E402
from bench.world import _CITIES, _FIRST, _LAST, TIERS  # noqa: E402
from services.common.results import provenance, write_result  # noqa: E402

GATE = 0.95
_NAME = re.compile(r"\b(" + "|".join(_FIRST) + r") (" + "|".join(_LAST) + r")\b")


def _reads(view):
    out = []
    for s in view["spans"]:
        if s["span_type"] == "memory_read" and s.get("output") and not s.get("error_type"):
            try:
                out.append([r.get("note", "") for r in json.loads(s["output"])])
            except json.JSONDecodeError:
                pass
    return out


def features(view) -> dict[str, float]:
    reads = _reads(view)
    notes = [n for r in reads for n in r]
    blob = " ".join(notes)
    keys = [n.split(":", 1)[0] for n in notes if ":" in n]
    max_rec = max((len(r) for r in reads), default=0)
    return {
        "reads_memory": float(bool(reads)),
        "n_memory_reads": float(len(reads)),
        "max_records": float(max_rec),
        "memory_chars": float(len(blob)),
        "person_names": float(len(set(_NAME.findall(blob)))),
        "account_tier_records": float(sum(n.startswith("Account tier:") for n in notes)
                                      / max(len(reads), 1)),
        "distinct_tiers": float(len({t for t in TIERS if t in blob})),
        "distinct_cities": float(len({c for c in _CITIES if c in blob})),
        "duplicate_key": float(len(keys) != len(set(keys))),
        "team_notes": float(sum(n.startswith("Team note:") for n in notes)),
    }


def _score(rows, preds, exclude_other: bool):
    rs = [r for r in rows if not (exclude_other and r["label"] == "OTHER_FAILURE")]
    tp = sum(1 for r in rs if r["label"] == "CONTEXT_BLEED" and preds[r["trace_id"]])
    fp = sum(1 for r in rs if r["label"] != "CONTEXT_BLEED" and preds[r["trace_id"]])
    fn = sum(1 for r in rs if r["label"] == "CONTEXT_BLEED" and not preds[r["trace_id"]])
    return prop(tp, tp + fp), prop(tp, tp + fn)


def main() -> int:
    rows = load_rows("dev")
    traces = load_traces({r["trace_id"] for r in rows})
    feats = {r["trace_id"]: features(detector_view_dict(traces[r["trace_id"]])) for r in rows}
    names = list(next(iter(feats.values())))
    results = []
    for f in names:
        values = sorted({v[f] for v in feats.values()})
        best = None
        for thr in values:  # rule: feature >= thr (best threshold reported, dev only)
            preds = {tid: v[f] >= thr and v[f] > 0 for tid, v in feats.items()}
            p, r = _score(rows, preds, exclude_other=True)
            if p["value"] is None:
                continue
            f1 = 2 * p["value"] * r["value"] / (p["value"] + r["value"]) if p["value"] + r["value"] else 0
            if best is None or f1 > best["f1"]:
                pa, ra = _score(rows, preds, exclude_other=False)
                best = {"rule": f"{f} >= {thr:g}", "f1": round(f1, 4), "precision": p, "recall": r,
                        "precision_vs_all": pa, "recall_vs_all": ra}
        if best:
            results.append(best)
    # Fixed rules named in the amendment, reported even if not the best threshold.
    fixed = {"record count > 1": lambda v: v["max_records"] > 1,
             "a person's name appears": lambda v: v["person_names"] >= 1,
             "two or more person names": lambda v: v["person_names"] >= 2}
    for label, fn in fixed.items():
        preds = {tid: fn(v) for tid, v in feats.items()}
        p, r = _score(rows, preds, True)
        pa, ra = _score(rows, preds, False)
        results.append({"rule": label, "precision": p, "recall": r,
                        "precision_vs_all": pa, "recall_vs_all": ra, "fixed": True})
    # Best pair (AND) of best single thresholds, as a check on "single-field" robustness.
    singles = [x for x in results if not x.get("fixed")]
    pair_best = None
    for a, b in combinations(singles, 2):
        fa, ta = a["rule"].split(" >= ")
        fb, tb = b["rule"].split(" >= ")
        preds = {tid: v[fa] >= float(ta) and v[fb] >= float(tb) for tid, v in feats.items()}
        p, r = _score(rows, preds, True)
        if p["value"] is not None and (pair_best is None or
                                       (p["value"] + r["value"]) > pair_best["sum"]):
            pair_best = {"rule": f"{a['rule']} AND {b['rule']}", "precision": p, "recall": r,
                         "sum": p["value"] + r["value"]}
    tripped = [x["rule"] for x in results
               if (x["precision"]["value"] or 0) >= GATE and (x["recall"]["value"] or 0) >= GATE]
    payload = {"split": "dev", "gate": GATE, "rules": results, "best_pair_and": pair_best,
               "gate_tripped_by": tripped}
    summary = (f"CONTEXT_BLEED separability (dev): gate {'TRIPPED by ' + ', '.join(tripped) if tripped else 'not tripped'}; "
               "best single rule " + max(results, key=lambda x: x.get("f1", 0))["rule"])
    write_result("A1-separability-dev", "cb_separability_dev.json", payload,
                 provenance_info=provenance(provider="none (no LLM)", model="trivial rules",
                                            mock=False, seed=None), summary=summary)
    print(f"{'rule':<34} {'P (excl OTHER)':<26} {'R':<26} P vs all")
    for x in results:
        p, r, pa = x["precision"], x["recall"], x["precision_vs_all"]
        print(f"{x['rule']:<34} {p['value']!s:<6}({p['k']}/{p['n']})"
              f"{'':<12} {r['value']!s:<6}({r['k']}/{r['n']}){'':<12} {pa['value']}")
    print("best AND pair:", pair_best["rule"] if pair_best else None,
          pair_best and (pair_best["precision"]["value"], pair_best["recall"]["value"]))
    print("GATE TRIPPED BY:", tripped or "none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
