"""Phase 2: tune detector operating points on DEV and write the dev report.

    python -m scripts.phase2.tune_dev

Writes services/detectors/thresholds.json, results/detect_pr_dev.json (D3),
results/detect_dev.json and reports/phase2/detectors_dev.md. Dev only.
"""

from __future__ import annotations

import json
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for _p in (REPO, os.path.join(REPO, "sdk")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bench.scoring import load_rows, load_traces  # noqa: E402
from scripts.phase2 import evalkit as ek  # noqa: E402
from services.common.results import provenance, report_header, write_result  # noqa: E402
from services.detectors import drift, judge, pipeline  # noqa: E402
from services.detectors.hallucination import NLI_MODEL  # noqa: E402

REPORT = os.path.join(REPO, "reports", "phase2", "detectors_dev.md")


def sensitivity_year_tolerance(rows) -> list[str]:
    """Registered before the freeze: QA founding-year rows that passed the checker
    with a number that is not exactly the gold year (the +/-1.1% tolerance admits
    +/-22 years). Mechanical criterion; reported, never used for tuning."""
    from bench.tasks import build_tasks
    from bench.world import build_world
    import re

    tasks = {t.task_id: t for t in build_tasks(build_world())}
    out = []
    for r in rows:
        t = tasks[r["task_id"]]
        if r["checker_pass"] == "True" and t.family == "qa" and t.attr == "founded":
            nums = [float(m.replace(",", "").rstrip(".")) for m in
                    re.findall(r"-?\d[\d,]*\.?\d*", r["final_answer"])]
            if not any(abs(x - float(t.gold)) < 1e-6 for x in nums):
                out.append(r["trace_id"])
    return out


def curves(rows, scores):
    out = {}
    hs = sorted({round(s.halluc, 4) for s in scores.values() if s.halluc is not None})
    out["HALLUCINATION"] = []
    for thr in hs:
        flags = {t: s.halluc is not None and s.halluc >= thr for t, s in scores.items()}
        p, r = ek.class_pr(rows, flags, "HALLUCINATION")
        out["HALLUCINATION"].append({"threshold": thr, "precision": p, "recall": r})
    bs = sorted({s.bleed for s in scores.values() if s.bleed})
    out["CONTEXT_BLEED"] = []
    for thr in bs:
        flags = {t: s.bleed is not None and s.bleed >= thr for t, s in scores.items()}
        p, r = ek.class_pr(rows, flags, "CONTEXT_BLEED")
        out["CONTEXT_BLEED"].append({"threshold": thr, "precision": p, "recall": r})
    out["PLAN_DRIFT"] = []
    for v in drift.VARIANTS:
        flags = {t: s.drift[v] for t, s in scores.items()}
        p, r = ek.class_pr(rows, flags, "PLAN_DRIFT")
        out["PLAN_DRIFT"].append({"variant": v, "precision": p, "recall": r})
    return out


def main() -> int:
    rows = load_rows("dev")
    traces = load_traces({r["trace_id"] for r in rows})
    views = ek.views_for(rows, traces)
    pipeline.compute_scores(next(iter(views.values())))  # warm the NLI model (not timed)
    scores = ek.compute_all(views)

    pr = curves(rows, scores)
    chosen = {c: ek.choose(pts) for c, pts in pr.items()}
    th = {
        "HALLUCINATION": {"threshold": chosen["HALLUCINATION"]["threshold"],
                          "detector": f"claim-level NLI ({NLI_MODEL})"},
        "CONTEXT_BLEED": {"threshold": chosen["CONTEXT_BLEED"]["threshold"],
                          "detector": "profile-consistency conflicts"},
        "PLAN_DRIFT": {"variant": chosen["PLAN_DRIFT"]["variant"],
                       "detector": "plan alignment + identifier provenance"},
        "rule": "max dev recall s.t. dev precision >= 0.90, else max dev precision",
        "meets_precision_floor": {c: chosen[c]["meets_precision_floor"] for c in chosen},
    }
    with open(pipeline.THRESHOLDS_PATH, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(th, fh, indent=2)
        fh.write("\n")

    preds = {t: pipeline.label(s, th) for t, s in scores.items()}
    res = ek.full_report(rows, preds)
    res["latency"] = ek.latency(scores)

    # Separate variant: Gemini judge replaces the NLI hallucination detector.
    jud = ek.judge_all(views)
    preds_j = {}
    for t, s in scores.items():
        f = pipeline.fired(s, th)
        f["HALLUCINATION"] = bool(jud[t])
        preds_j[t] = next((c for c in pipeline.ORDER if f[c]), "NORMAL")
    res_j = ek.full_report(rows, preds_j)

    # Pre-registered trivial reference for CONTEXT_BLEED (Amendment 1).
    ref_flags = {}
    for t, v in views.items():
        reads = [s for s in v.spans if s.span_type.value == "memory_read" and s.output
                 and not s.error_type]
        ref_flags[t] = any(sum(1 for r in json.loads(s.output)
                               if str(r.get("note", "")).startswith("Account tier:")) >= 2
                           for s in reads)
    ref_p, ref_r = ek.class_pr(rows, ref_flags, "CONTEXT_BLEED")

    with open(os.path.join(REPO, "results", "detect_baseline_dev.json"), encoding="utf-8") as fh:
        base = json.load(fh)["results"]
    sens = sensitivity_year_tolerance(rows)
    spent = judge.spent_usd()

    write_result("D3", "detect_pr_dev.json", {"split": "dev", "curves": pr, "chosen": chosen},
                 provenance_info=provenance(provider="local NLI + rules", model=NLI_MODEL,
                                            mock=False, seed=None),
                 summary="dev PR curves / operating points: " + ", ".join(
                     f"{c} P={chosen[c]['precision']['value']} R={chosen[c]['recall']['value']}"
                     for c in chosen))
    a = res["all"]["per_class"]
    write_result("D-dev", "detect_dev.json",
                 {"split": "dev", "thresholds": th, "pipeline": res, "judge_variant": res_j,
                  "cb_reference_rule": {"precision": ref_p, "recall": ref_r},
                  "sensitivity_year_tolerance_trace_ids": sens, "judge_spend_usd": spent},
                 provenance_info=provenance(provider="local NLI + rules (+gemini judge variant)",
                                            model=f"{NLI_MODEL}; judge {judge.JUDGE_MODEL}",
                                            mock=False, seed=None),
                 summary=f"DEV detectors: headline macro {a['macro_recall_headline']}, secondary "
                         f"{a['macro_recall_secondary_H_PD']}; FA/1000 NORMAL "
                         f"{res['false_alerts']['all']['per_1000']}")

    L = ["# Phase 2 detectors — DEV report (tuning split)", "",
         *report_header(provider="local NLI + rules; Gemini judge variant only",
                        model=f"{NLI_MODEL}; judge {judge.JUDGE_MODEL}", mock=False,
                        generator="python -m scripts.phase2.tune_dev",
                        result_file="results/detect_dev.json"),
         "", f"Dev only ({len(rows)} traces). Test is sealed. Operating points: "
         "max dev recall subject to dev precision >= 0.90, else max dev precision.", "",
         "## Operating points (frozen into services/detectors/thresholds.json)", "",
         "| Class | Operating point | Dev P | Dev R | Meets P ≥ 0.90 |", "|---|---|---|---|---|"]
    for c in ("HALLUCINATION", "CONTEXT_BLEED", "PLAN_DRIFT"):
        ch = chosen[c]
        op = ch.get("variant") or f"score ≥ {ch['threshold']}"
        L.append(f"| {c} | {op} | {ek._fmt(ch['precision'])} | {ek._fmt(ch['recall'])} | "
                 f"{'yes' if ch['meets_precision_floor'] else '**no**'} |")
    L += ["", "## Pipeline, all models (vs shipped-SVM baseline)", "",
          *ek.class_table(res["all"], base["all"]), ""]
    for m, block in res["per_model"].items():
        L += [f"## Pipeline, {m}", "", *ek.class_table(block, base["per_model"].get(m)), ""]
    fa = res["false_alerts"]
    L += ["## False alerts per 1,000 NORMAL traces", "",
          f"- all: **{fa['all']['per_1000']}** ({fa['all']['k']}/{fa['all']['n']})",
          *[f"- {m}: {v['per_1000']} ({v['k']}/{v['n']})" for m, v in fa["per_model"].items()],
          "", "## Confusion (all models)", "", *ek.confusion_table(res["all"]["confusion"]), "",
          "## CONTEXT_BLEED vs the pre-registered reference rule", "",
          f"- reference (≥ 2 'Account tier:' records): P {ek._fmt(ref_p)}, R {ek._fmt(ref_r)}",
          f"- detector: P {ek._fmt(a['CONTEXT_BLEED']['precision'])}, "
          f"R {ek._fmt(a['CONTEXT_BLEED']['recall'])}", "",
          "## Variant: Gemini judge in place of the NLI hallucination detector (separate)", "",
          *ek.class_table(res_j["all"]), "",
          "## Latency (all detectors per trace, CPU, model warm)", "",
          f"- p50 {res['latency']['p50_ms']} ms, p95 {res['latency']['p95_ms']} ms, "
          f"max {res['latency']['max_ms']} ms (n={res['latency']['n']})", "",
          "## Spend", "", f"- Gemini judge (dev, cumulative ledger): ${spent:.4f}. "
          "NLI and rules are local and free.", "",
          "## Registered sensitivity analysis (not used for tuning)", "",
          f"- {len(sens)} dev rows are QA founding-year runs that passed the checker with a "
          "non-exact year (the ±1.1% numeric tolerance admits ±22 years). They are labelled "
          "NORMAL but are wrong answers. The HALLUCINATION detector flags "
          f"{sum(1 for t in sens if preds[t] == 'HALLUCINATION')} of them. Labels are not changed "
          "in this phase; the same mechanical criterion will be applied to test.", ""]
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(L))
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    sys.exit(main())
