"""Harness: equivalence with the frozen agent, run identity, idempotency, sealing, budget."""

from __future__ import annotations

import json
import re

import pytest

import nexus_agent as nexus
from bench.agent import BenchAgent, SpanCollector
from bench.heal import harness as H
from bench.heal.agent import ConfiguredAgent
from bench.heal.config import ConfigPatch, clean_config, faulted_config
from bench.heal.sets import SealedSplitError
from bench.llm import BudgetExceeded, LLMResponse
from bench.tasks import build_tasks
from bench.tools import Toolbox
from bench.world import build_world

DEV_TOOL_TASK = "tool-001"   # dev split (in the pre-registered regression set)
DEV_QA_TASK = "qa-007"


class FakeLLM:
    """Deterministic scripted model: plan, one get_order/search call, then a final answer."""

    provider, model = "deepseek", "fake"

    def __init__(self, cost: float = 0.0) -> None:
        self.calls: list[tuple[str, str]] = []
        self.cost = cost

    def complete(self, system, messages, **kw) -> LLMResponse:
        prompt = messages[0]["content"]
        self.calls.append((system, prompt))
        if "Write a short plan" in prompt:
            text = json.dumps({"plan": [{"tool": "get_order", "purpose": "look up"}]})
        elif "(none yet)" in prompt:
            m = re.search(r"order ([A-Z]-\d+)", prompt)
            text = json.dumps({"action": "call", "tool": "get_order",
                               "args": {"order_id": m.group(1) if m else "B-0000"}})
        else:
            text = json.dumps({"action": "final", "answer": "The answer is 3."})
        return LLMResponse(text, self.provider, self.model, 10, 5, self.cost, False, 1.0)


@pytest.fixture
def collector():
    nexus.shutdown()
    client = nexus.init(agent_name="t", async_export=False, environment="test")
    c = SpanCollector()
    client._exporter = c
    yield c
    nexus.shutdown()


@pytest.mark.parametrize("fault", ["NONE", "HALLUCINATION"])
def test_configured_agent_sends_identical_requests(collector, fault):
    world = build_world()
    task = next(t for t in build_tasks(world) if t.task_id == DEV_TOOL_TASK)
    a, b = FakeLLM(), FakeLLM()
    BenchAgent(a, seed=1).run(task, Toolbox(world), "t1", guessing_prompt=fault == "HALLUCINATION")
    agent = ConfiguredAgent(b, seed=1)
    agent.run(task, Toolbox(world), "t2", config=faulted_config(fault))
    assert a.calls == b.calls and len(a.calls) >= 3
    assert agent.effective_config_hash() == H.config_hash(faulted_config(fault))


def test_configured_agent_uses_the_patched_values(collector):
    world = build_world()
    task = next(t for t in build_tasks(world) if t.task_id == DEV_TOOL_TASK)
    cfg = clean_config()
    cfg["system_prompt"] = "PATCHED"
    cfg["TOOL_SPECS"][1]["description"] = "DESC-PATCHED"
    cfg["MAX_STEPS"] = 1
    llm = FakeLLM()
    res = ConfiguredAgent(llm, seed=0).run(task, Toolbox(world), "t3", config=cfg)
    assert {s for s, _ in llm.calls} == {"PATCHED"}
    assert all("DESC-PATCHED" in p for _, p in llm.calls)
    assert res.stop_reason == "max_steps" and len(res.steps) == 1


def make_harness(tmp_path, cost=0.0, cap=1.5):
    llm = FakeLLM(cost)
    h = H.Harness(runs_path=str(tmp_path / "runs.jsonl"), state_dir=str(tmp_path / "state"),
                  cap_usd=cap, clients={"deepseek": llm, "ollama": llm})
    return h, llm


def specs(patch, seeds=(0, 1, 2)):
    return [H.RunSpec(patch, "TOOL_MISFIRE", env, t, "deepseek", s)
            for s in seeds for env, t in (("TOOL_MISFIRE", DEV_TOOL_TASK), ("NONE", DEV_QA_TASK))]


def test_runs_are_recorded_resumable_and_idempotent(tmp_path):
    h, llm = make_harness(tmp_path)
    none = ConfigPatch.none()
    st = h.run_all(specs(none) + specs(none), progress=False)   # duplicates collapse
    assert st == {"requested": 6, "already_done": 0, "ran": 6, "run_error": 0}
    n_calls = len(llm.calls)
    h2, llm2 = make_harness(tmp_path)                            # fresh process, same store
    assert h2.run_all(specs(none), progress=False)["ran"] == 0 and not llm2.calls
    recs = list(h2.records().values())
    assert len(recs) == 6 and n_calls > 0
    for r in recs:
        assert r["applied_config_hash"] == r["intended_config_hash"]
        assert r["patch_hash"][:16] in r["run_id"]
        assert {"cost_usd", "wall_s", "checker_pass", "label", "steps"} <= set(r)
    # The TOOL_MISFIRE backend rejects order_id: the scripted model fails its own task.
    own = [r for r in recs if r["env_fault"] == "TOOL_MISFIRE"]
    assert all(not r["checker_pass"] for r in own)


def test_a_different_patch_gets_new_run_ids(tmp_path):
    h, _ = make_harness(tmp_path)
    h.run_all(specs(ConfigPatch.none()), progress=False)
    p = ConfigPatch(ops=({"op": "replace", "path": "/MAX_STEPS", "value": 9},))
    assert h.run_all(specs(p), progress=False)["ran"] == 6
    assert len(h.records()) == 12


def test_reused_run_id_with_another_config_is_refused(tmp_path):
    h, _ = make_harness(tmp_path)
    h.run_all(specs(ConfigPatch.none(), seeds=(0,)), progress=False)
    path = tmp_path / "runs.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[0])
    rec["intended_config_hash"] = "f" * 64
    path.write_text("\n".join([json.dumps(rec), *lines[1:]]) + "\n", encoding="utf-8")
    h2, _ = make_harness(tmp_path)
    with pytest.raises(H.RunIdCollision):
        h2.run_all(specs(ConfigPatch.none(), seeds=(0,)), progress=False)
    # A store that holds one id twice is refused on load.
    path.write_text(lines[0] + "\n" + lines[0] + "\n", encoding="utf-8")
    with pytest.raises(H.RunIdCollision):
        H.RunStore(str(path))


def test_applied_config_must_equal_intended(tmp_path, monkeypatch):
    class Drifting(ConfiguredAgent):
        def run(self, task, toolbox, trace_id, *, config):
            return super().run(task, toolbox, trace_id, config={**config, "MAX_STEPS": 7})

    monkeypatch.setattr(H, "ConfiguredAgent", Drifting)
    h, _ = make_harness(tmp_path)
    with pytest.raises(H.ConfigMismatch):
        h.run_all(specs(ConfigPatch.none(), seeds=(0,)), progress=False)
    assert not h.records()


def test_test_split_is_sealed(tmp_path):
    h, llm = make_harness(tmp_path)
    test_task = next(t for t, s in h.splits.items() if s == "test")
    with pytest.raises(SealedSplitError):
        h.run_all([H.RunSpec(ConfigPatch.none(), "NONE", "NONE", test_task, "deepseek", 0)],
                  progress=False)
    assert not llm.calls


def test_spend_cap_stops_the_run(tmp_path):
    ledger = H.PhaseLedger(str(tmp_path / "l.jsonl"), cap_usd=0.01)
    ledger.append({"provider": "deepseek", "model": "m", "cost_usd": 0.009,
                   "input_tokens": 0, "output_tokens": 0})
    ledger.check("ollama", "m", 5.0)  # local model is free
    with pytest.raises(BudgetExceeded):
        ledger.check("deepseek", "m", 0.002)
    ledger.append({"provider": "gemini", "model": "m", "cost_usd": 0.0005,
                   "input_tokens": 0, "output_tokens": 0})
    with pytest.raises(BudgetExceeded):   # the cap is over all providers
        ledger.check("deepseek", "m", 0.0006)
