"""OpenInference JSON -> existing OTLP mapping -> Nexus (no inference or IO).

Accepts nested ``child_spans`` exports or flat spans, with ``span_attributes``
or ``attributes``. Unknown attributes remain in the OTLP metadata. Tool names
are never guessed or renamed, and prose is never promoted to a declared plan.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
import re

from nexus_agent.models import CompleteTrace, SpanType, TraceStatus
from services.collector import otel

KIND_OPERATIONS = {
    "LLM": "chat", "TOOL": "execute_tool", "AGENT": "invoke_agent",
    "CHAIN": "invoke_workflow", "RETRIEVER": "retrieval", "EMBEDDING": "embeddings",
}
# Amendment A1: fixed from dev tool-name/span-kind schema, without labels or
# output inspection. Do not extend this list after external test inspection.
RETRIEVAL_TOOL_NAMES = frozenset({
    "web_search", "visit_page", "page_down", "page_up",
    "find_on_page_ctrl_f", "inspect_file_as_text",
})
ALIASES = {
    "llm.model_name": "gen_ai.request.model",
    "llm.token_count.prompt": "gen_ai.usage.input_tokens",
    "llm.token_count.completion": "gen_ai.usage.output_tokens",
    "tool.name": "gen_ai.tool.name",
}
_DURATION = re.compile(r"P(?:(\d+(?:\.\d+)?)D)?(?:T(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?)?")
_MESSAGE = re.compile(r"llm\.(input|output)_messages\.(\d+)\.message\.(.+)")


def _text(value) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _messages(attrs: dict, direction: str):
    direct = attrs.get(f"llm.{direction}_messages")
    if direct is not None:
        decoded = otel._structured(direct)
        if isinstance(decoded, list):
            messages = []
            for message in decoded:
                if isinstance(message, dict) and "parts" not in message:
                    extra = {k: v for k, v in message.items() if k not in {"role", "content"}}
                    if extra:
                        content = message.get("content")
                        message = {"role": message.get("role", ""), "parts":
                                   ([{"type": "text", "content": content}] if content is not None else []) +
                                   [{"type": "openinference_fields", "fields": extra}]}
                messages.append(message)
            return messages
        return direct
    found = {}
    for key, value in attrs.items():
        match = _MESSAGE.fullmatch(key)
        if match and match[1] == direction:
            found.setdefault(int(match[2]), {})[match[3]] = value
    messages = []
    for index in sorted(found):
        fields = found[index]
        message = {k: fields[k] for k in ("role", "content") if k in fields}
        # Preserve indexed tool calls / multimodal fields in structured JSON.
        extra = {k: v for k, v in fields.items() if k not in {"role", "content"}}
        if extra:
            # Mixed text/tool-call messages must stay structured: otherwise the
            # OTLP text convenience path would discard the non-text fields.
            content = message.pop("content", None)
            message["parts"] = ([{"type": "text", "content": content}] if content is not None else [])
            message["parts"].append({"type": "openinference_fields", "fields": extra})
        messages.append(message)
    return messages or None


def canonical_attributes(raw: dict) -> dict:
    """Retain raw attributes; add only deterministic GenAI aliases."""
    attrs = dict(raw)
    kind = str(raw.get("openinference.span.kind", "")).upper()
    operation = KIND_OPERATIONS.get(kind)
    if operation:
        attrs.setdefault("gen_ai.operation.name", operation)
    if kind == "RETRIEVER" or (kind == "TOOL" and raw.get("tool.name") in RETRIEVAL_TOOL_NAMES):
        # Retag the existing span, without renaming tools or duplicating spans.
        # TOOL content aliases below still preserve actual arguments/results.
        attrs["gen_ai.operation.name"] = "retrieval"
    for old, new in ALIASES.items():
        if old in raw:
            value = raw[old]
            if "token_count" in old:
                value = int(value)
            attrs.setdefault(new, value)
    if kind == "TOOL":
        # OpenInference tool.parameters describes the parameter schema, not
        # the invocation. Only captured input.value supplies actual arguments.
        value = raw.get("input.value")
        if value is not None:
            attrs.setdefault("gen_ai.tool.call.arguments", value)
        elif "gen_ai.tool.call.arguments" not in attrs:
            attrs["nexus.arguments_missing"] = True
        if raw.get("output.value") is not None:
            attrs.setdefault("gen_ai.tool.call.result", raw["output.value"])
    for direction, value_key in (("input", "input.value"), ("output", "output.value")):
        messages = _messages(raw, direction)
        if messages is not None:
            attrs.setdefault(f"gen_ai.{direction}.messages", messages)
        elif value_key in raw:
            # A plain value remains plain; an arbitrary JSON value remains JSON.
            attrs.setdefault(f"gen_ai.{direction}.messages", raw[value_key])
    return attrs


def _put(target, values: dict) -> None:
    def assign(dest, value):
        if isinstance(value, bool):
            dest.bool_value = value
        elif isinstance(value, int):
            dest.int_value = value
        elif isinstance(value, float):
            dest.double_value = value
        elif isinstance(value, str):
            dest.string_value = value
        elif isinstance(value, dict):
            dest.kvlist_value.SetInParent()
            _put(dest.kvlist_value.values, value)
        elif isinstance(value, (list, tuple)):
            # Explicitly retain empty arrays rather than losing their type.
            dest.array_value.SetInParent()
            for item in value:
                assign(dest.array_value.values.add(), item)
        elif value is not None:
            raise ValueError("Unsupported OpenInference attribute value type")

    for key, value in values.items():
        assign(target.add(key=key).value, value)


def _nanos(timestamp: str, default_timezone=None) -> int:
    # datetime supports microseconds; retain any extra exported nanoseconds.
    match = re.search(r"\.(\d+)(?:Z|[+-]\d\d:\d\d)?$", timestamp)
    fraction = (match[1] if match else "").ljust(9, "0")[:9]
    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if dt.tzinfo is None and default_timezone is not None:
        dt = dt.replace(tzinfo=default_timezone)
    if dt.tzinfo is None:
        raise ValueError("OpenInference timestamp must have a timezone")
    delta = dt.replace(microsecond=0) - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (delta.days * 86400 + delta.seconds) * 1_000_000_000 + int(fraction)


def _duration_nanos(source: dict) -> int:
    if "duration_ms" in source:
        value = Decimal(str(source["duration_ms"])) * 1_000_000
    else:
        match = _DURATION.fullmatch(source.get("duration", ""))
        if not match or not any(match.groups()):
            raise ValueError("Expected ISO-8601 duration or explicit duration_ms")
        value = sum(Decimal(v or "0") * unit for v, unit in
                    zip(match.groups(), (86400, 3600, 60, 1))) * 1_000_000_000
    if value < 0:
        raise ValueError("Negative OpenInference duration")
    return int(value)


def _id_bytes(value: str, size: int) -> bytes:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{%d}" % (size * 2), value):
        raise ValueError("Invalid OpenInference ID")
    decoded = bytes.fromhex(value)
    if not any(decoded):
        raise ValueError("OpenInference ID must be nonzero")
    return decoded


def _walk(spans: list, parent: str | None = None, depth: int = 0):
    for source in spans:
        yield source, parent, depth
        yield from _walk(source.get("child_spans") or [], source["span_id"], depth + 1)


def to_otlp(trace: dict):
    """Create a protobuf request accepted by the existing collector mapping."""
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

    trace_id = _id_bytes(trace["trace_id"], 16)
    request = ExportTraceServiceRequest()
    seen = set()
    for source, nested_parent, _ in _walk(trace["spans"]):
        if source["span_id"] in seen:
            raise ValueError("Duplicate OpenInference span ID")
        seen.add(source["span_id"])
        if source.get("trace_id", trace["trace_id"]) != trace["trace_id"]:
            raise ValueError("Span belongs to a different trace")
        explicit_parent = source.get("parent_span_id")
        if nested_parent and explicit_parent and explicit_parent != nested_parent:
            raise ValueError("Nested and explicit parents disagree")
        parent = explicit_parent or nested_parent
        resource = request.resource_spans.add()
        _put(resource.resource.attributes, source.get("resource_attributes") or {})
        scope = resource.scope_spans.add()
        scope.scope.name = source.get("scope_name") or "openinference"
        scope.scope.version = source.get("scope_version") or ""
        start = _nanos(source["timestamp"])
        wire = scope.spans.add(trace_id=trace_id, span_id=_id_bytes(source["span_id"], 8),
                               name=source.get("span_name", ""), start_time_unix_nano=start,
                               end_time_unix_nano=start + _duration_nanos(source))
        if parent:
            wire.parent_span_id = _id_bytes(parent, 8)
        _put(wire.attributes, canonical_attributes(source.get("span_attributes", source.get("attributes", {}))))
        code = str(source.get("status_code", "Unset")).upper()
        if code not in {"OK", "ERROR", "UNSET", "0", "1", "2"}:
            raise ValueError("Unknown OpenInference status code")
        wire.status.code = {"OK": 1, "ERROR": 2, "1": 1, "2": 2}.get(code, 0)
        wire.status.message = source.get("status_message") or ""
        for event in source.get("events") or []:
            event_time = event.get("timestamp", event.get("Timestamp"))
            # The JSON exporter omits the offset on exception events. Use the
            # enclosing span's explicit zone; never use the host's local zone.
            zone = datetime.fromisoformat(source["timestamp"].replace("Z", "+00:00")).tzinfo
            target = wire.events.add(name=event.get("name", event.get("Name", "")),
                                      time_unix_nano=_nanos(event_time, zone) if event_time else start)
            _put(target.attributes, event.get("attributes", event.get("Attributes", {})))
    return request


def complete_trace(trace: dict) -> CompleteTrace:
    """Map and assemble in completion order, as the frozen tool rules expect."""
    request = to_otlp(trace)
    spans = [s for batch in otel.span_batches(request) for s in batch.spans]
    if not spans:
        raise ValueError("Cannot convert an empty OpenInference trace")
    wire_spans = [s for r in request.resource_spans for scope in r.scope_spans for s in scope.spans]
    ends = {s.span_id.hex(): s.end_time_unix_nano for s in wire_spans}
    spans.sort(key=lambda s: (ends[s.span_id], s.client_timestamp))
    by_id = {s.span_id: s for s in spans}
    def depth(span):
        seen = {span.span_id}
        level = 0
        while span.parent_span_id in by_id:
            if span.parent_span_id in seen:
                raise ValueError("Cyclic OpenInference parent graph")
            span = by_id[span.parent_span_id]
            seen.add(span.span_id)
            level += 1
        return level
    depths = {s.span_id: depth(s) for s in spans}
    agents = [s for s in spans if s.span_type == SpanType.AGENT_STEP]
    inputs = [s for s in agents if s.input]
    outputs = [s for s in agents if s.output]
    # Prefer the outermost captured agent boundary; use the LLM boundary only
    # when no agent has content. Never concatenate all tool outputs as an answer.
    inputs = inputs or [s for s in spans if s.input]
    outputs = outputs or [s for s in spans if s.span_type == SpanType.LLM_CALL and s.output]
    first = min(inputs, key=lambda s: (depths[s.span_id], s.client_timestamp)) if inputs else None
    last = min(outputs, key=lambda s: (depths[s.span_id], -ends[s.span_id])) if outputs else None
    return CompleteTrace(trace_id=trace["trace_id"], agent_name=spans[0].agent_name,
                         environment=spans[0].environment,
                         root_input=first.input if first else None,
                         final_output=last.output if last else None,
                         span_count=len(spans), spans=spans,
                         started_at=min(s.client_timestamp for s in spans),
                         completed_at=otel._from_unix_nano(max(ends.values())),
                         total_duration_ms=(max(ends.values()) - min(s.start_time_unix_nano for s in wire_spans)) / 1_000_000,
                         status=TraceStatus.COMPLETED)
