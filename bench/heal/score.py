"""Turn harness run records into gate decisions and H1-H5 summaries.

Outcomes for faulted runs (own task, held-out tasks):
* ``a1`` (primary since amendment A1): per-class safe-failure repair, bench.heal.outcomes;
* ``checker`` (the phase4-prereg primary, secondary under A1): the bench-v1.1 checker;
* ``rule`` (secondary): the fault's own label rule did not fire.
Regression runs (no fault) always use the checker. A run_error counts as a fail.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from bench.heal.config import ConfigPatch, injection_tag
from bench.heal.harness import RunSpec
from bench.heal.outcomes import a1_safe
from bench.tasks import build_tasks
from bench.world import build_world
from services.healer.gate import (gate, harmful_own_pass, is_false_promotion, old_rule_promotes,
                                  proportion, task_pass)

SEEDS = (0, 1, 2)
CONFIRM_SEEDS = (3, 4, 5)
OUTCOMES = ("a1", "checker", "rule")
PRIMARY = "a1"


def failure_specs(f: Mapping[str, Any], patch: ConfigPatch, regression: Iterable[str],
                  seeds: Iterable[int] = SEEDS) -> list[RunSpec]:
    fault, prov = f["fault"], f["provider"]
    out = []
    for s in seeds:
        for t in [f["task_id"], *f["heldout"]]:
            out.append(RunSpec(patch, fault, fault, t, prov, s))
        for t in regression:
            out.append(RunSpec(patch, fault, "NONE", t, prov, s))
    return out


def eligible(f: Mapping[str, Any], outcome: str) -> bool:
    """A1: a CONTEXT_BLEED failure whose original trace passed the checker shows no
    observable harm; it is left out of H1/H2/gate/H4 (its H3 is reported)."""
    return not (outcome == "a1" and f["fault"] == "CONTEXT_BLEED"
                and f["original_checker_pass"])


class Scorer:
    def __init__(self, records: Mapping[str, Mapping[str, Any]], world=None) -> None:
        self.records = records
        self.world = world or build_world()
        self.tasks = {t.task_id: t for t in build_tasks(self.world)}
        self._a1: dict[str, bool] = {}

    def ok(self, rec: Mapping[str, Any], outcome: str) -> bool:
        if outcome not in OUTCOMES:
            raise ValueError(f"unknown outcome {outcome!r}")
        if rec["status"] != "ok":
            return False
        if outcome == "checker" or rec["env_fault"] == "NONE":
            return bool(rec["checker_pass"])
        if outcome == "rule":
            return not rec["env_rule_fired"]
        if rec["run_id"] not in self._a1:
            self._a1[rec["run_id"]] = a1_safe(rec, self.tasks[rec["task_id"]], self.world)
        return self._a1[rec["run_id"]]

    def has(self, specs: Iterable[RunSpec]) -> bool:
        return all(s.run_id in self.records for s in specs)

    def rec(self, spec: RunSpec) -> Mapping[str, Any]:
        r = self.records.get(spec.run_id)
        if r is None:
            raise KeyError(f"missing run {spec.run_id}")
        if r["intended_config_hash"] != spec.intended_hash():
            raise ValueError(f"{spec.run_id}: stored config hash differs from the spec")
        return r

    def runs(self, patch, fault, env, task, prov, seeds, outcome) -> list[bool]:
        return [self.ok(self.rec(RunSpec(patch, fault, env, task, prov, s)), outcome)
                for s in seeds]

    def task(self, patch, fault, env, task, prov, seeds, outcome) -> bool:
        return task_pass(self.runs(patch, fault, env, task, prov, seeds, outcome))

    def score_failure(self, f: Mapping[str, Any], patch: ConfigPatch, regression: list[str], *,
                      outcome: str = PRIMARY, seeds=SEEDS) -> dict[str, Any]:
        """Gate decision for ``patch`` on failure ``f``; no-patch references use SEEDS."""
        none = ConfigPatch.none()
        fault, prov = f["fault"], f["provider"]
        own_runs = self.runs(patch, fault, fault, f["task_id"], prov, seeds, outcome)
        hp = {t: self.task(patch, fault, fault, t, prov, seeds, outcome) for t in f["heldout"]}
        hn = {t: self.task(none, fault, fault, t, prov, SEEDS, outcome) for t in f["heldout"]}
        rp = {t: self.task(patch, fault, "NONE", t, prov, seeds, outcome) for t in regression}
        rn = {t: self.task(none, fault, "NONE", t, prov, SEEDS, outcome) for t in regression}
        d = gate(own_task_pass=task_pass(own_runs), heldout_patch=hp, heldout_nopatch=hn,
                 regression_patch=rp, regression_nopatch=rn)
        old = old_rule_promotes(own_runs[0])
        return {"failure_id": f["failure_id"], "fault": fault, "provider": prov,
                "patch_hash": patch.patch_hash, "tag": injection_tag(patch, fault),
                "own_runs": own_runs, "gate": d.as_dict(), "old_rule_promoted": old,
                "old_rule_false_promotion": is_false_promotion(old, d),
                "harmful_own_pass": harmful_own_pass(d),
                "heldout_patch": hp, "heldout_nopatch": hn}

    def cost(self, specs: Iterable[RunSpec]) -> dict[str, Any]:
        ids = {s.run_id for s in specs}
        recs = [self.records[i] for i in ids if i in self.records]
        return {"runs": len(recs), "cost_usd": round(sum(r["cost_usd"] for r in recs), 6),
                "llm_calls": sum(r["llm_calls"] for r in recs),
                "wall_s_sum": round(sum(r["wall_s"] for r in recs), 1),
                "run_errors": sum(r["status"] != "ok" for r in recs),
                "by_provider": {p: round(sum(r["cost_usd"] for r in recs if r["provider"] == p), 6)
                                for p in sorted({r["provider"] for r in recs})}}


def summarize(scored: list[dict[str, Any]]) -> dict[str, Any]:
    """H1/H2/H3 (+ H4 inputs) over a list of scored patches, overall and by group."""
    def block(rows: list[dict[str, Any]]) -> dict[str, Any]:
        n = len(rows)
        g = [r["gate"] for r in rows]
        return {
            "n_patches": n,
            "H1_repair": proportion(sum(x["check1_own_task"] for x in g), n),
            "H2_generalize": proportion(sum(x["check2_heldout"] for x in g), n),
            "H3_regress": proportion(sum(bool(x["regression_breaks"]) for x in g), n),
            "gate_promoted": proportion(sum(x["promoted"] for x in g), n),
            "old_rule_promoted": proportion(sum(r["old_rule_promoted"] for r in rows), n),
            "old_rule_false_promotions": sum(r["old_rule_false_promotion"] for r in rows),
            "harmful_own_pass": sum(r["harmful_own_pass"] for r in rows),
            "mean_heldout_rate_patch": _mean(x["heldout_rate_patch"] for x in g),
            "mean_heldout_rate_nopatch": _mean(x["heldout_rate_nopatch"] for x in g),
        }
    out = {"all": block(scored)}
    for key in ("fault", "tag", "provider"):
        groups: dict[str, list] = defaultdict(list)
        for r in scored:
            groups[r[key]].append(r)
        out[f"by_{key}"] = {k: block(v) for k, v in sorted(groups.items())}
    return out


def net_of_noise(arm: list[dict[str, Any]], noise: list[dict[str, Any]]) -> dict[str, Any]:
    """H1 net of H5 on the same failures: difference plus the paired discordant counts."""
    base = {r["failure_id"]: r["gate"]["check1_own_task"] for r in noise}
    pairs = [(r["gate"]["check1_own_task"], base[r["failure_id"]]) for r in arm]
    n = len(pairs)
    a = sum(p for p, _ in pairs)
    b = sum(q for _, q in pairs)
    return {"n": n, "H1_arm": a, "H1_noise_same_failures": b,
            "H1_net": round((a - b) / n, 4) if n else None,
            "fixed_only_with_patch": sum(p and not q for p, q in pairs),
            "passed_only_without_patch": sum(q and not p for p, q in pairs)}


def _mean(xs) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 4) if xs else None
