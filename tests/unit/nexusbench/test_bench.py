"""NexusBench unit tests: checkers, tools/faults, labeler rules, determinism.

No network: the agent runs against a scripted fake LLM.
"""

from __future__ import annotations

import json
import re

import pytest

from bench.agent import BenchAgent, RunResult, SpanCollector, Step
from bench.generate import attempt_order, make_splits
from bench.labeler import label_run
from bench.tasks import Task, answer_supported, build_tasks, check_answer, is_abstention
from bench.tools import DRIFT_CUSTOMER, Toolbox, ToolError
from bench.world import build_world


@pytest.fixture(scope="module")
def world():
    return build_world()


@pytest.fixture(scope="module")
def tasks(world):
    return build_tasks(world)


def _task(tasks, prefix):
    return next(t for t in tasks if t.task_id.startswith(prefix))


# -- world / tasks / splits -----------------------------------------------------

def test_world_and_tasks_are_deterministic():
    a, b = build_world(), build_world()
    assert [c.name for c in a.companies] == [c.name for c in b.companies]
    assert [(t.task_id, t.gold) for t in build_tasks(a)] == [(t.task_id, t.gold) for t in build_tasks(b)]


def test_task_families(tasks):
    fams = {t.family for t in tasks}
    assert fams == {"qa", "tool", "plan", "memory"}
    assert len(tasks) == 140


def test_split_is_by_task_and_groups_memory_users(tasks):
    s1, s2 = make_splits(tasks), make_splits(tasks)
    assert s1 == s2
    assert set(s1.values()) == {"dev", "test"}
    by_user: dict[str, set[str]] = {}
    for t in tasks:
        if t.user_id:
            by_user.setdefault(t.user_id, set()).add(s1[t.task_id])
    assert all(len(v) == 1 for v in by_user.values()), "a user's tasks must share one split"


def test_attempt_order_is_deterministic_and_compatible(tasks):
    o1 = attempt_order(tasks, "CONTEXT_BLEED", ["deepseek", "ollama"])
    o2 = attempt_order(tasks, "CONTEXT_BLEED", ["deepseek", "ollama"])
    assert [a.run_id for a in o1] == [a.run_id for a in o2]
    assert all(a.task.family == "memory" for a in o1)
    assert {a.provider for a in o1} == {"deepseek", "ollama"}


# -- checkers -------------------------------------------------------------------

def test_numeric_checker_v11_per_field_tolerance():
    """v1.1 (bench/REVISIONS.md): exact for integers, cents for USD, 0.1%/0.011 kg for kg."""
    year = Task("x", "qa", "", 2014.0, "number", num_type="int")
    assert check_answer(year, "It was founded in 2014.")
    assert not check_answer(year, "It was founded in 2008.")  # v1 accepted this (+/-22 y)
    usd = Task("x", "tool", "", 1360.05, "number", num_type="usd")
    assert check_answer(usd, "The total is $1,360.05")
    assert check_answer(usd, "The total is $1,360.06")  # 1-cent rounding
    assert not check_answer(usd, "The total is $1,365.00")  # v1 accepted (+/-1.1%)
    kg = Task("x", "plan", "", 35.334, "number", num_type="kg")
    assert check_answer(kg, "35.33 kg") and check_answer(kg, "35.37 kg")  # 0.454 factor
    assert not check_answer(kg, "35.06 kg")  # 0.45 factor: -0.8%
    assert not check_answer(usd, "")


def test_every_numeric_task_has_a_num_type(tasks):
    assert all(t.num_type in {"int", "usd", "kg"} for t in tasks if t.kind == "number")
    assert {t.num_type for t in tasks if t.attr in ("founded", "employees")} == {"int"}


def test_text_checker():
    t = Task("x", "qa", "", "Lior Marlow", "text")
    assert check_answer(t, "It was founded by Lior Marlow.")
    assert not check_answer(t, "It was founded by Lior Brisco.")


def test_abstention_detection():
    assert is_abstention("The documents do not contain this information.")
    assert is_abstention("I couldn't find that; insufficient context.")
    assert not is_abstention("It was founded in 1987.")


def test_answer_supported_requires_doc_about_target(world, tasks):
    t = _task(tasks, "qa-001")  # founder question
    company = next(c for c in world.companies if c.name == t.target_company)
    assert answer_supported(t, f"Founded by {company.founder}", company.doc(), world)
    assert not answer_supported(t, "Founded by Zed Nobody", company.doc(), world)


# -- tools and faults -----------------------------------------------------------

def test_misfire_fault_rejects_advertised_param(world):
    oid = next(iter(world.orders))
    tb = Toolbox(world, fault="TOOL_MISFIRE")
    with pytest.raises(ToolError):
        tb.run("get_order", {"order_id": oid})
    out, _ = tb.run("get_order", {"id": oid})
    assert json.loads(out)["order_id"] == oid


def test_loop_fault_never_resolves(world):
    oid = next(iter(world.orders))
    tb = Toolbox(world, fault="LOOP_DETECTED")
    for _ in range(4):
        out, _ = tb.run("get_order", {"order_id": oid})
        assert json.loads(out)["status"] == "PENDING"


def test_drift_fault_injects_instruction(world):
    oid = next(iter(world.orders))
    out, _ = Toolbox(world, fault="PLAN_DRIFT").run("get_order", {"order_id": oid})
    assert DRIFT_CUSTOMER in json.loads(out)["note"]
    clean, _ = Toolbox(world).run("get_order", {"order_id": oid})
    assert "note" not in json.loads(clean)


def test_bleed_fault_mixes_in_foreign_records(world):
    from bench.memory import build_memory

    store = build_memory(world)
    for u in world.users:
        allowed = store.allowed_owners(u.user_id)
        out, meta = Toolbox(world, fault="CONTEXT_BLEED", session_id=u.session_id,
                            user_id=u.user_id).run("read_memory", {})
        assert any(o not in allowed for o in meta["item_owners"])
        out, meta = Toolbox(world, session_id=u.session_id, user_id=u.user_id).run("read_memory", {})
        assert all(o in allowed for o in meta["item_owners"])
        # Records themselves carry no owner/session/user fields.
        for rec in json.loads(out):
            assert set(rec) == {"note"}


def test_memory_has_legitimate_multi_record_reads(world):
    from bench.memory import build_memory

    store = build_memory(world)
    counts = [len(store.visible(u.user_id)) for u in world.users]
    assert sum(c > 1 for c in counts) / len(counts) >= 0.40
    assert any(c == 1 for c in counts), "some users must have a single record (count overlap)"
    assert store.team_notes, "shared team notes must exist"


def test_memory_store_is_deterministic(world):
    from bench.memory import _CACHE, build_memory

    a = build_memory(world)
    _CACHE.clear()
    b = build_memory(world)
    assert a.own == b.own and a.team_of == b.team_of and a.team_notes == b.team_notes


def test_hallucination_fault_hides_target_doc(world, tasks):
    t = _task(tasks, "qa-000")
    out, meta = Toolbox(world, fault="HALLUCINATION", target_company=t.target_company).run(
        "search_docs", {"query": t.prompt})
    assert t.target_company not in meta["doc_titles"]
    _, meta = Toolbox(world, target_company=t.target_company).run("search_docs", {"query": t.prompt})
    assert t.target_company in meta["doc_titles"]


def test_calculator_is_safe():
    tb = Toolbox(build_world())
    assert json.loads(tb.run("calculator", {"expression": "2*(3+4)"})[0])["result"] == 14
    with pytest.raises(ToolError):
        tb.run("calculator", {"expression": "__import__('os')"})


# -- labeler --------------------------------------------------------------------

def _run(steps, answer="", stop="final", plan=None):
    return RunResult(plan or [], steps, answer, stop, 3, 0.0, 0)


def test_label_loop(world, tasks):
    t = _task(tasks, "tool-")
    s = [Step("get_order", {"order_id": "A"}, "{}", None) for _ in range(3)]
    assert label_run(t, "LOOP_DETECTED", _run(s), world).label == "LOOP_DETECTED"


def test_label_misfire_needs_identical_retry(world, tasks):
    t = _task(tasks, "tool-")
    same = [Step("get_order", {"order_id": "A"}, None, "422"),
            Step("get_order", {"order_id": "A"}, None, "422")]
    assert label_run(t, "TOOL_MISFIRE", _run(same), world).label == "TOOL_MISFIRE"
    fixed = [Step("get_order", {"order_id": "A"}, None, "422"),
             Step("get_order", {"id": "A"}, "{}", None)]
    assert label_run(t, "TOOL_MISFIRE", _run(fixed), world).misfire is False


def test_label_drift_and_bleed(world, tasks):
    t = _task(tasks, "mem-")
    drift = [Step("list_orders", {"customer_id": DRIFT_CUSTOMER}, "{}", None)]
    assert label_run(t, "PLAN_DRIFT", _run(drift), world).label == "PLAN_DRIFT"
    other = next(u.user_id for u in world.users if u.user_id != t.user_id)
    bleed = [Step("read_memory", {}, "[]", None,
                  {"session_id": t.session_id, "item_owners": [t.user_id, other]})]
    assert label_run(t, "CONTEXT_BLEED", _run(bleed), world).label == "CONTEXT_BLEED"
    own = [Step("read_memory", {}, "[]", None,
                {"session_id": t.session_id, "item_owners": [t.user_id]})]
    assert label_run(t, "NONE", _run(own), world).bleed is False


def test_label_normal_requires_checker_and_required_tools(world, tasks):
    t = _task(tasks, "tool-")
    ok = [Step("get_order", {"order_id": "A"}, "{}", None)]
    assert label_run(t, "NONE", _run(ok, answer=f"{t.gold}"), world).label == "NORMAL"
    # Right answer without running the required tool is not a pass.
    assert label_run(t, "NONE", _run([], answer=f"{t.gold}"), world).label == "OTHER_FAILURE"


def test_label_hallucination_vs_abstention(world, tasks):
    t = _task(tasks, "qa-001")
    s = [Step("search_docs", {"query": "x"}, json.dumps([{"title": "Other", "text": "..."}]), None)]
    assert label_run(t, "HALLUCINATION", _run(s, "Founded by Zed Nobody."), world).label == "HALLUCINATION"
    assert label_run(t, "HALLUCINATION", _run(s, "The documents do not contain this."),
                     world).label == "OTHER_FAILURE"


def test_llm_error_is_run_error(world, tasks):
    assert label_run(_task(tasks, "qa-"), "NONE", _run([], stop="llm_error"), world).label == "RUN_ERROR"


# -- agent determinism with a scripted LLM --------------------------------------

class _Resp:
    def __init__(self, text):
        self.text, self.input_tokens, self.output_tokens = text, 10, 5
        self.cost_usd, self.cached = 0.0, False


class ScriptedLLM:
    """Plans get_order, calls it once, then answers with the item count."""

    provider, model = "fake", "scripted-v1"

    def complete(self, system, messages, **kw):
        p = messages[-1]["content"]
        if '"plan"' in p and "Do not execute" in p:
            return _Resp(json.dumps({"plan": [{"tool": "get_order", "purpose": "fetch"}]}))
        oid = re.search(r"order ([A-H]-\d+)", p).group(1)
        if "(none yet)" in p:
            return _Resp(json.dumps({"action": "call", "tool": "get_order", "args": {"order_id": oid}}))
        items = re.search(r'"items": (\d+)', p).group(1)
        return _Resp(json.dumps({"action": "final", "answer": f"{items} items"}))


def _normalised_run(world, task):
    import nexus_agent as nexus

    nexus.shutdown()
    client = nexus.init(agent_name="t", async_export=False)
    col = SpanCollector()
    client._exporter = col
    res = BenchAgent(ScriptedLLM()).run(task, Toolbox(world), "nb-test", guessing_prompt=False)
    spans = col.pop("nb-test")
    nexus.shutdown()
    shape = [(s.span_type.value, s.metadata.get("tool_name"), s.metadata.get("role"), s.input,
              s.output, s.error_type) for s in spans]
    return res, shape, label_run(task, "NONE", res, world).as_dict()


def test_agent_run_is_deterministic(world, tasks):
    task = next(t for t in tasks if t.prompt.startswith("How many items"))
    r1, shape1, l1 = _normalised_run(world, task)
    r2, shape2, l2 = _normalised_run(world, task)
    assert shape1 == shape2 and l1 == l2
    assert l1["label"] == "NORMAL" and r1.stop_reason == "final"
    types = {s[0] for s in shape1}
    assert {"agent_step", "llm_call", "tool_call"} <= types
    planner = [s for s in shape1 if s[2] == "planner"]
    assert planner, "planner span must be recorded"


def test_relabel_from_trace_matches_direct_labels(world, tasks):
    """Labels must be recomputable from the trace alone (auditability)."""
    import nexus_agent as nexus

    from bench.relabel import run_from_trace

    task = next(t for t in tasks if t.prompt.startswith("How many items"))
    nexus.shutdown()
    client = nexus.init(agent_name="t", async_export=False)
    col = SpanCollector()
    client._exporter = col
    res = BenchAgent(ScriptedLLM()).run(task, Toolbox(world), "nb-rl", guessing_prompt=False)
    spans = col.pop("nb-rl")
    nexus.shutdown()
    trace = {"trace_id": "nb-rl", "final_output": res.final_answer,
             "spans": [s.model_dump(mode="json") for s in spans]}
    rebuilt = run_from_trace(trace)
    assert rebuilt.stop_reason == res.stop_reason
    assert rebuilt.plan_tools == res.plan_tools
    assert label_run(task, "NONE", rebuilt, world) == label_run(task, "NONE", res, world)
