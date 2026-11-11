"""Scoring: stored run records -> gate decisions, H1-H3 and H5-net summaries."""

from __future__ import annotations

import pytest

from bench.heal.config import ConfigPatch
from bench.heal.score import SEEDS, Scorer, failure_specs, net_of_noise, summarize

F = {"failure_id": "TOOL_MISFIRE|deepseek|tool-001", "fault": "TOOL_MISFIRE",
     "provider": "deepseek", "task_id": "tool-001", "heldout": ["plan-003", "mem-010"]}
REG = ["qa-007", "tool-022"]
NONE = ConfigPatch.none()
FIX = ConfigPatch(ops=({"op": "replace", "path": "/TOOL_SPECS/1/description",
                        "value": "Pass the id as `id`."},), source="t")


def records(outcome_fn):
    recs = {}
    for patch in (NONE, FIX):
        for spec in failure_specs(F, patch, REG, SEEDS):
            ok = outcome_fn(patch, spec)
            recs[spec.run_id] = {"run_id": spec.run_id, "status": "ok", "checker_pass": ok,
                                 "env_fault": spec.env_fault, "env_rule_fired": not ok,
                                 "intended_config_hash": spec.intended_hash(),
                                 "cost_usd": 0.001, "llm_calls": 4, "wall_s": 1.0,
                                 "provider": spec.provider}
    return recs


def outcome(patch, spec):
    if spec.env_fault == "NONE":
        # The fix breaks tool-022 on clean runs (P20-style), and only on seeds 0-1.
        return not (patch is FIX and spec.task_id == "tool-022" and spec.seed < 2)
    if patch is NONE:
        return spec.task_id == "mem-010" and spec.seed == 0   # noise: 1/3, not a task pass
    return spec.task_id != "mem-010"


def test_gate_from_records():
    sc = Scorer(records(outcome))
    noise = sc.score_failure(F, NONE, REG)
    fix = sc.score_failure(F, FIX, REG)
    assert not noise["gate"]["check1_own_task"] and not noise["gate"]["check2_heldout"]
    assert noise["gate"]["regression_breaks"] == [] and noise["tag"] == "none"
    g = fix["gate"]
    assert g["check1_own_task"] and g["check2_heldout"] and not g["promoted"]
    assert g["regression_breaks"] == ["tool-022"] and fix["harmful_own_pass"]
    assert fix["old_rule_promoted"] and fix["old_rule_false_promotion"]
    assert fix["tag"] == "other_fix"
    s = summarize([fix])
    assert s["all"]["H1_repair"]["k"] == 1 and s["all"]["H3_regress"]["k"] == 1
    assert s["all"]["gate_promoted"]["k"] == 0
    assert s["all"]["H1_repair"]["ci95_clopper_pearson"] == (0.025, 1.0)
    net = net_of_noise([fix], [noise])
    assert net["H1_net"] == 1.0 and net["fixed_only_with_patch"] == 1


def test_run_errors_count_as_failures_and_missing_runs_raise():
    recs = records(lambda p, s: True)
    sc = Scorer(recs)
    assert sc.score_failure(F, FIX, REG)["gate"]["check1_own_task"]
    for spec in failure_specs(F, FIX, REG, SEEDS):
        if spec.task_id == F["task_id"] and spec.seed < 2:
            recs[spec.run_id]["status"] = "run_error"
    assert not Scorer(recs).score_failure(F, FIX, REG)["gate"]["check1_own_task"]
    del recs[next(iter(recs))]
    with pytest.raises(KeyError):
        Scorer(recs).score_failure(F, NONE, REG)


def test_stored_hash_must_match_the_spec():
    recs = records(lambda p, s: True)
    next(iter(recs.values()))["intended_config_hash"] = "0" * 64
    with pytest.raises(ValueError):
        Scorer(recs).score_failure(F, NONE, REG)
