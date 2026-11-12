"""Amendment A2 runs and scoring (reports/phase4/amendment_a2.md), dev only.

    python -m bench.heal.a2 --plan                      # run counts and spend estimate
    python -m bench.heal.a2 --run generic               # A2 item 3: generic HALLUCINATION re-run
    python -m bench.heal.a2 --run arms [--arm new]      # critic arms, seeds 0-2
    python -m bench.heal.a2 --run confirm               # seeds 3-5 for gate-promoted patches
    python -m bench.heal.a2 --score                     # score stored runs, write results

Under A2 the gate's check 3 and H3 use ``regression_a2`` (every dev qa task that passes
with no fault, plus the 9 tool/plan/memory tasks of the A1 set). Every H metric is
reported per failure and per distinct patch (``score.summarize_distinct``).
The primary outcome is A1 safe-failure repair; the injection tags are reported apart
and the headline is ``other_fix`` (pre-registration 1e).
"""

from __future__ import annotations

import argparse
import os
from collections import Counter
from typing import Any

from bench.generate import MODELS, SEED
from bench.heal.config import ConfigPatch, apply_patch, faulted_config
from bench.heal.critic import ARMS, Proposal, load_round3
from bench.heal.generic import generic_patch
from bench.heal.harness import H6_RESERVE_USD, REST_CAP_USD, RUNS_PATH, Harness, RunSpec, RunStore
from bench.heal.score import (CONFIRM_SEEDS, OUTCOMES, PRIMARY, SEEDS, Scorer, eligible,
                              failure_specs, net_of_noise, summarize, summarize_distinct)
from bench.heal.sets import REPO, load_sets
from services.common.results import provenance, write_result
from services.healer.gate import is_false_promotion, proportion

ROUND3 = os.path.join(REPO, "reports", "phase3", "round3")
REG_KEY = "regression_a2"
TAGS = ("other_fix", "reverts_injection")
GENERIC_RUN_CAP_USD = 3.0   # cap in force when the generic A2 re-run was made (D69, D74)


def reg(sets) -> list[str]:
    return sets[REG_KEY]


def by_failure(sets) -> dict[str, dict[str, Any]]:
    return {f["failure_id"]: f for f in sets["failures"]}


# -- arms ---------------------------------------------------------------------------

def generic_hallucination(sets) -> dict[str, ConfigPatch]:
    """A2 item 3: the generic arm's 12 HALLUCINATION patches (one distinct diff)."""
    return {f["failure_id"]: generic_patch("HALLUCINATION") for f in sets["failures"]
            if f["fault"] == "HALLUCINATION"}


def critic_arm(sets, arm: str, path: str | None = None
               ) -> tuple[dict[str, ConfigPatch], dict[str, Proposal]]:
    path = path or os.path.join(ROUND3, f"{arm}.jsonl")
    fx = {f["trace_id"]: f for f in sets["failures"]}
    props = load_round3(path, arm, {t: f["fault"] for t, f in fx.items()})
    missing = sorted(set(fx) - set(props))
    if missing:
        raise ValueError(f"{arm}: no round-3 record for {len(missing)} failures: {missing[:3]}")
    by_fid = {fx[t]["failure_id"]: p for t, p in props.items() if t in fx}
    patches = {fid: p.patch for fid, p in by_fid.items() if p.status == "patch"}
    return patches, by_fid


def specs(sets, patches: dict[str, ConfigPatch], seeds=SEEDS) -> list[RunSpec]:
    fx = by_failure(sets)
    out: list[RunSpec] = []
    for fid, p in patches.items():
        out += failure_specs(fx[fid], p, reg(sets), seeds)
    return out


def reference_specs(sets, fids) -> list[RunSpec]:
    """No-patch references (seeds 0-2) on own, held-out and A2 regression tasks."""
    none = ConfigPatch.none()
    return specs(sets, {fid: none for fid in fids})


def unique(ss) -> dict[str, RunSpec]:
    return {s.run_id: s for s in ss}


# -- planning -----------------------------------------------------------------------

_CALLS = {("qa", True): 3.67, ("qa", False): 3.0, ("tool", True): 5.37, ("tool", False): 4.0,
          ("plan", True): 5.6, ("plan", False): 5.0, ("memory", True): 6.52,
          ("memory", False): 5.0}   # mean LLM calls per DeepSeek run, Phase 4 baselines
_FAM = {"qa": "qa", "tool": "tool", "plan": "plan", "mem": "memory"}


def estimate(ss, done: set[str]) -> dict[str, Any]:
    """Planning estimate (not a cap): DeepSeek $/run from mean calls x tokens, with the
    patched system prompt's extra tokens (chars / 3.5) on every call."""
    usd, n = 0.0, Counter()
    for s in ss.values():
        if s.run_id in done:
            continue
        n[s.provider] += 1
        if s.provider != "deepseek":
            continue
        cfg = apply_patch(faulted_config(s.base_fault), s.patch)
        extra = (len(cfg["system_prompt"]) - len(faulted_config(s.base_fault)["system_prompt"]))
        calls = _CALLS[(_FAM[s.task_id.split("-")[0]], s.env_fault != "NONE")]
        usd += calls * ((506 + max(extra, 0) / 3.5) * 0.30e-6 + 39 * 1.20e-6)
    return {"to_run": dict(n), "est_deepseek_usd": round(usd, 3),
            "est_ollama_hours_2_workers": round(n["ollama"] * 12.3 / 2 / 3600, 1)}


# -- scoring ------------------------------------------------------------------------

class _gd:
    def __init__(self, d):
        self.check2_heldout = d["check2_heldout"]
        self.check3_no_regression = d["check3_no_regression"]


def score_arm(sets, records, patches: dict[str, ConfigPatch],
              proposals: dict[str, Proposal] | None = None) -> dict[str, Any]:
    sc = Scorer(records)
    fx, rg = by_failure(sets), reg(sets)
    out: dict[str, Any] = {"by_outcome": {}}
    for outcome in OUTCOMES:
        keep = [k for k in fx if eligible(fx[k], outcome)]
        no_harm = [k for k in fx if not eligible(fx[k], outcome)]
        rows, missing = [], []
        for k in keep:
            if k not in patches:
                continue
            if not sc.has(failure_specs(fx[k], patches[k], rg, SEEDS)):
                missing.append(k)
                continue
            rows.append(sc.score_failure(fx[k], patches[k], rg, outcome=outcome))
        conf = {}
        for r in rows:
            if not r["gate"]["promoted"]:
                continue
            k = r["failure_id"]
            if not sc.has(failure_specs(fx[k], patches[k], rg, CONFIRM_SEEDS)):
                conf[k] = {"failure_id": k, "status": "not_run"}
                continue
            c = sc.score_failure(fx[k], patches[k], rg, outcome=outcome, seeds=CONFIRM_SEEDS)
            conf[k] = {"failure_id": k, "status": "scored", "confirm_gate": c["gate"],
                       "false_promotion": is_false_promotion(True, _gd(c["gate"]))}
        noise = [sc.score_failure(fx[k], ConfigPatch.none(), rg, outcome=outcome)
                 for k in keep if sc.has(failure_specs(fx[k], ConfigPatch.none(), rg, SEEDS))]
        excl = []
        for k in no_harm:
            if k in patches and sc.has(failure_specs(fx[k], patches[k], rg, SEEDS)):
                g = sc.score_failure(fx[k], patches[k], rg, outcome="checker")["gate"]
                excl.append({"failure_id": k, "regression_breaks": g["regression_breaks"]})
        repaired = sum(r["gate"]["check1_own_task"] for r in rows)
        per_failure = {"eligible_failures": len(keep), "repaired": repaired,
                       "no_patch": sum(1 for k in keep if k not in patches),
                       "H1_per_failure": proportion(repaired, len(keep))}
        if proposals is not None:
            per_failure["no_patch_reasons"] = dict(Counter(
                proposals[k].reason for k in keep if k not in patches))
        h4 = {"n_patches": len(rows),
              "old_rule_promoted": sum(r["old_rule_promoted"] for r in rows),
              "old_rule_false_promotions": sum(r["old_rule_false_promotion"] for r in rows),
              "gate_promoted": sum(r["gate"]["promoted"] for r in rows),
              "gate_false_promotions": sum(c.get("false_promotion", False) for c in conf.values()),
              "confirmation_not_run": sum(c["status"] == "not_run" for c in conf.values())}
        h4_by_tag = {}
        for tag in TAGS:
            rt = [r for r in rows if r["tag"] == tag]
            h4_by_tag[tag] = {
                "n_patches": len(rt),
                "old_rule_promoted": sum(r["old_rule_promoted"] for r in rt),
                "old_rule_false_promotions": sum(r["old_rule_false_promotion"] for r in rt),
                "gate_promoted": sum(r["gate"]["promoted"] for r in rt),
                "gate_false_promotions": sum(conf.get(r["failure_id"], {}).get(
                    "false_promotion", False) for r in rt)}
        out["by_outcome"][outcome] = {
            "per_failure_rows": rows, "not_run": missing,
            "summary_per_failure": summarize(rows),
            "summary_per_distinct_patch": summarize_distinct(rows, conf),
            "per_failure_rate": per_failure, "confirmation": list(conf.values()),
            "H4": h4, "H4_by_tag": h4_by_tag,
            "net_of_H5": net_of_noise([r for r in rows
                                       if r["failure_id"] in {n["failure_id"] for n in noise}],
                                      noise),
            "no_observable_harm_excluded": excl}
    out["patches"] = {p.patch_hash: p.to_json() for p in patches.values()}
    out["seed_noise"] = seed_noise(sc, sets, patches, out["by_outcome"][PRIMARY])
    return out


def seed_noise(sc: Scorer, sets, patches, block) -> dict[str, Any]:
    """Descriptive only (D72): how often seeds disagree. Not used by the gate or selection.

    * ``within_s0_2``: run cells (patch, task, env) whose 3 seeds 0-2 do not all give the
      same outcome (A1 rule on faulted runs, checker on regression runs);
    * ``confirm_task_flips``: for gate-promoted patches with a scored confirmation, task
      cells whose 2-of-3 task outcome on seeds 3-5 differs from seeds 0-2.
    """
    fx, rg = by_failure(sets), reg(sets)
    cells, mixed, kinds = set(), Counter(), Counter()
    flips, nflip = Counter(), Counter()
    confirmed = {c["failure_id"] for c in block["confirmation"] if c["status"] == "scored"}
    for fid, p in patches.items():
        f = fx[fid]
        tasks = [(t, f["fault"], "faulted") for t in [f["task_id"], *f["heldout"]]]
        tasks += [(t, "NONE", "regression") for t in rg]
        for t, env, kind in tasks:
            key = (p.patch_hash, f["fault"], env, t, f["provider"])
            if key in cells:
                continue
            specs0 = [RunSpec(p, f["fault"], env, t, f["provider"], s) for s in SEEDS]
            if not sc.has(specs0):
                continue
            cells.add(key)
            o = [sc.ok(sc.rec(s), PRIMARY) for s in specs0]
            kinds[kind] += 1
            mixed[kind] += 0 < sum(o) < 3
            if fid in confirmed:
                specs1 = [RunSpec(p, f["fault"], env, t, f["provider"], s) for s in CONFIRM_SEEDS]
                if sc.has(specs1):
                    o1 = [sc.ok(sc.rec(s), PRIMARY) for s in specs1]
                    nflip[kind] += 1
                    flips[kind] += (sum(o) >= 2) != (sum(o1) >= 2)
    return {"within_s0_2": {k: proportion(mixed[k], kinds[k]) for k in sorted(kinds)},
            "within_s0_2_all": proportion(sum(mixed.values()), sum(kinds.values())),
            "confirm_task_flips": {k: proportion(flips[k], nflip[k]) for k in sorted(nflip)},
            "confirm_task_flips_all": proportion(sum(flips.values()), sum(nflip.values()))}


def selection(arms: dict[str, dict[str, Any]], outcome: str = PRIMARY) -> dict[str, Any]:
    """Pre-registered rule (1f, A1 §3): fewest gate false promotions on fresh seeds,
    ties broken by higher H2. Refuses to select while a confirmation is missing."""
    table = {}
    for name, s in arms.items():
        b = s["by_outcome"][outcome]
        if b["H4"]["confirmation_not_run"] or b["not_run"]:
            raise RuntimeError(f"{name}: runs missing; selection needs complete arms")
        table[name] = {"gate_false_promotions": b["H4"]["gate_false_promotions"],
                       "H2": b["summary_per_failure"]["all"]["H2_generalize"]["value"],
                       "H2_k": b["summary_per_failure"]["all"]["H2_generalize"]["k"],
                       "H2_n": b["summary_per_failure"]["all"]["H2_generalize"]["n"]}
    order = sorted(table, key=lambda a: (table[a]["gate_false_promotions"],
                                         -(table[a]["H2"] or 0.0)))
    best = order[0]
    tie = [a for a in order if (table[a]["gate_false_promotions"], table[a]["H2"]) ==
           (table[best]["gate_false_promotions"], table[best]["H2"])]
    # A2 §2: the same rule on per-distinct-patch counts, reported (not used to select).
    dt = {name: {"gate_false_promotions": s["by_outcome"][outcome]["summary_per_distinct_patch"][
                     "all"]["gate_false_promotions"],
                 "H2": s["by_outcome"][outcome]["summary_per_distinct_patch"]["all"][
                     "H2_generalize"]["value"]} for name, s in arms.items()}
    dbest = sorted(dt, key=lambda a: (dt[a]["gate_false_promotions"], -(dt[a]["H2"] or 0.0)))[0]
    return {"rule": "fewest gate false promotions on seeds 3-5; ties by higher H2 (per patch)",
            "outcome": outcome, "table": table, "selected": best,
            "unresolved_tie": tie if len(tie) > 1 else [],
            "per_distinct": {"table": dt, "selected": dbest, "same_as_selected": dbest == best}}


def write_results(sets, records, only: str | None = None) -> dict[str, Any]:
    prov = provenance(provider="deepseek+ollama",
                      model=f"{MODELS['deepseek']}+{MODELS['ollama']}", mock=False, seed=SEED)
    common = {"amendment": "A2 (tag phase4-prereg-a2)", "regression_set": REG_KEY,
              "regression": reg(sets), "seeds": list(SEEDS), "confirm_seeds": list(CONFIRM_SEEDS),
              "primary_outcome": PRIMARY, "cap_usd_rest_of_phase4": REST_CAP_USD}
    gen = score_arm(sets, records, generic_hallucination(sets))
    noise = {"generic": gen.pop("seed_noise")}
    out = {"generic": gen}
    if only == "generic":
        # Written once, when the generic re-run finished (D74): the cap recorded is the
        # one in force at run time, and seed noise lives in heal_seed_noise_dev.json.
        write_result("A2 generic", "heal_generic_a2_dev.json",
                     {**common, "cap_usd_rest_of_phase4": GENERIC_RUN_CAP_USD,
                      "arm": "generic (HALLUCINATION, A2)", **gen},
                     provenance_info=prov, summary=_line("generic HALLUCINATION under A2", gen))
        return out
    arms = {}
    for arm in ARMS:
        patches, props = critic_arm(sets, arm)
        s = score_arm(sets, records, patches, props)
        noise[arm] = s["seed_noise"]
        if only == "seed_noise":
            continue
        s["proposals"] = {k: {"status": p.status, "reason": p.reason,
                              "phase3_fix_tag": p.phase3_fix_tag,
                              "patch_hash": p.patch.patch_hash if p.patch else None}
                          for k, p in props.items()}
        write_result(f"A2 critic {arm}", f"heal_critic_{arm}_dev.json",
                     {**common, "arm": f"critic {arm} (detector evidence)", **s},
                     provenance_info=prov, summary=_line(f"critic {arm}", s))
        arms[arm] = s
    write_seed_noise(prov, common, noise)
    if only == "seed_noise":
        return {"seed_noise": noise}
    out.update(arms)
    try:
        out["selection"] = selection(arms)
    except RuntimeError as exc:
        out["selection"] = {"status": "not selected", "reason": str(exc)}
    if out["selection"].get("selected"):
        out["selection"]["test_cost_estimate"] = test_cost_estimate(
            sets, records, out["selection"]["selected"], arms[out["selection"]["selected"]])
    write_result("A2 selection", "heal_selection_dev.json", {**common, **out["selection"]},
                 provenance_info=prov, summary=f"selected: {out['selection'].get('selected')}")
    return out


def write_seed_noise(prov, common, noise: dict[str, Any]) -> None:
    """D72 item 1 / D74: descriptive seed-disagreement rates, one file for all arms."""
    tot = {k: sum(n["within_s0_2_all"][k] for n in noise.values()) for k in ("k", "n")}
    fl = {k: sum(n["confirm_task_flips_all"][k] for n in noise.values()) for k in ("k", "n")}
    write_result("A2 seed noise", "heal_seed_noise_dev.json",
                 {**common, "note": "Descriptive only; not used by the gate or the selection "
                  "rule (D72).", "arms": noise,
                  "all_arms": {"within_s0_2": proportion(tot["k"], tot["n"]),
                               "confirm_task_flips": proportion(fl["k"], fl["n"])}},
                 provenance_info=prov,
                 summary=f"seeds 0-2 disagree in {tot['k']}/{tot['n']} cells; "
                         f"{fl['k']}/{fl['n']} promoted task outcomes flip on seeds 3-5")


# Phase 3 round 3, dollars per retained proposal (reports/phase3/round3.md).
CRITIC_USD_PER_PROPOSAL = {"new": 0.002676, "v1_structured": 0.006492}


def test_cost_estimate(sets, records, arm: str, scored: dict[str, Any]) -> dict[str, Any]:
    """D72 item 3: planning estimate for the one-time test scoring of ``arm``. Built from
    dev measurements only; reads nothing from the test split. Test sets follow the same
    rules (12 failures per class; 5 held-out; regression = every passing qa task of the
    split, 40 - 20 dev = 20 by the datasheet's task counts, plus 3 per other family)."""
    patches, _ = critic_arm(sets, arm)
    fx = by_failure(sets)
    b = scored["by_outcome"][PRIMARY]
    promoted = [r["failure_id"] for r in b["per_failure_rows"] if r["gate"]["promoted"]]
    groups = {"critic runs s0-2": unique(specs(sets, patches)),
              "no-patch references": unique(reference_specs(sets, fx)),
              "confirmations s3-5": unique([x for k in promoted for x in failure_specs(
                  fx[k], patches[k], reg(sets), CONFIRM_SEEDS)])}
    dev = {}
    for name, ss in groups.items():
        recs = [records[k] for k in ss if k in records]
        dev[name] = {"runs": len(recs), "usd": round(sum(r["cost_usd"] for r in recs), 4),
                     "qwen_runs": sum(r["provider"] == "ollama" for r in recs)}
    n_dev = len(sets["failures"])
    n_test = 60                       # 12 per class, before any label-based exclusion
    test_reg = 20 + 9
    scale = (n_test / n_dev) * ((1 + 5 + test_reg) / (1 + 5 + len(reg(sets))))
    runs_usd = sum(v["usd"] for v in dev.values()) * scale
    critic_usd = n_test * CRITIC_USD_PER_PROPOSAL[arm]
    qwen_h = sum(v["qwen_runs"] for v in dev.values()) * scale * 4.4 / 3600  # 13.6 runs/min seen
    return {"arm": arm, "dev_measured": dev, "assumptions": {
                "test_failures": n_test, "test_regression_tasks": test_reg,
                "scale_vs_dev": round(scale, 3),
                "promotion_rate_as_dev": f"{len(promoted)}/{len(b['per_failure_rows'])}",
                "critic_usd_per_proposal": CRITIC_USD_PER_PROPOSAL[arm],
                "qwen_s_per_run": 4.4},
            "est_critic_proposals_usd": round(critic_usd, 3),
            "est_agent_runs_usd": round(runs_usd, 3),
            "est_total_usd": round(critic_usd + runs_usd, 2),
            "est_qwen_hours": round(qwen_h, 1),
            "note": "Estimate only; nothing was run on test. H6 is not part of test scoring."}


def _line(name, s) -> str:
    b = s["by_outcome"][PRIMARY]
    a, d = b["summary_per_failure"]["all"], b["summary_per_distinct_patch"]["all"]
    return (f"{name} (A1 outcome, A2 regression): per failure H1 {a['H1_repair']['k']}/"
            f"{a['n_patches']}, H2 {a['H2_generalize']['k']}, H3 {a['H3_regress']['k']}, gate "
            f"{a['gate_promoted']['k']}, gate false promotions {b['H4']['gate_false_promotions']}; "
            f"distinct patches {d['n_distinct']} (H1 {d['H1_repair']['k']}, H3 "
            f"{d['H3_regress']['k']})")


# -- CLI ----------------------------------------------------------------------------

def run_set(sets, which: str, arm_names) -> list[RunSpec]:
    if which == "generic":
        g = generic_hallucination(sets)
        return [*reference_specs(sets, g), *specs(sets, g), *specs(sets, g, CONFIRM_SEEDS)]
    if which == "arms":
        out: list[RunSpec] = []
        for arm in arm_names:
            patches, _ = critic_arm(sets, arm)
            out += [*reference_specs(sets, patches), *specs(sets, patches)]
        return out
    if which == "confirm":
        recs = RunStore(RUNS_PATH).by_id
        out = []
        for arm in arm_names:
            patches, props = critic_arm(sets, arm)
            s = score_arm(sets, recs, patches, props)["by_outcome"][PRIMARY]
            fx = by_failure(sets)
            out += [x for r in s["per_failure_rows"] if r["gate"]["promoted"]
                    for x in failure_specs(fx[r["failure_id"]], patches[r["failure_id"]],
                                           reg(sets), CONFIRM_SEEDS)]
        return out
    raise ValueError(which)


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--plan", action="store_true")
    g.add_argument("--run", choices=["generic", "arms", "confirm"])
    g.add_argument("--score", action="store_true")
    ap.add_argument("--arm", choices=list(ARMS), action="append")
    ap.add_argument("--only", choices=["generic", "seed_noise"], default=None,
                    help="with --score: write only the generic A2 result, or only "
                         "heal_seed_noise_dev.json")
    ap.add_argument("--env-file", default=None)
    args = ap.parse_args()
    sets = load_sets()
    arm_names = args.arm or list(ARMS)
    if args.plan:
        done = set(RunStore(RUNS_PATH).by_id)
        for which in ("generic", "arms"):
            print(which, estimate(unique(run_set(sets, which, arm_names)), done))
        for arm in arm_names:
            p, _ = critic_arm(sets, arm)
            print(arm, estimate(unique([*reference_specs(sets, p), *specs(sets, p)]), done))
        return 0
    if args.run:
        h = Harness(env_file=args.env_file, cap_usd=REST_CAP_USD - H6_RESERVE_USD)
        print(args.run, h.run_all(run_set(sets, args.run, arm_names)))
        print(f"rest-of-phase ledger total ${h.ledger.total():.4f} (arm cap ${h.ledger.cap_usd:.2f}, "
              f"phase cap ${REST_CAP_USD:.2f})")
        return 0
    write_results(sets, RunStore(RUNS_PATH).by_id, args.only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
