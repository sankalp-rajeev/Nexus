"""Phase 2 baseline: the shipped v3 classifier (rules + SVM) on NexusBench DEV.

    python -m bench.phase2_baseline

Runs the classifier exactly as shipped (data/classifier_model, no retraining,
no threshold change) on detector views of the DEV split only. Writes
results/detect_baseline_dev.json and reports/phase2/baseline_dev.md.
"""

from __future__ import annotations

import os
import sys
import time

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _p in (REPO, os.path.join(REPO, "sdk")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

from bench.detector_view import detector_view  # noqa: E402
from bench.scoring import CLASSES, HEADLINE, load_rows, load_traces, score  # noqa: E402
from services.common.results import provenance, report_header, write_result  # noqa: E402

MODEL_DESC = ("v3 classifier as shipped: rules + SVM over MiniLM embedding, PatchCore, "
              "io_divergence, NLI contradiction (data/classifier_model)")
RESULT_FILE = "detect_baseline_dev.json"
REPORT = os.path.join(REPO, "reports", "phase2", "baseline_dev.md")


def _fmt(p):
    if p["value"] is None:
        return "n/a"
    lo, hi = p["ci95_clopper_pearson"]
    return f"{p['value']:.3f} ({p['k']}/{p['n']}; {lo:.2f}-{hi:.2f})"


def main() -> int:
    from services.classifier.main import load_classifier

    rows = load_rows("dev")
    traces = load_traces({r["trace_id"] for r in rows})
    clf = load_classifier()
    t0 = time.time()
    preds = {}
    for r in rows:
        preds[r["trace_id"]] = clf.classify(detector_view(traces[r["trace_id"]])).failure_type.value
    elapsed = time.time() - t0
    res = score(rows, preds)
    res["seconds"] = round(elapsed, 1)
    res["split"] = "dev"
    a = res["all"]["per_class"]
    summary = (f"DEV baseline (shipped SVM): headline macro recall {a['macro_recall_headline']}; "
               + ", ".join(f"{c} R={a[c]['recall']['value']} P={a[c]['precision']['value']}"
                           for c in CLASSES))
    prov = provenance(provider="none (no LLM)", model=MODEL_DESC, mock=False, seed=None)
    write_result("D-baseline-dev", RESULT_FILE, res, provenance_info=prov, summary=summary)

    lines = ["# Phase 2 baseline — shipped classifier on NexusBench DEV", "",
             *report_header(provider="none (no LLM)", model=MODEL_DESC, mock=False,
                            generator="python -m bench.phase2_baseline",
                            result_file=f"results/{RESULT_FILE}"),
             "", f"- Split: **dev only** ({res['all']['n']} traces). Test is sealed.",
             "- Input: `bench.detector_view` (the pre-registered detector contract).",
             "- Operating point: as shipped (no retraining, no threshold change).",
             "- Intervals: Clopper-Pearson 95%. OTHER_FAILURE excluded from per-class rows.", ""]
    for scope, block in [("All models", res["all"]), *[(m, b) for m, b in res["per_model"].items()]]:
        pc = block["per_class"]
        af = block["any_failure"]
        lines += [f"## {scope} (n={block['n']})", "",
                  f"Headline macro recall (H, CB, PD): **{pc['macro_recall_headline']}** "
                  f"over {', '.join(pc['headline_classes_scored']) or 'no classes'}; "
                  f"secondary macro (H, PD): **{pc['macro_recall_secondary_H_PD']}**", "",
                  "| Class | Kind | Support | Recall | Precision |", "|---|---|---|---|---|"]
        for c in CLASSES:
            d = pc[c]
            lines.append(f"| {c} | {d['kind']} | {d['support']} | {_fmt(d['recall'])} | "
                         f"{_fmt(d['precision'])} |")
        lines += ["", f"Any failure (OTHER_FAILURE counts as a failure): recall "
                  f"{_fmt(af['recall'])}, precision {_fmt(af['precision'])}; OTHER_FAILURE "
                  f"flagged {_fmt(af['other_failure_flagged'])}.", ""]
    conf = res["all"]["confusion"]
    preds_seen = sorted({p for d in conf.values() for p in d})
    lines += ["## Confusion (all models; rows = label, cols = prediction)", "",
              "| label \\ pred | " + " | ".join(preds_seen) + " |",
              "|---|" + "---|" * len(preds_seen)]
    for t in sorted(conf):
        lines.append(f"| {t} | " + " | ".join(str(conf[t].get(p, 0)) for p in preds_seen) + " |")
    lines.append("")
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))
    print("\n".join(lines))
    _ = HEADLINE
    return 0


if __name__ == "__main__":
    sys.exit(main())
