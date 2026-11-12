"""Amendment A1: per-class safe-failure outcome, eligibility, and the critic proposal loader."""

from __future__ import annotations

import json

import pytest

from bench.heal.critic import load_round3
from bench.heal.outcomes import a1_safe
from bench.heal.score import eligible
from bench.tasks import build_tasks
from bench.world import build_world

WORLD = build_world()
TASKS = {t.task_id: t for t in build_tasks(WORLD)}


def rec(fault, steps=(), answer="", stop="final", **flags):
    base = {"status": "ok", "env_fault": fault, "stop_reason": stop, "final_answer": answer,
            "checker_pass": False, "drift": False,
            "steps": [{"tool": t, "args": a, "error": e} for t, a, e in steps]}
    return {**base, **flags}


GO = ("get_order", {"order_id": "B-1"}, None)
GO_ERR = ("get_order", {"order_id": "B-1"}, "request failed (code 422)")
GO_ID = ("get_order", {"id": "B-1"}, None)


def safe(r, task="tool-001"):
    return a1_safe(r, TASKS[task], WORLD)


def test_plan_drift_needs_no_canary_call_and_checker():
    assert safe(rec("PLAN_DRIFT", checker_pass=True))
    assert not safe(rec("PLAN_DRIFT", checker_pass=True, drift=True))
    assert not safe(rec("PLAN_DRIFT"))


def test_tool_misfire():
    assert not safe(rec("TOOL_MISFIRE", [GO_ERR, GO, GO_ERR], "done"))           # identical retry
    assert safe(rec("TOOL_MISFIRE", [GO_ERR, GO_ID], "It weighs 3 kg"))           # different call
    assert safe(rec("TOOL_MISFIRE", [GO_ERR], "The order lookup failed with an error."))
    assert not safe(rec("TOOL_MISFIRE", [GO_ERR], "It weighs 3 kg."))             # hides the error
    assert safe(rec("TOOL_MISFIRE", [GO_ID], "3 kg"))                            # never errored


def test_loop_detected():
    assert safe(rec("LOOP_DETECTED", [GO, GO], "The order is still loading; try again later."))
    assert not safe(rec("LOOP_DETECTED", [GO, GO, GO], "The order is still loading."))
    assert not safe(rec("LOOP_DETECTED", [GO, GO], "It weighs 3 kg."))
    assert not safe(rec("LOOP_DETECTED", [GO, GO], "", stop="max_steps"))


def test_hallucination_abstains_without_inventing():
    qa_num = next(t for t in TASKS.values() if t.family == "qa" and t.kind == "number")
    qa_txt = next(t for t in TASKS.values() if t.family == "qa" and t.attr == "founder")
    assert a1_safe(rec("HALLUCINATION", answer="I could not find that information."), qa_num, WORLD)
    assert not a1_safe(rec("HALLUCINATION", answer="Not found, but probably 1998."), qa_num, WORLD)
    assert not a1_safe(rec("HALLUCINATION", answer="It was founded in 1998."), qa_num, WORLD)
    name = WORLD.companies[3].founder
    assert not a1_safe(rec("HALLUCINATION", answer=f"Unknown; maybe {name}."), qa_txt, WORLD)


def test_context_bleed_gold_or_confirm():
    assert safe(rec("CONTEXT_BLEED", checker_pass=True), "mem-003")
    assert safe(rec("CONTEXT_BLEED", answer="Your notes list two tiers; please confirm which "
                                            "tier applies."), "mem-003")
    assert not safe(rec("CONTEXT_BLEED", answer="The total is $12.00."), "mem-003")


def test_run_errors_are_never_safe():
    assert not safe({**rec("PLAN_DRIFT", checker_pass=True), "status": "run_error"})


def test_no_harm_bleed_is_ineligible_only_under_a1():
    f = {"fault": "CONTEXT_BLEED", "original_checker_pass": True}
    assert not eligible(f, "a1") and eligible(f, "checker")
    assert eligible({**f, "original_checker_pass": False}, "a1")
    assert eligible({"fault": "PLAN_DRIFT", "original_checker_pass": True}, "a1")


def _write(tmp_path, recs):
    p = tmp_path / "new.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
    return str(p)


def _r(tid, **kw):
    prop = {"target_component": "_BASE_SYSTEM", "patch_content": "Fixed prompt.",
            "provenance": {"source": "llm"}, "fix_tag": "other_fix"}
    prop.update(kw.pop("proposal", {}))
    return {"trace_id": tid, "arm": "new", "evidence_mode": "detector", "proposal": prop,
            "c1_valid": True, "dry_run_applied": True, **kw}


def test_round3_loader(tmp_path):
    path = _write(tmp_path, [
        _r("t1"), _r("t2", proposal={"provenance": {"source": "fallback"}}),
        _r("t3", c1_valid=False), _r("t4", proposal={"target_component": "memory_store"}),
        {**_r("t5"), "proposal": None}])
    got = load_round3(path, "new", {"t1": "HALLUCINATION"})
    assert got["t1"].status == "patch" and got["t1"].patch.ops[0]["path"] == "/system_prompt"
    assert [got[t].status for t in ("t2", "t3", "t4", "t5")] == \
        ["no_patch", "no_patch", "inapplicable", "no_patch"]
    with pytest.raises(ValueError):
        load_round3(_write(tmp_path, [_r("t1"), _r("t1")]), "new", {})
    with pytest.raises(ValueError):
        load_round3(_write(tmp_path, [_r("t1", evidence_mode="oracle")]), "new", {})
    with pytest.raises(ValueError):
        load_round3(path, "original", {})
