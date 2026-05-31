"""Generate a labeled synthetic dataset of 200 traces (Section 8.3).

100 NORMAL + 20 each of HALLUCINATION, CONTEXT_BLEED, PLAN_DRIFT, TOOL_MISFIRE,
LOOP_DETECTED. Each failure type is generated with the distinguishing signal
described in the PRD so the two-stage classifier can detect it.

    python tests/fixtures/generate_synthetic_traces.py
writes tests/fixtures/synthetic_traces.json
"""

from __future__ import annotations

import json
import os
import random
from datetime import datetime, timedelta, timezone

from nexus_agent.models import CompleteTrace, FailureType, Span, SpanType, TraceStatus

SEED = 1234
OUT_PATH = os.path.join(os.path.dirname(__file__), "synthetic_traces.json")

CODE_TASKS = [
    "optimize the SQL query for the orders table",
    "fix the null pointer in the auth module",
    "add pagination to the users endpoint",
    "refactor the Redis caching layer",
    "implement retry logic for the payment API",
    "write unit tests for the parser",
    "migrate the schema to add an index",
    "debug the memory leak in the worker",
    "add input validation to the upload route",
    "parallelize the batch job pipeline",
]
MEETING_TASKS = [
    "summarize the Q3 planning meeting",
    "extract action items from the standup",
    "list decisions from the design review",
    "draft notes from the customer call",
    "summarize the incident retro",
    "capture follow-ups from the roadmap sync",
]
RESEARCH_TASKS = [
    "research the latest GDP growth figures",
    "summarize recent renewable energy adoption trends",
    "compare quarterly revenue across competitors",
    "find studies on sleep and productivity",
    "summarize the new climate policy report",
    "analyze housing market price movements",
    "review breakthroughs in battery technology",
    "summarize consumer sentiment survey results",
]
UNRELATED_TOPICS = [
    "a recipe for classic tiramisu with mascarpone",
    "the history of the Roman aqueduct system",
    "how photosynthesis converts sunlight into sugar",
    "the migratory patterns of arctic terns",
    "rules and scoring in the game of cricket",
    "the geology of volcanic basalt formations",
]
TOOLS = ["web_search", "sql_runner", "code_search", "calendar_lookup", "doc_fetch"]


def _rng(i: int) -> random.Random:
    return random.Random(SEED + i)


def _ts(base: datetime, k: int) -> datetime:
    return base + timedelta(milliseconds=120 * k)


def _span(trace_id: str, agent: str, stype: SpanType, k: int, base: datetime,
          *, inp: str, out: str | None = None, dur: float = 80.0,
          err_type: str | None = None, err_msg: str | None = None,
          metadata: dict | None = None) -> Span:
    return Span(
        span_id=f"span_{trace_id[-8:]}_{k:02d}",
        trace_id=trace_id,
        agent_name=agent,
        span_type=stype,
        input=inp,
        output=out,
        duration_ms=dur,
        error_type=err_type,
        error_message=err_msg,
        metadata=metadata or {},
        client_timestamp=_ts(base, k),
        server_timestamp=_ts(base, k),
        sdk_version="1.0.0",
    )


def _trace(trace_id: str, agent: str, spans: list[Span], root_input: str) -> CompleteTrace:
    return CompleteTrace(
        trace_id=trace_id,
        agent_name=agent,
        environment="synthetic",
        root_input=root_input,
        final_output=spans[-1].output,
        span_count=len(spans),
        total_duration_ms=sum(s.duration_ms for s in spans),
        started_at=spans[0].client_timestamp,
        completed_at=spans[-1].client_timestamp,
        status=TraceStatus.COMPLETED,
        spans=spans,
    )


def gen_normal(i: int) -> CompleteTrace:
    """Healthy trace with a varied (but coherent) structure. Multiple shapes
    keep the NORMAL distribution diverse so calibration generalizes."""
    r = _rng(i)
    base = datetime.now(timezone.utc)
    domain = r.choice(["code", "meeting", "research"])
    agent = {"code": "CodeMind", "meeting": "MeetingMind", "research": "ResearchCrew"}[domain]
    task = r.choice({"code": CODE_TASKS, "meeting": MEETING_TASKS, "research": RESEARCH_TASKS}[domain])
    tool = r.choice(TOOLS)
    tid = f"trace_norm{i:04d}"
    shape = r.choice(["plan_retrieve_llm_mem", "plan_tool_llm", "llm_only", "plan_retrieve_llm", "plan_tool_tool_llm_mem"])

    spans: list[Span] = []
    k = 0

    def add(stype, inp, out, **md):
        nonlocal k
        spans.append(_span(tid, agent, stype, k, base, inp=inp, out=out, metadata=md))
        k += 1

    if shape == "plan_retrieve_llm_mem":
        add(SpanType.AGENT_STEP, f"task: {task}", f"plan: gather context then {task}")
        add(SpanType.RETRIEVAL, f"query: {task}", f"retrieved 3 docs about {task}")
        add(SpanType.LLM_CALL, f"using context, {task}", f"completed: {task}; result is consistent and correct",
            model="gemini-2.0-flash", tokens_used=r.randint(120, 400))
        add(SpanType.MEMORY_WRITE, f"store result for {task}", "stored ok", final=True)
    elif shape == "plan_tool_llm":
        add(SpanType.AGENT_STEP, f"task: {task}", f"plan: use {tool} to handle {task}")
        add(SpanType.TOOL_CALL, f"query: {task}", f"{tool} returned results for {task}", tool_name=tool)
        add(SpanType.LLM_CALL, f"summarize {tool} results for {task}", f"answer about {task} grounded in {tool} output",
            model="gemini-2.0-flash", tokens_used=r.randint(120, 400), final=True)
    elif shape == "llm_only":
        add(SpanType.LLM_CALL, f"directly answer: {task}", f"concise correct answer about {task}",
            model="gemini-2.0-flash", tokens_used=r.randint(80, 300), final=True)
    elif shape == "plan_retrieve_llm":
        add(SpanType.AGENT_STEP, f"task: {task}", f"plan for {task}")
        add(SpanType.RETRIEVAL, f"query: {task}", f"retrieved docs about {task}")
        add(SpanType.LLM_CALL, f"answer {task} from context", f"correct, on-topic answer about {task}",
            model="gemini-2.0-flash", tokens_used=r.randint(120, 400), final=True)
    else:  # plan_tool_tool_llm_mem
        add(SpanType.AGENT_STEP, f"task: {task}", f"plan: multi-step on {task}")
        add(SpanType.TOOL_CALL, f"query: {task} part 1", f"{tool} ok for {task} part 1", tool_name=tool)
        add(SpanType.TOOL_CALL, f"query: {task} part 2", f"{tool} ok for {task} part 2", tool_name=tool)
        add(SpanType.LLM_CALL, f"combine results for {task}", f"coherent synthesis about {task}",
            model="gemini-2.0-flash", tokens_used=r.randint(150, 500))
        add(SpanType.MEMORY_WRITE, f"persist {task}", "stored ok", final=True)

    return _trace(tid, agent, spans, task)


def gen_hallucination(i: int) -> CompleteTrace:
    r = _rng(1000 + i)
    base = datetime.now(timezone.utc)
    task = r.choice(CODE_TASKS)
    wrong = r.choice(UNRELATED_TOPICS)
    tid = f"trace_hall{i:04d}"
    spans = [
        _span(tid, "CodeMind", SpanType.RETRIEVAL, 0, base,
              inp=f"query: {task}", out=f"retrieved docs about {task}"),
        # LLM output is about an unrelated topic -> far from input context.
        _span(tid, "CodeMind", SpanType.LLM_CALL, 1, base,
              inp=f"using context about {task}, answer the question",
              out=f"{wrong}. {wrong}. unrelated digression about {wrong}",
              metadata={"model": "gemini-2.0-flash", "tokens_used": r.randint(120, 400)}),
        _span(tid, "CodeMind", SpanType.AGENT_STEP, 2, base,
              inp="finalize", out=f"final answer references {wrong}", metadata={"final": True}),
    ]
    return _trace(tid, "CodeMind", spans, task)


def gen_context_bleed(i: int) -> CompleteTrace:
    r = _rng(2000 + i)
    base = datetime.now(timezone.utc)
    cur_s, cur_u = r.randint(100, 199), r.randint(10, 49)
    other_s, other_u = r.randint(200, 299), r.randint(50, 99)
    task = r.choice(MEETING_TASKS)
    tid = f"trace_bleed{i:04d}"
    spans = [
        _span(tid, "MeetingMind", SpanType.AGENT_STEP, 0, base,
              inp=f"session_{cur_s} user_{cur_u}: {task}", out="planning with current session context"),
        # Memory read returns a DIFFERENT session/user than the current task.
        _span(tid, "MeetingMind", SpanType.MEMORY_READ, 1, base,
              inp=f"read context for session_{cur_s} user_{cur_u}",
              out=f"returned notes from session_{other_s} user_{other_u} (mismatched session)",
              metadata={"memory_key": f"session_{other_s}_user_{other_u}"}),
        _span(tid, "MeetingMind", SpanType.LLM_CALL, 2, base,
              inp=f"summarize using memory for session_{cur_s}",
              out=f"summary contaminated with session_{other_s} user_{other_u} data",
              metadata={"model": "gemini-2.0-flash", "final": True}),
    ]
    return _trace(tid, "MeetingMind", spans, task)


def gen_plan_drift(i: int) -> CompleteTrace:
    r = _rng(3000 + i)
    base = datetime.now(timezone.utc)
    a, b, c = "task_A", "task_B", "task_C"
    task = r.choice(CODE_TASKS)
    tid = f"trace_drift{i:04d}"
    spans = [
        _span(tid, "CodeMind", SpanType.AGENT_STEP, 0, base,
              inp=f"plan for {task}", out=f"planner subtasks: {a}, {b}, {c}"),
        _span(tid, "CodeMind", SpanType.AGENT_STEP, 1, base,
              inp=f"execute {a}", out=f"executed {a} successfully"),
        # task_B is skipped; executor jumps to task_C -> incomplete coverage.
        _span(tid, "CodeMind", SpanType.AGENT_STEP, 2, base,
              inp=f"execute {c}", out=f"executed {c}; {b} was never performed"),
        _span(tid, "CodeMind", SpanType.AGENT_STEP, 3, base,
              inp="finalize", out=f"done with {a} and {c} only, drifted from plan",
              metadata={"final": True}),
    ]
    return _trace(tid, "CodeMind", spans, task)


def gen_tool_misfire(i: int) -> CompleteTrace:
    r = _rng(4000 + i)
    base = datetime.now(timezone.utc)
    tool = r.choice(TOOLS)
    bad_args = ""  # empty query string -> error, then identical retry
    tid = f"trace_misfire{i:04d}"
    spans = [
        _span(tid, "CodeMind", SpanType.AGENT_STEP, 0, base, inp="start task", out="will call tool"),
        _span(tid, "CodeMind", SpanType.TOOL_CALL, 1, base,
              inp=bad_args, out=None, err_type="ToolError", err_msg="empty query rejected",
              metadata={"tool_name": tool}),
        # Identical retry with the same bad args within the window.
        _span(tid, "CodeMind", SpanType.TOOL_CALL, 2, base,
              inp=bad_args, out=None, err_type="ToolError", err_msg="empty query rejected",
              metadata={"tool_name": tool, "final": True}),
    ]
    return _trace(tid, "CodeMind", spans, "tool task")


def gen_loop_detected(i: int) -> CompleteTrace:
    r = _rng(5000 + i)
    base = datetime.now(timezone.utc)
    tool = r.choice(TOOLS)
    args = f"query: {r.choice(CODE_TASKS)}"
    tid = f"trace_loop{i:04d}"
    spans = [_span(tid, "CodeMind", SpanType.AGENT_STEP, 0, base, inp="start", out="looping")]
    # Same (tool_name, input) repeated 3+ times.
    for k in range(1, 4 + r.randint(0, 1)):
        spans.append(
            _span(tid, "CodeMind", SpanType.TOOL_CALL, k, base,
                  inp=args, out="same result", metadata={"tool_name": tool})
        )
    spans[-1].metadata["final"] = True
    return _trace(tid, "CodeMind", spans, "loop task")


GENERATORS = {
    FailureType.NORMAL: (gen_normal, 100),
    FailureType.HALLUCINATION: (gen_hallucination, 20),
    FailureType.CONTEXT_BLEED: (gen_context_bleed, 20),
    FailureType.PLAN_DRIFT: (gen_plan_drift, 20),
    FailureType.TOOL_MISFIRE: (gen_tool_misfire, 20),
    FailureType.LOOP_DETECTED: (gen_loop_detected, 20),
}


def build_dataset() -> tuple[list[CompleteTrace], list[FailureType]]:
    traces: list[CompleteTrace] = []
    labels: list[FailureType] = []
    for label, (gen, count) in GENERATORS.items():
        for i in range(count):
            traces.append(gen(i))
            labels.append(label)
    return traces, labels


def save_dataset(path: str = OUT_PATH) -> str:
    traces, labels = build_dataset()
    payload = {
        "labels": [l.value for l in labels],
        "traces": [t.model_dump(mode="json") for t in traces],
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    return path


def load_dataset(path: str = OUT_PATH) -> tuple[list[CompleteTrace], list[FailureType]]:
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    traces = [CompleteTrace.model_validate(t) for t in payload["traces"]]
    labels = [FailureType(l) for l in payload["labels"]]
    return traces, labels


if __name__ == "__main__":
    p = save_dataset()
    traces, labels = load_dataset(p)
    from collections import Counter

    print(f"wrote {len(traces)} traces -> {p}")
    print("label counts:", dict(Counter(l.value for l in labels)))
