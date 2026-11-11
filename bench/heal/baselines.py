"""No-critic baselines on dev (pre-registration item 3): H5 noise and the generic templates.

    python -m bench.heal.baselines --plan     # count runs, estimate spend, run nothing
    python -m bench.heal.baselines --run      # run (resumable), then score and write results
    python -m bench.heal.baselines --score    # score stored runs only

Writes results/heal_noise.json, results/heal_generic_dev.json and
reports/phase4/baselines_dev.md. Runs land in results/heal_runs.jsonl.
"""

from __future__ import annotations

import argparse
import os
from collections import Counter
from typing import Any

from bench.generate import MODELS, SEED
from bench.heal.config import ConfigPatch
from bench.heal.generic import Inapplicable, generic_patch
from bench.heal.harness import PHASE4_CAP_USD, RUNS_PATH, Harness, RunSpec, RunStore
from bench.heal.score import (CONFIRM_SEEDS, SEEDS, Scorer, failure_specs, net_of_noise,
                              summarize)
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
        if r["gate"]["promoted"]:
            out += failure_specs(fx[r["failure_id"]], generic[r["failure_id"]],
                                 sets["regression"], CONFIRM_SEEDS)
    return out


def score_all(sets, records) -> dict[str, Any]:
    sc = Scorer(records)
    noise, generic, inapp = arms(sets)
    fx = {f["failure_id"]: f for f in sets["failures"]}
    reg = sets["regression"]
    out: dict[str, Any] = {}
    for outcome in ("primary", "secondary"):
        ns = [sc.score_failure(fx[k], p, reg, outcome=outcome) for k, p in noise.items()]
        gs = [sc.score_failure(fx[k], p, reg, outcome=outcome) for k, p in generic.items()]
        conf = []  # fresh-seed confirmation runs exist only for primary-promoted patches
        for r in gs:
            if r["gate"]["promoted"] and outcome == "primary":
                c = sc.score_failure(fx[r["failure_id"]], generic[r["failure_id"]], reg,
                                     outcome=outcome, seeds=CONFIRM_SEEDS)
                conf.append({"failure_id": r["failure_id"], "confirm_gate": c["gate"],
                             "false_promotion": is_false_promotion(True, _gd(c["gate"]))})
        out[outcome] = {"noise": ns, "generic": gs, "generic_confirmation": conf}
    out["inapplicable"] = inapp
    out["patches"] = {p.patch_hash: p.to_json() for p in [ConfigPatch.none(), *generic.values()]}
    out["cost_noise"] = sc.cost(specs_for(sets, noise))
    n_ids = {s.run_id for s in specs_for(sets, noise)}
    g_extra = [s for s in specs_for(sets, generic) + confirmation_specs(
        sets, generic, out["primary"]["generic"]) if s.run_id not in n_ids]
    out["cost_generic"] = sc.cost(g_extra)
    out["noise_companions"] = noise_companions(sets, records)
    return out


class _gd:  # minimal view so is_false_promotion can read a stored gate dict
    def __init__(self, d):
        self.check2_heldout = d["check2_heldout"]
        self.check3_no_regression = d["check3_no_regression"]


def noise_companions(sets, records) -> dict[str, Any]:
    """Seed-level noise with no patch: how often the 3 seeds of one cell disagree."""
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
        keys = [k for k, v in cells.items() if v == kind]
        seen, mixed, any_pass, all_pass = set(), 0, 0, 0
        for base, env, t, p in keys:
            spec_key = RunSpec(none, base, env, t, p, 0).run_id.rsplit("-s", 1)[0]
            if spec_key in seen:
                continue
            seen.add(spec_key)
            runs = sc.runs(none, base, env, t, p, SEEDS, "primary")
            mixed += 0 < sum(runs) < 3
            any_pass += any(runs)
            all_pass += all(runs)
        n = len(seen)
        out[kind] = {"cells": n, "mixed_seeds": proportion(mixed, n),
                     "any_seed_pass": proportion(any_pass, n),
                     "all_seeds_pass": proportion(all_pass, n)}
    own = [sc.runs(none, f["fault"], f["fault"], f["task_id"], f["provider"], SEEDS, "primary")
           for f in sets["failures"]]
    out["own_task_seed0_pass"] = proportion(sum(r[0] for r in own), len(own))
    return out


def build_payloads(sets, s) -> tuple[dict, dict]:
    common = {"failures_n": len(sets["failures"]), "excluded": sets["excluded"],
              "regression": sets["regression"], "seeds": list(SEEDS),
              "selection_sha256": sets["selection_sha256"], "labels_sha256": sets["labels_sha256"],
              "cap_usd": PHASE4_CAP_USD}
    noise = {**common, "arm": "H5 no patch",
             "primary": summarize(s["primary"]["noise"]),
             "secondary": summarize(s["secondary"]["noise"]),
             "note": ("No-patch reruns. H2 and H3 are 0 by construction here: the no-patch runs are "
                      "also the gate's reference. See noise_companions for seed-level noise."),
             "noise_companions": s["noise_companions"], "spend": s["cost_noise"],
             "per_failure": s["primary"]["noise"]}
    gen = {**common, "arm": "generic fallback templates",
           "inapplicable": s["inapplicable"], "patches": s["patches"],
           "primary": summarize(s["primary"]["generic"]),
           "secondary": summarize(s["secondary"]["generic"]),
           "net_of_H5": {o: net_of_noise(s[o]["generic"], s[o]["noise"])
                         for o in ("primary", "secondary")},
           "H4": {o: h4(s[o]) for o in ("primary", "secondary")},
           "spend": s["cost_generic"], "per_failure": s["primary"]["generic"],
           "confirmation": s["primary"]["generic_confirmation"]}
    return noise, gen


def h4(block) -> dict[str, Any]:
    gs, conf = block["generic"], block["generic_confirmation"]
    return {"old_rule_promoted": sum(r["old_rule_promoted"] for r in gs),
            "old_rule_false_promotions": sum(r["old_rule_false_promotion"] for r in gs),
            "gate_promoted": sum(r["gate"]["promoted"] for r in gs),
            "gate_false_promotions_on_confirmation": sum(c["false_promotion"] for c in conf),
            "n_patches": len(gs)}


def write_all(sets, records) -> None:
    s = score_all(sets, records)
    noise, gen = build_payloads(sets, s)
    prov = provenance(provider="deepseek+ollama",
                      model=f"{MODELS['deepseek']}+{MODELS['ollama']}", mock=False, seed=SEED)
    a = noise["primary"]["all"]
    write_result("H5", "heal_noise.json", noise, provenance_info=prov, summary=(
        f"No-patch rerun of {a['n_patches']} dev failures x3: own task passes (>=2/3) "
        f"{a['H1_repair']['k']}/{a['n_patches']}; old rule would promote the null patch "
        f"{a['old_rule_promoted']['k']}/{a['n_patches']}; gate promotes 0"))
    g = gen["primary"]["all"]
    net = gen["net_of_H5"]["primary"]
    write_result("H1-H3 generic", "heal_generic_dev.json", gen, provenance_info=prov, summary=(
        f"Generic fallback patches (dev, {g['n_patches']} applicable, "
        f"{len(gen['inapplicable'])} inapplicable): H1 {g['H1_repair']['k']}/{g['n_patches']} "
        f"(net of H5 {net['H1_net']}), H2 {g['H2_generalize']['k']}, H3 "
        f"{g['H3_regress']['k']}, gate promoted {g['gate_promoted']['k']}"))
    write_report(noise, gen, prov)


def _p(d) -> str:
    if d["n"] == 0:
        return "–"
    lo, hi = d["ci95_clopper_pearson"]
    return f"{d['k']}/{d['n']} ({d['value']:.2f}; {lo:.2f}–{hi:.2f})"


def _rows(summary, label) -> list[str]:
    lines = []
    for name, b in [("all", summary["all"]), *[(f"{label}={k}", v) for k, v in
                                               summary["by_fault"].items()]]:
        lines.append(f"| {name} | {b['n_patches']} | {_p(b['H1_repair'])} | "
                     f"{_p(b['H2_generalize'])} | {_p(b['H3_regress'])} | "
                     f"{_p(b['gate_promoted'])} | {_p(b['old_rule_promoted'])} | "
                     f"{b['old_rule_false_promotions']} |")
    return lines


def write_report(noise, gen, prov) -> None:
    head = ["| Group | Patches | H1 repair | H2 generalize | H3 regress | Gate promoted | "
            "Old rule promoted | Old-rule false promotions |", "|---|---|---|---|---|---|---|---|"]
    nc = noise["noise_companions"]
    lines = [
        "# Phase 4 no-critic baselines (dev)", "",
        *report_header(provider=prov["provider"], model=prov["model"], mock=False,
                       generator="python -m bench.heal.baselines --score",
                       result_file="results/heal_generic_dev.json"),
        "- **Also:** [`results/heal_noise.json`](../../results/heal_noise.json), per-run "
        "records in [`results/heal_runs.jsonl`](../../results/heal_runs.jsonl)",
        "- **Pre-registration:** [`preregistration.md`](preregistration.md)", "",
        "Counts are patches (one per failure). Intervals are 95% Clopper-Pearson. A task passes "
        "at >= 2 of 3 runs by the bench-v1.1 checker. Generated file; do not edit.", "",
        "## H5: no patch, each failure re-run 3x", "", *head, *_rows(noise["primary"], "fault"),
        "", "H2 and H3 are 0 by construction for the null patch (it is its own reference).", "",
        "Seed-level noise (no patch):", "",
        f"- faulted cells (own + held-out tasks): {nc['faulted']['cells']}; seeds disagree in "
        f"{_p(nc['faulted']['mixed_seeds'])}; at least one seed passes in "
        f"{_p(nc['faulted']['any_seed_pass'])}",
        f"- regression cells: {nc['regression']['cells']}; seeds disagree in "
        f"{_p(nc['regression']['mixed_seeds'])}; all 3 seeds pass in "
        f"{_p(nc['regression']['all_seeds_pass'])}",
        f"- failing task passes on seed 0 alone (what the old rule sees): "
        f"{_p(nc['own_task_seed0_pass'])}", "",
        f"Spend: ${noise['spend']['cost_usd']:.4f} over {noise['spend']['runs']} runs "
        f"({noise['spend']['llm_calls']} LLM calls, {noise['spend']['run_errors']} run errors).",
        "", "## Generic fallback templates as patches", "",
        f"Inapplicable (no config key for the template's target): "
        f"{len(gen['inapplicable'])} failures "
        f"({', '.join(sorted({k.split('|')[0] for k in gen['inapplicable']}))}). "
        "They are not run and are not in the denominators below.", "",
        *head, *_rows(gen["primary"], "fault"), "",
        "By injection tag:", "",
        *[f"- {k}: {v['n_patches']} patches, H1 {_p(v['H1_repair'])}"
          for k, v in gen["primary"]["by_tag"].items()], "",
        "Net of H5 (same failures, primary outcome): "
        + ", ".join(f"{k} {v}" for k, v in gen["net_of_H5"]["primary"].items()), "",
        "H4 inputs (primary): " + ", ".join(f"{k} {v}" for k, v in gen["H4"]["primary"].items()),
        "", f"Spend (runs not shared with H5): ${gen['spend']['cost_usd']:.4f} over "
        f"{gen['spend']['runs']} runs ({gen['spend']['llm_calls']} LLM calls, "
        f"{gen['spend']['run_errors']} run errors).", "",
        "## Secondary outcome (reported, not gated): the fault's own rule did not fire", "",
        "### H5", "", *head, *_rows(noise["secondary"], "fault"), "",
        "### Generic", "", *head, *_rows(gen["secondary"], "fault"), "",
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
            scored = score_all(sets, h.records())["primary"]["generic"]
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
