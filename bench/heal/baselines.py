"""No-critic baselines on dev (pre-registration item 3): H5 noise and the generic templates.

    python -m bench.heal.baselines --plan     # count runs, estimate spend, run nothing
    python -m bench.heal.baselines --run      # run (resumable), then score and write results
    python -m bench.heal.baselines --score    # score stored runs only

Writes results/heal_noise.json, results/heal_generic_dev.json and
reports/phase4/baselines_dev.md. Runs land in results/heal_runs.jsonl.

Scoring follows amendment A1 (reports/phase4/amendment_a1.md): the primary outcome is
per-class safe-failure repair; the phase4-prereg checker outcome is reported beside it.
"""

from __future__ import annotations

import argparse
import os
from collections import Counter
from typing import Any

from bench.generate import MODELS, SEED
from bench.heal.config import ConfigPatch
from bench.heal.generic import Inapplicable, generic_patch
from bench.heal.harness import PHASE4_CAP_USD, REST_CAP_USD, RUNS_PATH, Harness, RunSpec, RunStore
from bench.heal.score import (CONFIRM_SEEDS, OUTCOMES, PRIMARY, SEEDS, Scorer, eligible,
                              failure_specs, net_of_noise, summarize)
from bench.heal.sets import REPO, load_sets
from services.common.results import provenance, report_header, write_result
from services.healer.gate import is_false_promotion, proportion

REPORT = os.path.join(REPO, "reports", "phase4", "baselines_dev.md")
DS_COST_PER_CALL = 0.00021   # mean DeepSeek call in the Phase 1 ledger (517 in / 42 out tokens)
CALLS_PER_RUN = 5.0          # planning estimate only


def arms(sets: dict[str, Any]) -> tuple[dict, dict, dict]:
    none = ConfigPatch.none()
    noise = {f["failure_id"]: none for f in sets["failures"]}
    generic, inapplicable = {}, {}
    for f in sets["failures"]:
        try:
            generic[f["failure_id"]] = generic_patch(f["fault"])
        except Inapplicable as exc:
            inapplicable[f["failure_id"]] = str(exc)
    return noise, generic, inapplicable


def specs_for(sets, patches: dict[str, ConfigPatch], seeds=SEEDS) -> list[RunSpec]:
    fx = {f["failure_id"]: f for f in sets["failures"]}
    out: list[RunSpec] = []
    for fid, p in patches.items():
        out += failure_specs(fx[fid], p, sets["regression"], seeds)
    return out


def _unique(specs):
    return {s.run_id: s for s in specs}


def plan(sets) -> dict[str, Any]:
    noise, generic, inapp = arms(sets)
    n_specs, g_specs = _unique(specs_for(sets, noise)), _unique(specs_for(sets, generic))
    g_only = {k: v for k, v in g_specs.items() if k not in n_specs}
    out = {}
    for name, sp in (("noise", n_specs), ("generic_extra", g_only)):
        c = Counter(s.provider for s in sp.values())
        out[name] = {"runs": len(sp), "by_provider": dict(c),
                     "est_deepseek_usd": round(c.get("deepseek", 0) * CALLS_PER_RUN
                                               * DS_COST_PER_CALL, 3)}
    out["generic_inapplicable"] = len(inapp)
    return out


def confirmation_specs(sets, generic, scored_generic) -> list[RunSpec]:
    fx = {f["failure_id"]: f for f in sets["failures"]}
    out = []
    for r in scored_generic:
        if r["gate"]["promoted"] and r["failure_id"] in generic:
            out += failure_specs(fx[r["failure_id"]], generic[r["failure_id"]],
                                 sets["regression"], CONFIRM_SEEDS)
    return out


OUTCOME_NAMES = {"a1": "A1 safe-failure repair (primary)",
                 "checker": "checker only (phase4-prereg primary; secondary under A1)",
                 "rule": "fault rule cleared (secondary)"}


def score_all(sets, records) -> dict[str, Any]:
    sc = Scorer(records)
    noise, generic, inapp = arms(sets)
    fx = {f["failure_id"]: f for f in sets["failures"]}
    reg = sets["regression"]
    out: dict[str, Any] = {"by_outcome": {}}
    for outcome in OUTCOMES:
        keep = [k for k in fx if eligible(fx[k], outcome)]
        no_harm = [k for k in fx if not eligible(fx[k], outcome)]
        ns = [sc.score_failure(fx[k], noise[k], reg, outcome=outcome) for k in keep]
        gs = [sc.score_failure(fx[k], generic[k], reg, outcome=outcome)
              for k in keep if k in generic]
        conf = []
        for r in gs:
            if not r["gate"]["promoted"]:
                continue
            k = r["failure_id"]
            if not sc.has(failure_specs(fx[k], generic[k], reg, CONFIRM_SEEDS)):
                conf.append({"failure_id": k, "status": "not_run"})
                continue
            c = sc.score_failure(fx[k], generic[k], reg, outcome=outcome, seeds=CONFIRM_SEEDS)
            conf.append({"failure_id": k, "status": "scored", "confirm_gate": c["gate"],
                         "false_promotion": is_false_promotion(True, _gd(c["gate"]))})

        def breaks(k, patch):
            return sc.score_failure(fx[k], patch, reg, outcome="checker")["gate"][
                "regression_breaks"]

        excl = [{"failure_id": k, "noise_regression_breaks": breaks(k, noise[k]),
                 "generic_regression_breaks": breaks(k, generic[k]) if k in generic else None}
                for k in no_harm]
        repaired = sum(r["gate"]["check1_own_task"] for r in gs)
        per_failure = {"eligible_failures": len(keep), "repaired": repaired,
                       "no_applicable_patch": sum(1 for k in keep if k not in generic),
                       "H1_per_failure": proportion(repaired, len(keep))}
        out["by_outcome"][outcome] = {
            "noise": ns, "generic": gs, "generic_confirmation": conf,
            "no_observable_harm_excluded": excl, "generic_per_failure": per_failure}
    out["inapplicable"] = inapp
    out["patches"] = {p.patch_hash: p.to_json() for p in [ConfigPatch.none(), *generic.values()]}
    out["cost_noise"] = sc.cost(specs_for(sets, noise))
    n_ids = {s.run_id for s in specs_for(sets, noise)}
    out["cost_generic"] = sc.cost([s for s in specs_for(sets, generic) if s.run_id not in n_ids])
    out["noise_companions"] = noise_companions(sets, records)
    return out


class _gd:  # minimal view so is_false_promotion can read a stored gate dict
    def __init__(self, d):
        self.check2_heldout = d["check2_heldout"]
        self.check3_no_regression = d["check3_no_regression"]


def noise_companions(sets, records) -> dict[str, Any]:
    """Seed-level noise with no patch (checker): how often the 3 seeds of one cell disagree."""
    sc = Scorer(records)
    none = ConfigPatch.none()
    cells = {}
    for f in sets["failures"]:
        for t in [f["task_id"], *f["heldout"]]:
            cells[(f["fault"], f["fault"], t, f["provider"])] = "faulted"
        for t in sets["regression"]:
            cells[(f["fault"], "NONE", t, f["provider"])] = "regression"
    out: dict[str, Any] = {}
    for kind in ("faulted", "regression"):
        seen, mixed, any_pass, all_pass = set(), 0, 0, 0
        for (base, env, t, p), v in cells.items():
            if v != kind:
                continue
            key = RunSpec(none, base, env, t, p, 0).run_id.rsplit("-s", 1)[0]
            if key in seen:
                continue
            seen.add(key)
            runs = sc.runs(none, base, env, t, p, SEEDS, "checker")
            mixed += 0 < sum(runs) < 3
            any_pass += any(runs)
            all_pass += all(runs)
        n = len(seen)
        out[kind] = {"cells": n, "mixed_seeds": proportion(mixed, n),
                     "any_seed_pass": proportion(any_pass, n),
                     "all_seeds_pass": proportion(all_pass, n)}
    return out


def h4(block) -> dict[str, Any]:
    gs, conf = block["generic"], block["generic_confirmation"]
    return {"n_patches": len(gs),
            "old_rule_promoted": sum(r["old_rule_promoted"] for r in gs),
            "old_rule_false_promotions": sum(r["old_rule_false_promotion"] for r in gs),
            "gate_promoted": sum(r["gate"]["promoted"] for r in gs),
            "gate_false_promotions_on_confirmation":
                sum(c.get("false_promotion", False) for c in conf),
            "confirmation_not_run": sum(c["status"] == "not_run" for c in conf)}


def build_payloads(sets, s) -> tuple[dict, dict]:
    common = {"failures_n": len(sets["failures"]), "excluded": sets["excluded"],
              "regression": sets["regression"], "seeds": list(SEEDS),
              "selection_sha256": sets["selection_sha256"], "labels_sha256": sets["labels_sha256"],
              "cap_usd": {"preparation": PHASE4_CAP_USD, "rest_of_phase4": REST_CAP_USD}, "primary_outcome": PRIMARY,
              "outcomes": OUTCOME_NAMES, "amendment": "A1 (tag phase4-prereg-a1)"}
    bo = s["by_outcome"]
    noise = {**common, "arm": "H5 no patch",
             "summary": {o: summarize(bo[o]["noise"]) for o in OUTCOMES},
             "no_observable_harm_excluded": bo[PRIMARY]["no_observable_harm_excluded"],
             "note": ("No-patch reruns. H2 and H3 are 0 by construction here: the no-patch runs "
                      "are also the gate's reference."),
             "noise_companions": s["noise_companions"], "spend": s["cost_noise"],
             "per_failure": {o: bo[o]["noise"] for o in OUTCOMES}}
    gen = {**common, "arm": "generic fallback templates",
           "inapplicable": s["inapplicable"], "patches": s["patches"],
           "summary": {o: summarize(bo[o]["generic"]) for o in OUTCOMES},
           "per_failure_rate": {o: bo[o]["generic_per_failure"] for o in OUTCOMES},
           "no_observable_harm_excluded": bo[PRIMARY]["no_observable_harm_excluded"],
           "net_of_H5": {o: net_of_noise(bo[o]["generic"], bo[o]["noise"]) for o in OUTCOMES},
           "H4": {o: h4(bo[o]) for o in OUTCOMES},
           "spend": s["cost_generic"],
           "per_failure": {o: bo[o]["generic"] for o in OUTCOMES},
           "confirmation": {o: bo[o]["generic_confirmation"] for o in OUTCOMES}}
    return noise, gen


def write_all(sets, records) -> None:
    s = score_all(sets, records)
    noise, gen = build_payloads(sets, s)
    prov = provenance(provider="deepseek+ollama",
                      model=f"{MODELS['deepseek']}+{MODELS['ollama']}", mock=False, seed=SEED)
    a, c = noise["summary"]["a1"]["all"], noise["summary"]["checker"]["all"]
    write_result("H5", "heal_noise.json", noise, provenance_info=prov, summary=(
        f"No-patch rerun of dev failures x3 (A1): safe repair {a['H1_repair']['k']}/"
        f"{a['n_patches']} ({len(noise['no_observable_harm_excluded'])} no-harm bleed "
        f"excluded); checker-only {c['H1_repair']['k']}/{c['n_patches']}; gate promotes "
        f"{a['gate_promoted']['k']}"))
    g, gc = gen["summary"]["a1"]["all"], gen["summary"]["checker"]["all"]
    net = gen["net_of_H5"]["a1"]
    write_result("H1-H3 generic", "heal_generic_dev.json", gen, provenance_info=prov, summary=(
        f"Generic fallback patches (dev, A1): H1 {g['H1_repair']['k']}/{g['n_patches']} (net of "
        f"H5 {net['H1_net']}), H2 {g['H2_generalize']['k']}, H3 {g['H3_regress']['k']}, gate "
        f"promoted {g['gate_promoted']['k']}; checker-only H1 {gc['H1_repair']['k']}/"
        f"{gc['n_patches']}; {len(gen['inapplicable'])} inapplicable"))
    write_report(noise, gen, prov)


def _p(d) -> str:
    if d["n"] == 0:
        return "–"
    lo, hi = d["ci95_clopper_pearson"]
    return f"{d['k']}/{d['n']} ({d['value']:.2f}; {lo:.2f}–{hi:.2f})"


HEAD = ["| Group | Patches | H1 repair | H2 generalize | H3 regress | Gate promoted | "
        "Old rule promoted | Old-rule false promotions |", "|---|---|---|---|---|---|---|---|"]


def _cells(b) -> str:
    return (f"{b['n_patches']} | {_p(b['H1_repair'])} | {_p(b['H2_generalize'])} | "
            f"{_p(b['H3_regress'])} | {_p(b['gate_promoted'])} | {_p(b['old_rule_promoted'])} | "
            f"{b['old_rule_false_promotions']} |")


def _rows(summary) -> list[str]:
    return [f"| all | {_cells(summary['all'])}",
            *[f"| fault={k} | {_cells(v)}" for k, v in summary["by_fault"].items()]]


def write_report(noise, gen, prov) -> None:
    nc = noise["noise_companions"]
    side = ["| Arm | Definition | Patches | H1 repair | H2 generalize | H3 regress | "
            "Gate promoted | Old rule promoted | Old-rule false promotions |",
            "|---|---|---|---|---|---|---|---|---|"]
    for arm, doc in (("H5 no patch", noise), ("generic", gen)):
        for o, name in (("checker", "old: checker"), ("a1", "new: A1")):
            side.append(f"| {arm} | {name} | {_cells(doc['summary'][o]['all'])}")
    excl = noise["no_observable_harm_excluded"]
    gpf = gen["per_failure_rate"]["a1"]
    tags = "; ".join(f"{k}: {v['n_patches']} patches, H1 {_p(v['H1_repair'])}"
                     for k, v in gen["summary"]["a1"]["by_tag"].items())
    secondary = []
    for o in ("checker", "rule"):
        secondary += [f"### {OUTCOME_NAMES[o]}", "", "H5:", "", *HEAD,
                      *_rows(noise["summary"][o]), "", "Generic:", "", *HEAD,
                      *_rows(gen["summary"][o]), ""]
    lines = [
        "# Phase 4 no-critic baselines (dev)", "",
        *report_header(provider=prov["provider"], model=prov["model"], mock=False,
                       generator="python -m bench.heal.baselines --score"),
        "- **Result files:** [`results/heal_generic_dev.json`](../../results/heal_generic_dev.json)"
        ", [`results/heal_noise.json`](../../results/heal_noise.json), per-run records in "
        "[`results/heal_runs.jsonl`](../../results/heal_runs.jsonl)",
        "- **Protocol:** [`preregistration.md`](preregistration.md) + amendment "
        "[`amendment_a1.md`](amendment_a1.md) (primary outcome = A1 safe-failure repair)", "",
        "Counts are patches (one per failure). Intervals are 95% Clopper-Pearson. A task passes "
        "at >= 2 of 3 runs. H3 is checker-based under every definition. Rescored from stored "
        "runs; no run was repeated for A1. Generated file; do not edit.", "",
        "## Old vs new definition, side by side", "", *side, "",
        f"A1 leaves out {len(excl)} CONTEXT_BLEED failures whose original trace already passed "
        "the checker (no observable harm); the checker rows include them. Generic arm per "
        f"eligible failure (no applicable patch = not repaired): {_p(gpf['H1_per_failure'])}.",
        "",
        "## H5: no patch (A1)", "", *HEAD, *_rows(noise["summary"]["a1"]), "",
        "H2 and H3 are 0 by construction for the null patch (it is its own reference).", "",
        f"Seed-level noise (no patch, checker): faulted cells {nc['faulted']['cells']}, seeds "
        f"disagree in {_p(nc['faulted']['mixed_seeds'])}; regression cells "
        f"{nc['regression']['cells']}, seeds disagree in {_p(nc['regression']['mixed_seeds'])}.",
        "",
        f"Spend: ${noise['spend']['cost_usd']:.4f} over {noise['spend']['runs']} runs "
        f"({noise['spend']['llm_calls']} LLM calls, {noise['spend']['run_errors']} run errors).",
        "", "## Generic fallback templates (A1)", "",
        f"Inapplicable (no config key for the template's target): {len(gen['inapplicable'])} "
        f"failures ({', '.join(sorted({k.split('|')[0] for k in gen['inapplicable']}))}); "
        "not run, not in the patch denominators.", "",
        *HEAD, *_rows(gen["summary"]["a1"]), "",
        f"By injection tag: {tags}.", "",
        "Net of H5 (A1): " + ", ".join(f"{k} {v}" for k, v in gen["net_of_H5"]["a1"].items()), "",
        "H4 (A1): " + ", ".join(f"{k} {v}" for k, v in gen["H4"]["a1"].items()), "",
        "A gate-promoted patch needs a fresh-seed confirmation (seeds 3-5) before H4 can count "
        "gate false promotions. A1 item 4 allows no new runs, so those are listed as not run.", "",
        f"Spend (runs not shared with H5): ${gen['spend']['cost_usd']:.4f} over "
        f"{gen['spend']['runs']} runs.", "",
        "## Secondary outcomes", "", *secondary,
    ]
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--plan", action="store_true")
    g.add_argument("--run", action="store_true")
    g.add_argument("--score", action="store_true")
    ap.add_argument("--arm", choices=["noise", "generic", "both"], default="both")
    ap.add_argument("--confirm", action="store_true",
                    help="with --run: also run fresh-seed confirmations of gate-promoted patches")
    ap.add_argument("--env-file", default=None)
    args = ap.parse_args()
    sets = load_sets()
    if args.plan:
        for k, v in plan(sets).items():
            print(k, v)
        return 0
    if args.run:
        h = Harness(env_file=args.env_file)
        noise, generic, _ = arms(sets)
        if args.arm in ("noise", "both"):
            print("noise:", h.run_all(specs_for(sets, noise)))
        if args.arm in ("generic", "both"):
            print("generic:", h.run_all(specs_for(sets, generic)))
            if args.confirm:
                scored = score_all(sets, h.records())["by_outcome"][PRIMARY]["generic"]
                conf = confirmation_specs(sets, generic, scored)
                if conf:
                    print("confirmation:", h.run_all(conf))
        print(f"phase-4 ledger total ${h.ledger.total():.4f}")
        if args.arm != "both":
            return 0
    write_all(sets, RunStore(RUNS_PATH).by_id)
    print("wrote results/heal_noise.json, results/heal_generic_dev.json, "
          "reports/phase4/baselines_dev.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
