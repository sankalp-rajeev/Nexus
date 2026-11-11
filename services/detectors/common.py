"""Helpers shared by the Phase 2 detectors.

Detectors consume a Nexus ``CompleteTrace`` (for NexusBench: the output of
``bench.detector_view``) and nothing else.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from nexus_agent.models import CompleteTrace, Span, SpanType

TOOL_SPAN_TYPES = (SpanType.TOOL_CALL, SpanType.MEMORY_READ, SpanType.RETRIEVAL)
# Tools whose output is retrieved evidence for grounding checks (deployment config).
RETRIEVAL_TOOLS = {"search_docs", "search", "retrieve", "retriever", "knowledge_search"}
ID_RE = re.compile(r"\b[A-Za-z]{1,3}-\d{3,6}\b")


@dataclass
class Call:
    span: Span
    tool: str
    args: Any
    args_text: str
    ok: bool


def tool_calls(trace: CompleteTrace) -> list[Call]:
    """Tool and memory calls in execution order (spans are recorded on completion)."""
    out = []
    for s in trace.spans:
        if s.span_type not in (SpanType.TOOL_CALL, SpanType.MEMORY_READ):
            continue
        tool = str((s.metadata or {}).get("tool_name") or s.span_type.value)
        try:
            args = json.loads(s.input) if s.input else {}
        except (json.JSONDecodeError, TypeError):
            args = s.input
        out.append(Call(s, tool, args, json.dumps(args, sort_keys=True), s.error_type is None))
    return out


def planned_tools(trace: CompleteTrace) -> list[str] | None:
    for s in trace.spans:
        md = s.metadata or {}
        if s.span_type == SpanType.AGENT_STEP and md.get("role") == "planner":
            return [str(t) for t in md.get("plan_steps", [])]
    return None


def parse_json(text: str | None) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def json_strings(obj: Any) -> list[str]:
    """All string leaves of a JSON value (dict values and list items)."""
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [x for v in obj.values() for x in json_strings(v)]
    if isinstance(obj, list):
        return [x for v in obj for x in json_strings(v)]
    return []
