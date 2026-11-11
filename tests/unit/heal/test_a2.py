"""Amendment A2: per-distinct-patch reporting, A2 arm wiring, H6 kappa."""

from __future__ import annotations

from bench.heal.h6 import kappa, parse
from bench.heal.score import summarize_distinct


def _row(fid, ph, *, c1=True, c2=True, br=(), promoted=None, fault="HALLUCINATION"):
    promoted = (c1 and c2 and not br) if promoted is None else promoted
    return {"failure_id": fid, "fault": fault, "patch_hash": ph, "tag": "other_fix",
            "provider": "deepseek", "old_rule_promoted": c1,
            "old_rule_false_promotion": c1 and not (c2 and not br),
            "harmful_own_pass": c1 and bool(br),
            "gate": {"check1_own_task": c1, "check2_heldout": c2,
                     "regression_breaks": list(br), "promoted": promoted}}


def test_one_diff_on_twelve_failures_is_one_distinct_patch():
    rows = [_row(f"H|deepseek|qa-{i:03d}", "abc") for i in range(12)]
    conf = {r["failure_id"]: {"status": "scored", "false_promotion": False} for r in rows}
    d = summarize_distinct(rows, conf)
    assert d["all"]["n_distinct"] == 1 and d["all"]["failures_covered"] == 12
    assert d["all"]["max_failures_per_patch"] == 12
    assert d["all"]["H1_repair"]["k"] == 1 and d["all"]["gate_promoted"]["k"] == 1
    assert d["patches"][0]["confirmed_failures"] == 12


def test_distinct_patch_needs_every_failure_for_good_and_any_for_bad():
    rows = [_row("a", "p1"), _row("b", "p1", c1=False), _row("c", "p2", br=["qa-001"])]
    conf = {"a": {"status": "scored", "false_promotion": True}}
    d = summarize_distinct(rows, conf)["all"]
    assert d["n_distinct"] == 2
    assert d["H1_repair"]["k"] == 1          # p1 fails check 1 on b; p2 passes it
    assert d["H3_regress"]["k"] == 1         # p2 breaks a regression task
    assert d["gate_false_promotions"] == 1   # p1's promotion on a failed confirmation
    assert d["harmful_own_pass"] == 1


def test_same_diff_on_two_faults_is_two_experiments():
    rows = [_row("a", "p", fault="HALLUCINATION"), _row("b", "p", fault="TOOL_MISFIRE")]
    assert summarize_distinct(rows)["all"]["n_distinct"] == 2


def test_kappa_and_verdict_parse():
    assert kappa([(True, True), (False, False)] * 5) == 1.0
    assert kappa([(True, False), (False, True)] * 5) == -1.0
    assert parse('{"verdict": "PASS"}') == "pass" and parse("nope") is None
