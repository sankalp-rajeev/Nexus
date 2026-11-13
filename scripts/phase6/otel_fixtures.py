"""Convert NexusBench DEV traces into OTLP spans that use the current GenAI semconv names.

DEV only. Trace ids are whitelisted through the DEV label adapter before any trace is
deserialised (``services.critic.dev_adapter``); nothing here opens the sealed TEST split.

The conversion is what a faithful GenAI instrumentation would emit for the same
operation, not a Nexus-aware encoding:

* every Nexus field that has a semconv equivalent uses it (model, provider, token usage,
  tool name, error type/message, operation name, prompt/response content);
* Python OTel attributes cannot hold nested maps, so message content is a JSON *string*
  (this is what the Python instrumentations emit);
* everything else in span metadata (role, cached, family, ...) becomes an ``app.*`` custom
  attribute, which the Nexus mapping keeps only in ``metadata["otel.attributes"]``;
* nothing is added that would make the round trip easier (no ``nexus.*`` hints other than the
  explicit ``nexus.synthetic`` marker when requested).
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "sdk")]

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest  # noqa: E402

from nexus_agent.models import Span, SpanType  # noqa: E402
from services.critic.dev_adapter import dev_labels, dev_traces  # noqa: E402

LABELS = ROOT / "data/nexusbench/labels.csv"
TRACES = ROOT / "data/nexusbench/traces.jsonl"
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
SCOPE_NAME, SCOPE_VERSION = "nexus.otel_fixtures", "1"

OPERATIONS = {
    SpanType.LLM_CALL: "chat",
    SpanType.TOOL_CALL: "execute_tool",
    SpanType.AGENT_STEP: "invoke_agent",
    SpanType.MEMORY_READ: "search_memory",
}
# (input attribute, output attribute) for the operations above.
CONTENT_ATTRIBUTES = {
    SpanType.LLM_CALL: ("gen_ai.input.messages", "gen_ai.output.messages"),
    SpanType.AGENT_STEP: ("gen_ai.input.messages", "gen_ai.output.messages"),
    SpanType.TOOL_CALL: ("gen_ai.tool.call.arguments", "gen_ai.tool.call.result"),
    SpanType.MEMORY_READ: ("gen_ai.memory.query.text", "gen_ai.memory.records"),
}
# Nexus metadata keys that have a current-semconv attribute.
SEMCONV_METADATA = {"model", "provider", "input_tokens", "output_tokens", "tool_name", "tokens_used"}


def dev_trace_ids() -> list[str]:
    """DEV trace ids, in label-file order. TEST rows are discarded by ``dev_labels``."""
    return [row["trace_id"] for row in dev_labels(LABELS) if row["split"] == "dev"]


def dev_labelled() -> dict[str, str]:
    return {row["trace_id"]: row["label"] for row in dev_labels(LABELS) if row["split"] == "dev"}


def load_dev_traces(ids) -> dict:
    """Whitelisted DEV traces only (the adapter refuses ids outside the DEV set)."""
    allowed = set(dev_trace_ids())
    ids = list(ids)
    if not set(ids) <= allowed:
        raise ValueError("DEV whitelist failed: refusing non-DEV trace ids")
    return dev_traces(TRACES, set(ids))


def otel_trace_id(trace_id: str, salt: str = "") -> bytes:
    return hashlib.sha256(f"{salt}|{trace_id}".encode()).digest()[:16]


def otel_span_id(trace_id: str, span_id: str, salt: str = "") -> bytes:
    return hashlib.sha256(f"{salt}|{trace_id}|{span_id}".encode()).digest()[:8]


def _nanos(moment: datetime) -> int:
    return (moment - EPOCH) // timedelta(microseconds=1) * 1000


def _set(target, key: str, value) -> None:
    attr = target.add(key=key).value
    if isinstance(value, bool):
        attr.bool_value = value
    elif isinstance(value, int):
        attr.int_value = value
    elif isinstance(value, float):
        attr.double_value = value
    elif isinstance(value, str):
        attr.string_value = value
    elif isinstance(value, (list, tuple)) and all(isinstance(v, str) for v in value):
        for item in value:
            attr.array_value.values.add(string_value=item)
    else:
        attr.string_value = json.dumps(value, ensure_ascii=False, sort_keys=True)


def message_json(role: str, text: str, *, finish_reason: str | None = None) -> str:
    message = {"role": role, "parts": [{"type": "text", "content": text}]}
    if finish_reason:
        message["finish_reason"] = finish_reason
    return json.dumps([message], ensure_ascii=False)


def span_attributes(span: Span, plan_attributes: bool = True) -> dict:
    """Current-semconv attributes for one Nexus span (ordered; no nested values).

    ``plan_attributes`` writes a span's ``role``/``plan_steps`` as the documented ``nexus.agent.*``
    attributes; with False they are plain ``app.*`` attributes, as a generic OpenTelemetry
    application that knows nothing about Nexus would emit them.
    """
    if span.span_type not in OPERATIONS:
        raise ValueError(f"fixture converter does not cover span_type={span.span_type.value}")
    meta = span.metadata or {}
    operation = OPERATIONS[span.span_type]
    attrs: dict = {"gen_ai.operation.name": operation}
    if span.span_type == SpanType.LLM_CALL:
        if "model" in meta:
            attrs["gen_ai.request.model"] = meta["model"]
        if "provider" in meta:
            attrs["gen_ai.provider.name"] = meta["provider"]
        for key, name in (("input_tokens", "gen_ai.usage.input_tokens"), ("output_tokens", "gen_ai.usage.output_tokens")):
            if key in meta:
                attrs[name] = meta[key]
    elif span.span_type == SpanType.TOOL_CALL and "tool_name" in meta:
        attrs["gen_ai.tool.name"] = meta["tool_name"]
    elif span.span_type == SpanType.AGENT_STEP:
        attrs["gen_ai.agent.name"] = span.agent_name
    in_key, out_key = CONTENT_ATTRIBUTES[span.span_type]
    as_messages = in_key == "gen_ai.input.messages"
    attrs[in_key] = message_json("user", span.input) if as_messages else span.input
    if span.output is not None:
        attrs[out_key] = message_json("assistant", span.output, finish_reason="stop") if as_messages else span.output
    if span.error_type:
        attrs["error.type"] = span.error_type
    plan_keys = {"role": "nexus.agent.role", "plan_steps": "nexus.agent.plan_steps"}
    for key, value in meta.items():
        if key in SEMCONV_METADATA:
            continue
        if plan_attributes and key in plan_keys:  # any span: NexusBench also tags the planner's llm_call
            attrs[plan_keys[key]] = value
        else:
            attrs[f"app.{key}"] = value
    return attrs


def trace_to_otlp(trace, *, trace_salt: str = "", synthetic: bool = False,
                  id_prefix: str | None = None, plan_attributes: bool = True) -> ExportTraceServiceRequest:
    """One OTLP export request holding every span of ``trace``, in the trace's span order."""
    request = ExportTraceServiceRequest()
    resource = request.resource_spans.add()
    _set(resource.resource.attributes, "service.name", trace.agent_name)
    _set(resource.resource.attributes, "deployment.environment.name", trace.environment)
    scope = resource.scope_spans.add()
    scope.scope.name, scope.scope.version = SCOPE_NAME, SCOPE_VERSION
    tid = otel_trace_id(id_prefix or trace.trace_id, trace_salt)
    for source in trace.spans:
        attrs = span_attributes(source, plan_attributes)  # raises for span types the converter does not cover
        start = _nanos(source.client_timestamp)
        wire = scope.spans.add(
            trace_id=tid, span_id=otel_span_id(trace.trace_id, source.span_id, trace_salt),
            name=f"{OPERATIONS[source.span_type]} {source.metadata.get('model') or source.metadata.get('tool_name') or ''}".strip(),
            kind=3 if source.span_type == SpanType.LLM_CALL else 1,
            start_time_unix_nano=start, end_time_unix_nano=start + round(source.duration_ms * 1_000_000),
        )
        if source.parent_span_id:
            wire.parent_span_id = otel_span_id(trace.trace_id, source.parent_span_id, trace_salt)
        if synthetic:
            attrs["nexus.synthetic"] = True
        for key, value in attrs.items():
            _set(wire.attributes, key, value)
        if source.error_type or source.error_message:
            wire.status.code = 2
            wire.status.message = source.error_message or ""
    return request


def otlp_span_ids(trace, trace_salt: str = "") -> list[str]:
    """OTLP hex span ids in trace order, to translate native ``failure_span_id`` values."""
    return [otel_span_id(trace.trace_id, s.span_id, trace_salt).hex() for s in trace.spans]


def native_spans(trace, *, trace_id: str | None = None, id_salt: str = "", synthetic: bool = False) -> list[Span]:
    """The trace's own spans, as the SDK would have posted them (optionally re-keyed)."""
    out = []
    mapping = {s.span_id: f"span_{hashlib.sha256(f'{id_salt}|{s.span_id}'.encode()).hexdigest()[:12]}" for s in trace.spans}
    for span in trace.spans:
        update = {"trace_id": trace_id or span.trace_id, "server_timestamp": None}
        if id_salt:
            update["span_id"] = mapping[span.span_id]
            update["parent_span_id"] = mapping.get(span.parent_span_id)
        if synthetic:
            update["metadata"] = {**span.metadata, "nexus.synthetic": True}
        out.append(span.model_copy(update=update))
    return out

def with_root_final(trace):
    """Same trace, same span order; the parentless span carries ``metadata.final = True``."""
    spans = [s.model_copy(update={"metadata": {**s.metadata, "final": True}}) if s.parent_span_id is None else s
             for s in trace.spans]
    return trace.model_copy(update={"spans": spans})


def sdk_delivery(trace):
    """The trace as the Nexus SDK (0.1.0rc1+) delivers it: the root span (no parent) carries
    ``metadata.final = True`` and arrives last, because a root ends after its children.

    DEV traces come with one parentless span each and no ``final`` key. Everything else about
    the spans is unchanged; only the order of arrival and that one metadata key differ.
    """
    marked = with_root_final(trace)
    ordered = [s for s in marked.spans if s.parent_span_id is not None] + \
              [s for s in marked.spans if s.parent_span_id is None]
    return marked.model_copy(update={"spans": ordered})