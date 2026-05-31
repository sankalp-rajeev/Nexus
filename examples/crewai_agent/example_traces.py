"""Three manually-labeled example traces from an instrumented CrewAI-style agent.

Used to sanity-check the classifier end-to-end (Phase 3 exit criterion). One
trace per detection path: a healthy run (NORMAL), a rule-detected TOOL_MISFIRE,
and an embedding-detected HALLUCINATION.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from nexus_agent.models import CompleteTrace, FailureType, Span, SpanType, TraceStatus

AGENT = "crewai-research-agent"


def _span(tid, k, stype, inp, out=None, *, err=None, tool=None, final=False) -> Span:
    md = {}
    if tool:
        md["tool_name"] = tool
    if final:
        md["final"] = True
    base = datetime.now(timezone.utc)
    return Span(
        span_id=f"span_{tid[-6:]}_{k:02d}", trace_id=tid, agent_name=AGENT, span_type=stype,
        input=inp, output=out, duration_ms=90.0, error_type=err,
        error_message="error" if err else None, metadata=md,
        client_timestamp=base + timedelta(milliseconds=100 * k),
        server_timestamp=base + timedelta(milliseconds=100 * k), sdk_version="1.0.0",
    )


def _trace(tid, spans) -> CompleteTrace:
    return CompleteTrace(
        trace_id=tid, agent_name=AGENT, environment="example", root_input=spans[0].input,
        final_output=spans[-1].output, span_count=len(spans),
        total_duration_ms=sum(s.duration_ms for s in spans),
        started_at=spans[0].client_timestamp, completed_at=spans[-1].client_timestamp,
        status=TraceStatus.COMPLETED, spans=spans,
    )


def normal_trace() -> CompleteTrace:
    tid = "trace_crew_norm"
    return _trace(tid, [
        _span(tid, 0, SpanType.AGENT_STEP, "task: research the new GDP figures",
              "plan: search sources then summarize the GDP figures"),
        _span(tid, 1, SpanType.TOOL_CALL, "query: latest GDP figures 2026",
              "found 3 reports on GDP figures", tool="web_search"),
        _span(tid, 2, SpanType.LLM_CALL, "summarize the GDP figures from context",
              "the GDP figures show steady growth, summary is consistent with sources", final=True),
    ])


def tool_misfire_trace() -> CompleteTrace:
    tid = "trace_crew_misfire"
    return _trace(tid, [
        _span(tid, 0, SpanType.AGENT_STEP, "task: look up the customer record", "will call search"),
        _span(tid, 1, SpanType.TOOL_CALL, "", None, err="ToolError", tool="db_lookup"),
        _span(tid, 2, SpanType.TOOL_CALL, "", None, err="ToolError", tool="db_lookup", final=True),
    ])


def hallucination_trace() -> CompleteTrace:
    tid = "trace_crew_hall"
    return _trace(tid, [
        _span(tid, 0, SpanType.RETRIEVAL, "query: optimize the SQL query for orders",
              "retrieved docs about SQL query optimization for the orders table"),
        _span(tid, 1, SpanType.LLM_CALL, "using context about SQL optimization, answer",
              "a recipe for classic tiramisu with mascarpone and espresso, unrelated digression", final=True),
    ])


def labeled_examples() -> list[tuple[CompleteTrace, FailureType]]:
    return [
        (normal_trace(), FailureType.NORMAL),
        (tool_misfire_trace(), FailureType.TOOL_MISFIRE),
        (hallucination_trace(), FailureType.HALLUCINATION),
    ]
