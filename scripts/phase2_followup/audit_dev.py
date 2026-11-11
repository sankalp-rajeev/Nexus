"""Phase 2 follow-up audits on DEV only (frozen detector code, no tuning).

    python -m scripts.phase2_followup.audit_dev

1. Judge-NLI independence: per-trace agreement on dev where either method ran.
2. Entity-filter artifact: the entity-presence rule ALONE as a HALLUCINATION detector.
Also persists per-trace dev predictions (results/phase2_dev_predictions.json),
which the original Phase 2 run did not store.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for _p in (REPO, os.path.join(REPO, "sdk")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bench.scoring import load_rows, load_traces  # noqa: E402
from scripts.phase2 import evalkit as ek  # noqa: E402
from services.common.results import provenance, write_result  # noqa: E402
from services.detectors import judge, pipeline  # noqa: E402
from services.detectors.hallucination import (  # noqa: E402
    NLI_MODEL, claims, entities, premise_units, retrieved_context)


def entity_rule(view) -> bool | None:
    """Flag iff some factual claim names an entity that no premise unit contains.
    None when the NLI path would not run (no premises or no claims)."""
    prem = retrieved_context(view)
    cl = claims(view.final_output or "", view.root_input or "")
    if not prem or not cl:
        return None
    units = [u.lower() for u in premise_units(prem)]
    for c in cl:
        ents = entities(c)
        if ents and not any(all(e in u for e in ents) for u in units):
            return True
    return False


def main() -> int:
    th = pipeline.load_thresholds()
    rows = load_rows("dev")
    traces = load_traces({r["trace_id"] for r in rows})
    views = ek.views_for(rows, traces)
    pipeline.compute_scores(next(iter(views.values())))
    scores = ek.compute_all(views)
    jud = ek.judge_all(views)  # cached responses: no new spend expected
    per = {}
    for r in rows:
        t, s, v = r["trace_id"], scores[r["trace_id"]], views[r["trace_id"]]
        nli_flag = s.halluc is not None and s.halluc >= th["HALLUCINATION"]["threshold"]
        per[t] = {"label_v1": r["label"], "model": r["model"],
                  "pred": pipeline.label(s, th), "nli_ran": s.halluc is not None,
                  "nli_score": s.halluc, "nli_flag": nli_flag,
                  "judge_ran": jud[t] is not None, "judge_flag": bool(jud[t]),
                  "entity_rule": entity_rule(v)}

    either = [p for p in per.values() if p["nli_ran"] or p["judge_ran"]]
    table = Counter((("ran" if p["nli_ran"] else "skip") + ("/flag" if p["nli_flag"] else "/clear"),
                     ("ran" if p["judge_ran"] else "skip") + ("/flag" if p["judge_flag"] else "/clear"))
                    for p in either)
    disagree = sum(1 for p in either if p["nli_flag"] != p["judge_flag"])
    audit = {
        "split": "dev",
        "code_paths": {
            "nli": "hallucination.score: retrieved_context -> claims (sentence+conjunction split, "
                   "hedge/meta/imperative filter) -> premise_units -> DeBERTa NLI -> entity gate "
                   "-> 1 - min_claim max_premise P(entail) >= threshold",
            "judge": "judge.judge: retrieved_context -> raw final answer + question -> Gemini "
                     "prompt -> JSON verdict",
        },
        "shared_steps": ["retrieved_context() (document flattening, number normalisation, "
                         "pronoun resolution added during dev tuning)",
                         "applicability gate: both skip traces with no retrieved documents",
                         "the same detector_view input"],
        "judge_uses_nli_output": False, "judge_uses_claim_split_or_entity_filter": False,
        "judge_runs_only_on_nli_selected": False,
        "n_traces": len(per), "n_either_ran": len(either),
        "nli_ran": sum(p["nli_ran"] for p in per.values()),
        "judge_ran": sum(p["judge_ran"] for p in per.values()),
        "agreement_table": {f"nli={a} | judge={b}": n for (a, b), n in sorted(table.items())},
        "disagreements": disagree,
    }
    h_rows = [r for r in rows if r["label"] not in ("OTHER_FAILURE", "RUN_ERROR")]
    flags = {t: bool(p["entity_rule"]) for t, p in per.items()}
    p_, r_ = ek.class_pr(h_rows, flags, "HALLUCINATION")
    ent = {"split": "dev", "rule": "flag iff a factual claim names an entity absent from every "
                                    "premise unit", "precision": p_, "recall": r_,
           "flagged_hallucination_traces": sum(1 for t, p in per.items()
                                               if p["label_v1"] == "HALLUCINATION" and flags[t]),
           "disclosure_required": (r_["value"] or 0) >= 0.95}
    prov = provenance(provider="local NLI + Gemini judge (cached)",
                      model=f"{NLI_MODEL}; {judge.JUDGE_MODEL}", mock=False, seed=None)
    write_result("A2-independence-dev", "phase2_independence_audit.json", audit,
                 provenance_info=prov,
                 summary=f"judge vs NLI (dev): {len(either)} traces where either ran, "
                         f"{disagree} disagreements; shared step: retrieved_context")
    write_result("A3-entity-rule-dev", "phase2_entity_rule_dev.json", ent, provenance_info=prov,
                 summary=f"entity-absence rule alone (dev): P={p_['value']} R={r_['value']}")
    with open(os.path.join(REPO, "results", "phase2_dev_predictions.json"), "w",
              encoding="utf-8", newline="\n") as fh:
        json.dump({"note": "per-trace DEV predictions from the frozen detectors "
                           "(tag phase2-detectors-frozen); not a result row",
                   "thresholds": th, "predictions": per}, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print(json.dumps({k: audit[k] for k in ("n_either_ran", "nli_ran", "judge_ran",
                                            "agreement_table", "disagreements")}, indent=1))
    print("entity rule alone:", p_, r_)
    print("judge spend (ledger):", round(judge.spent_usd(), 4))
    return 0


if __name__ == "__main__":
    sys.exit(main())
