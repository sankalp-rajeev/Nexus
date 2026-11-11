"""The NexusBench agent, driven by an explicit config instead of module constants.

``bench/agent.py`` is frozen benchmark code (its traces are hashed in the test
manifest), so it is not edited. ``ConfiguredAgent.run`` is the same planner ->
actor loop with the three config values passed in. With ``clean_config()`` or
``faulted_config("HALLUCINATION")`` it sends byte-identical LLM requests to
``BenchAgent.run`` (``tests/unit/heal/test_harness.py`` checks this).

The agent records the config it actually used (the system prompt string sent
with every LLM call, the step budget it enforced and the tool list it rendered)
so the harness can assert that the applied config is the intended one.
"""

from __future__ import annotations

import json
from typing import Any

from langgraph.graph import END, StateGraph

import nexus_agent as nexus
from nexus_agent.client import _current_trace_id
from nexus_agent.models import SpanType

from bench.agent import BenchAgent, RunResult, Step, _parse_json, _State
from bench.heal.config import CONFIG_KEYS, config_hash
from bench.tasks import Task
from bench.tools import Toolbox


def tool_block(specs: list[dict[str, Any]]) -> str:
    lines = []
    for t in specs:
        args = ", ".join(f"{k}: {v}" for k, v in t["args"].items()) or "no arguments"
        lines.append(f"- {t['name']}({args}): {t['description']}")
    return "Available tools:\n" + "\n".join(lines)


class ConfiguredAgent(BenchAgent):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.systems_sent: set[str] = set()
        self.effective: dict[str, Any] | None = None

    def _ask(self, system: str, prompt: str, role: str, acc: dict[str, Any]) -> str:
        self.systems_sent.add(system)
        return super()._ask(system, prompt, role, acc)

    def effective_config_hash(self) -> str:
        """Hash of the config the run actually used; raises if prompts disagree with it."""
        if self.effective is None:
            raise RuntimeError("run() has not been called")
        if self.systems_sent and self.systems_sent != {self.effective["system_prompt"]}:
            raise RuntimeError("LLM calls used a system prompt other than the config's")
        return config_hash(self.effective)

    def run(self, task: Task, toolbox: Toolbox, trace_id: str, *,  # type: ignore[override]
            config: dict[str, Any]) -> RunResult:
        system: str = config["system_prompt"]
        max_steps: int = config["MAX_STEPS"]
        specs: list[dict[str, Any]] = json.loads(json.dumps(config["TOOL_SPECS"]))
        tools_txt = tool_block(specs)
        self.effective = {"system_prompt": system, "MAX_STEPS": max_steps, "TOOL_SPECS": specs}
        assert set(self.effective) == set(CONFIG_KEYS)

        acc: dict[str, Any] = {"llm_calls": 0, "cost": 0.0, "invalid": 0}
        steps: list[Step] = []

        def plan_node(state: _State) -> _State:
            prompt = (
                f"{tools_txt}\n\nTask: {task.prompt}\n\n"
                "Write a short plan before acting. Respond with JSON: "
                '{"plan": [{"tool": "<tool name>", "purpose": "<why>"}]}. '
                "Use only the tools listed. Do not execute anything yet."
            )
            with nexus.span(SpanType.AGENT_STEP, input=task.prompt, role="planner") as ps:
                text = self._ask(system, prompt, "planner", acc)
                obj = _parse_json(text) or {}
                plan = [p for p in obj.get("plan", []) if isinstance(p, dict) and p.get("tool")]
                if not obj:
                    acc["invalid"] += 1
                ps.set_output(json.dumps(plan))
                ps.set_metadata({"plan_steps": [str(p.get("tool")) for p in plan]})
            return {"plan": plan, "history": [], "final": None, "stop": None}

        def act_node(state: _State) -> _State:
            history = list(state.get("history", []))
            hist_txt = "\n".join(
                f"{i + 1}. {h['tool']}({json.dumps(h['args'])}) -> {h['result']}"
                for i, h in enumerate(history)) or "(none yet)"
            plan_txt = json.dumps(state.get("plan", []))
            prompt = (
                f"{tools_txt}\n\nTask: {task.prompt}\n\nYour plan: {plan_txt}\n\n"
                f"Actions so far:\n{hist_txt}\n\n"
                "Decide the next action. Respond with JSON, either "
                '{"action": "call", "tool": "<tool name>", "args": {...}} or '
                '{"action": "final", "answer": "<answer for the user>"}.'
            )
            with nexus.span(SpanType.AGENT_STEP, input=f"step {len(history) + 1}", role="actor"):
                text = self._ask(system, prompt, "actor", acc)
                obj = _parse_json(text)
                if obj is None:
                    acc["invalid"] += 1
                    history.append({"tool": "invalid_json", "args": {}, "result": "ERROR: "
                                    "your last reply was not valid JSON"})
                elif obj.get("action") == "final" or ("answer" in obj and "tool" not in obj):
                    return {**state, "history": history, "final": str(obj.get("answer", "")),
                            "stop": "final"}
                else:
                    tool = str(obj.get("tool", ""))
                    args = obj.get("args") if isinstance(obj.get("args"), dict) else {}
                    result, err, meta = self._exec(toolbox, tool, args)
                    steps.append(Step(tool, args, None if err else result, err, meta))
                    history.append({"tool": tool, "args": args, "result": result})
            if len(history) >= max_steps:
                return {**state, "history": history, "final": "", "stop": "max_steps"}
            return {**state, "history": history}

        def route(state: _State) -> str:
            return END if state.get("stop") else "act"

        g = StateGraph(_State)
        g.add_node("plan", plan_node)
        g.add_node("act", act_node)
        g.set_entry_point("plan")
        g.add_edge("plan", "act")
        g.add_conditional_edges("act", route, {"act": "act", END: END})
        app = g.compile()

        tok = _current_trace_id.set(trace_id)
        final, stop = "", "llm_error"
        plan_tools: list[str] = []
        try:
            with nexus.span(SpanType.AGENT_STEP, input=task.prompt, role="root",
                            task_id=task.task_id, family=task.family) as root:
                try:
                    out = app.invoke({}, {"recursion_limit": 3 * max_steps + 5})
                    final = out.get("final") or ""
                    stop = out.get("stop") or "max_steps"
                    plan_tools = [str(p.get("tool")) for p in out.get("plan", [])]
                except Exception as exc:  # LLM/provider failure: record, don't label
                    root.error_type = exc.__class__.__name__
                    root.error_message = str(exc)[:300]
                    if exc.__class__.__name__ == "BudgetExceeded":
                        raise
                root.set_output(final)
        finally:
            _current_trace_id.reset(tok)
        return RunResult(plan_tools, steps, final, stop, acc["llm_calls"], acc["cost"],
                         acc["invalid"])
