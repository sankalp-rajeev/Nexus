"""The NexusBench agent: a LangGraph planner -> actor loop with a real LLM.

Every run is instrumented with the Nexus SDK, so its trace is a genuine Nexus
``CompleteTrace`` (root agent_step, planner agent_step with its declared plan,
llm_call spans, tool_call spans, memory_read spans with session/user IDs).

The LLM speaks a provider-agnostic JSON protocol (no native function calling),
so the same agent runs on Gemini, DeepSeek and a local Ollama model.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

import nexus_agent as nexus
from nexus_agent.client import _current_trace_id
from nexus_agent.models import SpanType

from bench.llm import LLMClient
from bench.tasks import Task
from bench.tools import TOOL_SPECS, Toolbox, ToolError

MAX_STEPS = 8
AGENT_NAME = "nexusbench_agent"

_BASE_SYSTEM = (
    "You are an operations assistant for a company database. You solve the user's task by "
    "calling tools, then give a final answer. All facts must come from tool results. "
    "Respond ONLY with a single JSON object, no prose."
)
_GUESS_SYSTEM = (  # HALLUCINATION fault: a prompt that rewards guessing
    _BASE_SYSTEM + " Users are frustrated by non-answers: always give a specific, confident "
    "answer, and never say that you don't know or that information is missing."
)


def _tool_block() -> str:
    lines = []
    for t in TOOL_SPECS:
        args = ", ".join(f"{k}: {v}" for k, v in t["args"].items()) or "no arguments"
        lines.append(f"- {t['name']}({args}): {t['description']}")
    return "Available tools:\n" + "\n".join(lines)


def _parse_json(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                obj = json.loads(m.group(0))
                return obj if isinstance(obj, dict) else None
            except json.JSONDecodeError:
                return None
    return None


@dataclass
class Step:
    tool: str
    args: dict[str, Any]
    output: str | None
    error: str | None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunResult:
    plan_tools: list[str]
    steps: list[Step]
    final_answer: str
    stop_reason: str  # "final" | "max_steps" | "llm_error"
    llm_calls: int
    cost_usd: float
    invalid_json: int


class _State(TypedDict, total=False):
    plan: list[dict[str, Any]]
    history: list[dict[str, Any]]
    final: str | None
    stop: str | None


class SpanCollector:
    """Thread-safe exporter that keeps spans in memory, grouped by trace."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.by_trace: dict[str, list] = {}

    def export(self, batch) -> bool:
        with self._lock:
            for s in batch.spans:
                self.by_trace.setdefault(s.trace_id, []).append(s)
        return True

    def pop(self, trace_id: str) -> list:
        with self._lock:
            return self.by_trace.pop(trace_id, [])

    def close(self) -> None:
        pass


class BenchAgent:
    def __init__(self, llm: LLMClient, *, seed: int = 0, sample_tag: str = "") -> None:
        self.llm = llm
        self.seed = seed
        self.sample_tag = sample_tag

    # -- LLM with instrumentation -------------------------------------------
    def _ask(self, system: str, prompt: str, role: str, acc: dict[str, Any]) -> str:
        with nexus.span(SpanType.LLM_CALL, input=prompt, role=role, model=self.llm.model,
                        provider=self.llm.provider) as s:
            resp = self.llm.complete(system, [{"role": "user", "content": prompt}],
                                     max_tokens=400, temperature=0.0, seed=self.seed,
                                     cache_tag=self.sample_tag)
            acc["llm_calls"] += 1
            acc["cost"] += resp.cost_usd
            s.set_output(resp.text)
            s.set_metadata({"tokens_used": resp.input_tokens + resp.output_tokens,
                            "input_tokens": resp.input_tokens,
                            "output_tokens": resp.output_tokens, "cached": resp.cached})
        return resp.text

    # -- run ------------------------------------------------------------------
    def run(self, task: Task, toolbox: Toolbox, trace_id: str, *, guessing_prompt: bool) -> RunResult:
        system = _GUESS_SYSTEM if guessing_prompt else _BASE_SYSTEM
        acc: dict[str, Any] = {"llm_calls": 0, "cost": 0.0, "invalid": 0}
        steps: list[Step] = []

        def plan_node(state: _State) -> _State:
            prompt = (
                f"{_tool_block()}\n\nTask: {task.prompt}\n\n"
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
                f"{_tool_block()}\n\nTask: {task.prompt}\n\nYour plan: {plan_txt}\n\n"
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
            if len(history) >= MAX_STEPS:
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
                    out = app.invoke({}, {"recursion_limit": 3 * MAX_STEPS + 5})
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

    @staticmethod
    def _exec(toolbox: Toolbox, tool: str, args: dict[str, Any]) -> tuple[str, str | None, dict]:
        span_type = SpanType.MEMORY_READ if tool == "read_memory" else SpanType.TOOL_CALL
        with nexus.span(span_type, input=json.dumps(args, sort_keys=True), tool_name=tool) as s:
            try:
                out, meta = toolbox.run(tool, args)
                s.set_output(out)
                s.set_metadata(meta)
                return out, None, meta
            except (ToolError, TypeError) as exc:
                msg = str(exc) if isinstance(exc, ToolError) else "invalid arguments"
                s.error_type = "ToolError"
                s.error_message = msg
                return f"ERROR: {msg}", msg, {}
