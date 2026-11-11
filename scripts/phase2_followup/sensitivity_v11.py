"""Phase 2 sensitivity: v1.1 labels, from STORED predictions only (no detector run).

    python -m scripts.phase2_followup.sensitivity_v11

TEST: per-trace predictions were not persisted (DECISIONS D45). The v1.1
metrics are rebuilt from the stored v1 confusion matrices by moving each
relabelled row from its v1 to its v1.1 label row at its *stored-determined*
prediction. A row's prediction is determined if it is in the stored
year-tolerance id list (all predicted HALLUCINATION), or if its model's stored
confusion row for its v1 label has a single predicted class. Any undetermined
row aborts the exact computation.
DEV: re-scored from results/phase2_dev_predictions.json.
"""

from __future__ import annotations

import copy
import csv
import io
import json
import os
import subprocess
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for _p in (REPO, os.path.join(REPO, "sdk")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bench.scoring import CLASSES, EXCLUDED, HEADLINE, SECONDARY, prop  # noqa: E402
from scripts.phase2 import evalkit as ek  # noqa: E402
from services.common.results import provenance, write_result  # noqa: E402

V1_REF = "phase2-test-scored"


def _labels(text: str) -> dict:
    return {r["trace_id"]: r for r in csv.DictReader(io.StringIO(text))}


def metrics_from_confusion(conf: dict) -> dict:
    """Same rules as bench.scoring.score, computed from a confusion matrix."""
    def cell(t, p):
        return conf.get(t, {}).get(p, 0)
    labels = [t for t in conf if t not in EXCLUDED]
    preds = {p for d in conf.values() for p in d}
    pc = {}
    for c in CLASSES:
        tp = cell(c, c)
        fp = sum(cell(t, c) for t in labels if t != c)
        fn = sum(cell(c, p) for p in preds if p != c)
        pc[c] = {"support": tp + fn, "recall": prop(tp, tp + fn), "precision": prop(tp, tp + fp)}
    rec = [pc[c]["recall"]["value"] for c in HEADLINE if pc[c]["support"]]
    sec = [pc[c]["recall"]["value"] for c in SECONDARY if pc[c]["support"]]
    pc["macro_recall_headline"] = round(sum(rec) / len(rec), 4) if rec else None
    pc["macro_recall_secondary_H_PD"] = round(sum(sec) / len(sec), 4) if sec else None
    for c in CLASSES:
        pc[c]["f1"] = ek.f1(pc[c])
    kept = [t for t in conf if t != "RUN_ERROR"]
    tp = sum(cell(t, p) for t in kept if t != "NORMAL" for p in preds if p != "NORMAL")
    fp = sum(cell("NORMAL", p) for p in preds if p != "NORMAL")
    fn = sum(cell(t, "NORMAL") for t in kept if t != "NORMAL")
    n_norm = sum(conf.get("NORMAL", {}).values())
    return {"per_class": pc, "any_failure": {"recall": prop(tp, tp + fn), "precision": prop(tp, tp + fp)},
            "false_alerts_per_1000_normal": round(1000 * fp / n_norm, 1) if n_norm else None,
            "false_alerts": prop(fp, n_norm)}


def test_v11() -> dict:
    with open(os.path.join(REPO, "results", "detect_test.json"), encoding="utf-8") as fh:
        stored = json.load(fh)["results"]
    v1 = _labels(subprocess.check_output(["git", "show", f"{V1_REF}:data/nexusbench/labels.csv"],
                                         cwd=REPO, text=True, encoding="utf-8"))
    with open(os.path.join(REPO, "data", "nexusbench", "labels.csv"), encoding="utf-8") as fh:
        v11 = _labels(fh.read())
    sens = set(stored["sensitivity_year_tolerance"]["trace_ids"])
    changed = [t for t, r in v1.items() if r["split"] == "test" and r["label"] != v11[t]["label"]]
    out = {}
    for scope, conf0 in [("all", stored["pipeline"]["all"]["confusion"]),
                         *[(m, b["confusion"]) for m, b in stored["pipeline"]["per_model"].items()]]:
        # Self-check: recomputing v1 from the stored confusion reproduces stored metrics.
        m1 = metrics_from_confusion(conf0)
        ref = (stored["pipeline"]["all"] if scope == "all" else stored["pipeline"]["per_model"][scope])
        assert m1["per_class"]["macro_recall_headline"] == ref["per_class"]["macro_recall_headline"]
        conf = copy.deepcopy(conf0)
        moved = []
        for t in changed:
            r1, r2 = v1[t], v11[t]
            if scope != "all" and r1["model"] != scope:
                continue
            if t in sens:
                pred, how = "HALLUCINATION", "stored year-tolerance id list"
            else:
                row = stored["pipeline"]["per_model"][r1["model"]]["confusion"].get(r1["label"], {})
                if len(row) != 1:
                    raise SystemExit(f"prediction of {t} not determined by stored data: {row}")
                pred, how = next(iter(row)), f"all {r1['model']} {r1['label']} rows predicted alike"
            conf[r1["label"]][pred] -= 1
            conf.setdefault(r2["label"], {}).setdefault(pred, 0)
            conf[r2["label"]][pred] += 1
            moved.append({"trace_id": t, "v1": r1["label"], "v1_1": r2["label"], "pred": pred,
                          "determined_by": how})
        out[scope] = {"v1": m1, "v1_1": metrics_from_confusion(conf), "moved": moved,
                      "confusion_v1_1": conf}
    return out


def dev_v11() -> dict:
    from bench.scoring import score

    with open(os.path.join(REPO, "results", "phase2_dev_predictions.json"), encoding="utf-8") as fh:
        per = json.load(fh)["predictions"]
    with open(os.path.join(REPO, "data", "nexusbench", "labels.csv"), encoding="utf-8") as fh:
        v11 = [r for r in csv.DictReader(fh) if r["split"] == "dev"]
    v1 = [{**r, "label": per[r["trace_id"]]["label_v1"]} for r in v11]
    preds = {t: p["pred"] for t, p in per.items()}
    res = {}
    for name, rows in (("v1", v1), ("v1_1", v11)):
        sc = score(rows, preds)
        block = {}
        for scope, b in [("all", sc["all"]), *sc["per_model"].items()]:
            for c in CLASSES:
                b["per_class"][c]["f1"] = ek.f1(b["per_class"][c])
            fa = ek.false_alerts_per_1000([r for r in rows if scope == "all" or r["model"] == scope],
                                          preds)
            block[scope] = {"per_class": b["per_class"], "any_failure": b["any_failure"],
                            "false_alerts_per_1000_normal": fa["per_1000"],
                            "false_alerts": {k: fa[k] for k in ("value", "k", "n",
                                                                "ci95_clopper_pearson")},
                            "confusion": b["confusion"]}
        res[name] = block
    return res


def main() -> int:
    t = test_v11()
    d = dev_v11()
    prov = provenance(provider="none (stored predictions)", model="frozen Phase 2 detectors",
                      mock=False, seed=None)
    ta, da = t["all"]["v1_1"]["per_class"], d["v1_1"]["all"]["per_class"]
    write_result("S-v1.1-test", "detect_test_v11_sensitivity.json", t, provenance_info=prov,
                 summary=f"SENSITIVITY (v1.1 labels, stored test predictions): headline "
                         f"{ta['macro_recall_headline']}; H P={ta['HALLUCINATION']['precision']['value']} "
                         f"R={ta['HALLUCINATION']['recall']['value']}; FA/1000 "
                         f"{t['all']['v1_1']['false_alerts_per_1000_normal']}")
    write_result("S-v1.1-dev", "detect_dev_v11_sensitivity.json", d, provenance_info=prov,
                 summary=f"SENSITIVITY (v1.1 labels, dev): headline {da['macro_recall_headline']}; "
                         f"H P={da['HALLUCINATION']['precision']['value']} "
                         f"R={da['HALLUCINATION']['recall']['value']}")
    for split, blocks in (("TEST", {"v1": t["all"]["v1"], "v1_1": t["all"]["v1_1"]}),
                          ("DEV", {"v1": d["v1"]["all"], "v1_1": d["v1_1"]["all"]})):
        print(f"== {split}")
        for c in CLASSES:
            a, b = blocks["v1"]["per_class"][c], blocks["v1_1"]["per_class"][c]
            print(f"  {c:<14} v1 P={a['precision']['value']} R={a['recall']['value']} | "
                  f"v1.1 P={b['precision']['value']} ({b['precision']['k']}/{b['precision']['n']}) "
                  f"R={b['recall']['value']} ({b['recall']['k']}/{b['recall']['n']})")
        for k in ("macro_recall_headline", "macro_recall_secondary_H_PD"):
            print(f"  {k}: v1 {blocks['v1']['per_class'][k]} | v1.1 {blocks['v1_1']['per_class'][k]}")
        print(f"  FA/1000 NORMAL: v1 {blocks['v1']['false_alerts_per_1000_normal']} | v1.1 "
              f"{blocks['v1_1']['false_alerts_per_1000_normal']}")
    for m in ("deepseek-flash", "qwen2.5:7b-instruct"):
        a, b = t[m]["v1"]["per_class"], t[m]["v1_1"]["per_class"]
        print(f"  TEST {m}: headline v1 {a['macro_recall_headline']} -> v1.1 {b['macro_recall_headline']}; "
              f"H P {a['HALLUCINATION']['precision']['value']} -> {b['HALLUCINATION']['precision']['value']}; "
              f"FA/1000 {t[m]['v1']['false_alerts_per_1000_normal']} -> {t[m]['v1_1']['false_alerts_per_1000_normal']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
