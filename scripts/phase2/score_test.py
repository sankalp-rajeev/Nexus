"""Phase 2 ONE-TIME test scoring with the frozen detectors (pre-registration §3.6).

    python -m scripts.phase2.score_test

Refuses to run unless the tag phase2-detectors-frozen exists, the detector code,
thresholds and evaluation code are unchanged since that tag, and no test result
exists yet. Writes D1 results/detect_test.json, D2 results/detect_vs_baseline.json,
D4 results/detect_external.json, D5 results/detect_false_alerts.json,
D6 results/detect_latency.json and reports/phase2/test_report.md.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for _p in (REPO, os.path.join(REPO, "sdk")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

FROZEN_TAG = "phase2-detectors-frozen"
FROZEN_PATHS = ["services/detectors", "scripts/phase2", "bench", "data/nexusbench"]
D1 = os.path.join(REPO, "results", "detect_test.json")


def _guard() -> str:
    def git(*a):
        return subprocess.run(["git", *a], cwd=REPO, capture_output=True, text=True)
    if git("rev-parse", "-q", "--verify", f"refs/tags/{FROZEN_TAG}").returncode != 0:
        sys.exit(f"refusing: tag {FROZEN_TAG} does not exist")
    diff = git("diff", "--name-only", FROZEN_TAG, "--", *FROZEN_PATHS).stdout.strip()
    if diff:
        sys.exit(f"refusing: frozen paths changed since {FROZEN_TAG}:\n{diff}")
    if os.path.exists(D1):
        sys.exit("refusing: results/detect_test.json exists; the test split is scored once")
    return git("rev-parse", "--short", "HEAD").stdout.strip()


def main() -> int:
    head = _guard()
    from nexus_agent.models import CompleteTrace

    from bench.scoring import load_rows, load_traces, prop
    from scripts.phase2 import evalkit as ek
    from scripts.phase2.tune_dev import sensitivity_year_tolerance
    from services.classifier.main import load_classifier
    from services.common.results import provenance, report_header, write_result
    from services.detectors import judge, pipeline
    from services.detectors.hallucination import NLI_MODEL

    th = pipeline.load_thresholds()
    rows = load_rows("test", unseal=True)  # the one and only unsealing
    traces = load_traces({r["trace_id"] for r in rows})
    views = ek.views_for(rows, traces)
    pipeline.compute_scores(next(iter(views.values())))  # warm model (not timed)
    scores = ek.compute_all(views)
    preds = {t: pipeline.label(s, th) for t, s in scores.items()}
    res = ek.full_report(rows, preds)
    lat = ek.latency(scores)

    jud = ek.judge_all(views)
    preds_j = {}
    for t, s in scores.items():
        f = pipeline.fired(s, th)
        f["HALLUCINATION"] = bool(jud[t])
        preds_j[t] = next((c for c in pipeline.ORDER if f[c]), "NORMAL")
    res_j = ek.full_report(rows, preds_j)

    ref_flags = {}
    for t, v in views.items():
        reads = [s for s in v.spans if s.span_type.value == "memory_read" and s.output
                 and not s.error_type]
        ref_flags[t] = any(sum(1 for r in json.loads(s.output)
                               if str(r.get("note", "")).startswith("Account tier:")) >= 2
                           for s in reads)
    ref_p, ref_r = ek.class_pr(rows, ref_flags, "CONTEXT_BLEED")
    sens = sensitivity_year_tolerance(rows)

    clf = load_classifier()
    base_preds = {t: clf.classify(v).failure_type.value for t, v in views.items()}
    base = ek.full_report(rows, base_preds)

    # D4: external real-world traces, same frozen detectors, no NexusBench view needed.
    with open(os.path.join(REPO, "tests", "fixtures", "master_traces.json"), encoding="utf-8") as fh:
        md = json.load(fh)
    ext: dict = {}
    for src in ("halueval", "toolbench"):
        items = [(CompleteTrace.model_validate(t), lab) for t, lab in zip(md["traces"], md["labels"])
                 if t.get("source") == src]
        ep = [(lab, pipeline.label(pipeline.compute_scores(t), th)) for t, lab in items]
        tp = sum(1 for lab, p in ep if lab != "NORMAL" and p != "NORMAL")
        fp = sum(1 for lab, p in ep if lab == "NORMAL" and p != "NORMAL")
        fn = sum(1 for lab, p in ep if lab != "NORMAL" and p == "NORMAL")
        cls = "HALLUCINATION" if src == "halueval" else "TOOL_MISFIRE"
        ctp = sum(1 for lab, p in ep if lab == cls and p == cls)
        cfp = sum(1 for lab, p in ep if lab != cls and p == cls)
        cfn = sum(1 for lab, p in ep if lab == cls and p != cls)
        ext[src] = {"n": len(ep), "binary": {"precision": prop(tp, tp + fp), "recall": prop(tp, tp + fn)},
                    cls: {"precision": prop(ctp, ctp + cfp), "recall": prop(ctp, ctp + cfn)},
                    "v3_baseline_binary": {"halueval": {"precision": 1.0, "recall": 0.033},
                                           "toolbench": {"precision": 1.0, "recall": 1.0}}[src]}

    # D6: SDK overhead per instrumented call (existing benchmark).
    out = subprocess.run([sys.executable, os.path.join(REPO, "examples", "raw_llm_call",
                                                       "benchmark_overhead.py")],
                         capture_output=True, text=True, cwd=REPO).stdout
    m = re.search(r"overhead\s*:\s*([\d.]+) ms/call", out)
    sdk_ms = float(m.group(1)) if m else None

    prov = provenance(provider="local NLI + rules", model=NLI_MODEL, mock=False, seed=None)
    a, b = res["all"]["per_class"], base["all"]["per_class"]
    write_result("D1", "detect_test.json",
                 {"split": "test", "scored_at_commit": head, "frozen_tag": FROZEN_TAG,
                  "thresholds": th, "pipeline": res, "judge_variant": res_j,
                  "cb_reference_rule": {"precision": ref_p, "recall": ref_r},
                  "sensitivity_year_tolerance": {
                      "trace_ids": sens,
                      "flagged_as_hallucination": sum(1 for t in sens if preds[t] == "HALLUCINATION")},
                  "judge_spend_usd_cumulative": judge.spent_usd()},
                 provenance_info=prov,
                 summary=f"TEST (once): headline macro recall {a['macro_recall_headline']}, secondary "
                         f"{a['macro_recall_secondary_H_PD']}; H P={a['HALLUCINATION']['precision']['value']} "
                         f"R={a['HALLUCINATION']['recall']['value']}; CB P={a['CONTEXT_BLEED']['precision']['value']} "
                         f"R={a['CONTEXT_BLEED']['recall']['value']}; PD P={a['PLAN_DRIFT']['precision']['value']} "
                         f"R={a['PLAN_DRIFT']['recall']['value']}")
    write_result("D2", "detect_vs_baseline.json",
                 {"split": "test", "detectors": res["all"]["per_class"], "baseline_svm": b,
                  "baseline_per_model": {m: v["per_class"] for m, v in base["per_model"].items()}},
                 provenance_info=prov,
                 summary=f"TEST headline macro recall {a['macro_recall_headline']} vs SVM baseline "
                         f"{b['macro_recall_headline']} (secondary {a['macro_recall_secondary_H_PD']} vs "
                         f"{b['macro_recall_secondary_H_PD']})")
    write_result("D4", "detect_external.json", ext, provenance_info=prov,
                 summary="external: HaluEval binary P={} R={}; ToolBench binary P={} R={}".format(
                     ext["halueval"]["binary"]["precision"]["value"],
                     ext["halueval"]["binary"]["recall"]["value"],
                     ext["toolbench"]["binary"]["precision"]["value"],
                     ext["toolbench"]["binary"]["recall"]["value"]))
    write_result("D5", "detect_false_alerts.json",
                 {"split": "test", "detectors": res["false_alerts"], "baseline_svm": base["false_alerts"]},
                 provenance_info=prov,
                 summary=f"TEST false alerts per 1,000 NORMAL: {res['false_alerts']['all']['per_1000']} "
                         f"(baseline {base['false_alerts']['all']['per_1000']})")
    write_result("D6", "detect_latency.json", {"detector_per_trace_ms": lat, "sdk_overhead_ms_per_call": sdk_ms},
                 provenance_info=prov,
                 summary=f"detector latency p50 {lat['p50_ms']} ms, p95 {lat['p95_ms']} ms (CPU); "
                         f"SDK overhead {sdk_ms} ms/call")

    L = ["# Phase 2 — TEST results (scored once, frozen detectors)", "",
         *report_header(provider="local NLI + rules; Gemini judge variant only", model=NLI_MODEL,
                        mock=False, generator="python -m scripts.phase2.score_test",
                        result_file="results/detect_test.json"),
         "", f"Test split ({len(rows)} traces), scored once at `{head}` with the code frozen at tag "
         f"`{FROZEN_TAG}`.", "", "## All models (vs shipped-SVM baseline)", "",
         *ek.class_table(res["all"], base["all"]), ""]
    for mname, block in res["per_model"].items():
        L += [f"## {mname}", "", *ek.class_table(block, base["per_model"].get(mname)), ""]
    L += ["## Confusion (all models)", "", *ek.confusion_table(res["all"]["confusion"]), "",
          "## CONTEXT_BLEED vs the pre-registered reference rule", "",
          f"- reference: P {ek._fmt(ref_p)}, R {ek._fmt(ref_r)}",
          f"- detector: P {ek._fmt(a['CONTEXT_BLEED']['precision'])}, R {ek._fmt(a['CONTEXT_BLEED']['recall'])}",
          "", "## Variant: Gemini judge for HALLUCINATION (separate)", "", *ek.class_table(res_j["all"]), "",
          "## D5 false alerts per 1,000 NORMAL", "",
          f"- detectors {res['false_alerts']['all']['per_1000']} "
          f"({res['false_alerts']['all']['k']}/{res['false_alerts']['all']['n']}); "
          f"baseline {base['false_alerts']['all']['per_1000']}", "",
          "## D4 external (HaluEval, ToolBench)", ""]
    for src, e in ext.items():
        cls = "HALLUCINATION" if src == "halueval" else "TOOL_MISFIRE"
        L.append(f"- {src} (n={e['n']}): binary P {ek._fmt(e['binary']['precision'])}, "
                 f"R {ek._fmt(e['binary']['recall'])}; {cls} R {ek._fmt(e[cls]['recall'])}; "
                 f"v3 baseline P/R {e['v3_baseline_binary']['precision']}/{e['v3_baseline_binary']['recall']}")
    L += ["", "## D6 latency", "", f"- detectors per trace (CPU): p50 {lat['p50_ms']} ms, "
          f"p95 {lat['p95_ms']} ms, max {lat['max_ms']} ms", f"- SDK overhead: {sdk_ms} ms per call", "",
          "## Registered sensitivity analysis (founding-year tolerance)", "",
          f"- {len(sens)} test rows meet the criterion; detector flags "
          f"{sum(1 for t in sens if preds[t] == 'HALLUCINATION')} of them as HALLUCINATION.", ""]
    path = os.path.join(REPO, "reports", "phase2", "test_report.md")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(L))
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
