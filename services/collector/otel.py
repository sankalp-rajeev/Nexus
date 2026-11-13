"""Lossless OTLP-to-Nexus projection; the field-by-field contract is docs/otel_mapping.md.

This is server-side code: it lives in the collector, not in the ``nexus-llmops`` SDK wheel.
Nothing here imports OpenTelemetry, and the one protobuf helper is imported lazily, so importing
this module pulls in no OTel or protobuf package. ``span_batches`` takes an
``ExportTraceServiceRequest`` that the caller (the collector) has already parsed.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from nexus_agent.models import Span, SpanBatch, SpanType

# Conventions this mapping was written and tested against (see docs/otel_mapping.md).
# semantic-conventions-genai has no tagged release, so it is pinned by commit.
SEMCONV_GENAI_REPO = "https://github.com/open-telemetry/semantic-conventions-genai"
SEMCONV_GENAI_COMMIT = "e6658f14c9d9ea0760825f029cb82e7673f48fab"  # main, 2026-11-06
# Core semantic-conventions release that still carried gen_ai.* (v1.42.0 moved it out).
SEMCONV_CORE_VERSION = "v1.41.1"
SEMCONV_CORE_COMMIT = "ead83b9b0fa36540c1642fce46e874f002ac23f1"

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

# Legacy attribute name -> current name. The current name always wins when both are present.
LEGACY_ATTRIBUTE_ALIASES = {
    "gen_ai.system": "gen_ai.provider.name",
    "gen_ai.usage.prompt_tokens": "gen_ai.usage.input_tokens",
    "gen_ai.usage.completion_tokens": "gen_ai.usage.output_tokens",
}
# Values of the legacy gen_ai.system that were renamed in gen_ai.provider.name.
LEGACY_PROVIDER_VALUES = {
    "vertex_ai": "gcp.vertex_ai",
    "gemini": "gcp.gemini",
    "az.ai.inference": "azure.ai.inference",
    "az.ai.openai": "azure.ai.openai",
}
# Pre-1.37 per-message span events: event name -> role.
LEGACY_INPUT_EVENTS = {
    "gen_ai.system.message": "system", "gen_ai.user.message": "user",
    "gen_ai.assistant.message": "assistant", "gen_ai.tool.message": "tool",
}
LEGACY_OUTPUT_EVENT = "gen_ai.choice"
DETAILS_EVENT = "gen_ai.client.inference.operation.details"
# GenAI semconv has no notion of an agent's declared plan, which the PLAN_DRIFT detector needs
# (it reads ``role == "planner"`` and ``plan_steps`` on an agent span). These Nexus-namespaced span
# attributes are the opt-in way to supply it; without them PLAN_DRIFT cannot fire on OTLP traces.
NEXUS_AGENT_ATTRIBUTES = {"nexus.agent.role": "role", "nexus.agent.plan_steps": "plan_steps"}
# Content stored externally. The pinned spec says "_ref"; opentelemetry-instrumentation-openai-v2
# 2.4b0 still writes the dotted ".ref" form.
CONTENT_REF_KEYS = (
    "gen_ai.input.messages_ref", "gen_ai.output.messages_ref", "gen_ai.system_instructions_ref",
    "gen_ai.input.messages.ref", "gen_ai.output.messages.ref", "gen_ai.system_instructions.ref",
)


def _message_to_dict(message) -> dict:
    from google.protobuf.json_format import MessageToDict

    return MessageToDict(message)


def _value(value):
    kind = value.WhichOneof("value")
    if kind == "array_value":
        return [_value(v) for v in value.array_value.values]
    if kind == "kvlist_value":
        return _attributes(value.kvlist_value.values)
    if kind == "bytes_value":
        return {"base64": _message_to_dict(value)["bytesValue"]}
    return getattr(value, kind) if kind else None


def _attributes(attributes) -> dict:
    return {a.key: _value(a.value) for a in attributes}


def _text(value) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _plan_steps(value) -> list[str]:
    """``nexus.agent.plan_steps`` is a string array; a JSON-encoded array (or one step) is accepted too."""
    if isinstance(value, str):
        decoded = _structured(value)
        value = decoded if isinstance(decoded, list) else [value]
    return [str(step) for step in value] if isinstance(value, list) else [str(value)]


def _structured(value):
    """Decode JSON text; structured AnyValue passes through. None if not decodable."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


def _joined(messages: list[tuple[str, str]]) -> str:
    """One message is plain text; several keep their role as a line prefix."""
    if len(messages) == 1:
        return messages[0][1]
    return "\n".join(f"{role}: {text}" if role else text for role, text in messages)


def _text_message(message) -> tuple[str, str] | None:
    """(role, text) when the message holds only text parts; else None."""
    if not isinstance(message, dict):
        return None
    role = str(message.get("role") or "")
    parts = message.get("parts")
    if parts is None:  # pre-"parts" shape: {"role": ..., "content": "..."}
        content = message.get("content")
        return (role, content) if isinstance(content, str) else None
    if not isinstance(parts, list):
        return None
    texts = []
    for part in parts:
        if not (isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("content"), str)):
            return None
        texts.append(part["content"])
    return role, "\n".join(texts)


def _message_list(value) -> list[tuple[str, str]] | None:
    """Text-only message list, or None when anything is non-text (tool calls, blobs, ...)."""
    structure = _structured(value)
    if not isinstance(structure, list):
        return None
    messages = [_text_message(m) for m in structure]
    return None if any(m is None for m in messages) else messages


def _system_text(value) -> str:
    structure = _structured(value)
    if isinstance(structure, list) and all(
        isinstance(p, dict) and p.get("type") == "text" and isinstance(p.get("content"), str) for p in structure
    ):
        return "\n".join(p["content"] for p in structure)
    return value if isinstance(value, str) and structure is None else _text(value)


def _indexed(attrs: dict, prefix: str) -> list[tuple[str, str]] | None:
    """Flattened legacy form: gen_ai.prompt.0.role / gen_ai.prompt.0.content, gen_ai.completion.0.*."""
    found: dict[int, dict] = {}
    for key, value in attrs.items():
        parts = key.split(".")
        if key.startswith(prefix + ".") and len(parts) == 4 and parts[2].isdigit() and parts[3] in {"role", "content"}:
            found.setdefault(int(parts[2]), {})[parts[3]] = value
    messages = [(str(found[i].get("role") or ""), _text(found[i]["content"])) for i in sorted(found) if "content" in found[i]]
    return messages or None


def _input_content(attrs: dict) -> str | None:
    if "gen_ai.tool.call.arguments" in attrs:
        return _text(attrs["gen_ai.tool.call.arguments"])
    system, history = attrs.get("gen_ai.system_instructions"), attrs.get("gen_ai.input.messages")
    if system is not None or history is not None:
        head = [("system", _system_text(system))] if system is not None else []
        if history is None:
            return _joined(head)
        listed = _message_list(history)
        if listed is not None:
            return _joined(head + listed)
        # Non-text history (tool calls, blobs, ...) stays JSON; instructions precede it.
        prefix = f"system: {head[0][1]}\n" if head else ""
        return prefix + _text(history)
    for key in ("gen_ai.retrieval.query.text", "gen_ai.memory.query.text", "gen_ai.prompt"):
        if key in attrs:
            return _text(attrs[key])
    listed = _indexed(attrs, "gen_ai.prompt")
    return _joined(listed) if listed else None


def _output_content(attrs: dict) -> str | None:
    for key in ("gen_ai.tool.call.result", "gen_ai.output.messages", "gen_ai.memory.records",
                "gen_ai.retrieval.documents", "gen_ai.completion"):
        if key in attrs:
            if key == "gen_ai.output.messages":
                listed = _message_list(attrs[key])
                if listed is not None:
                    return _joined(listed)
            return _text(attrs[key])
    listed = _indexed(attrs, "gen_ai.completion")
    return _joined(listed) if listed else None


def _event_body(values: dict):
    """Event payload: its own attributes, or the JSON blob some older instrumentations use."""
    blob = values.get("gen_ai.event.content")
    decoded = _structured(blob) if blob is not None else None
    return decoded if isinstance(decoded, dict) else values


def _message_event_text(content) -> str:
    return content if isinstance(content, str) else _text(content)


def _event_content(events) -> tuple[dict, list[tuple[str, str]], list[tuple[str, str]]]:
    """Content carried by span events: (attribute-like fallback, legacy input msgs, legacy output msgs)."""
    fallback: dict = {}
    legacy_in: list[tuple[str, str]] = []
    legacy_out: list[tuple[str, str]] = []
    for event in events:
        values = _attributes(event.attributes)
        name = event.name
        if name == DETAILS_EVENT:
            for key in ("gen_ai.input.messages", "gen_ai.output.messages", "gen_ai.system_instructions"):
                if key in values:
                    fallback.setdefault(key, values[key])
        elif name in {"gen_ai.input.messages", "gen_ai.output.messages"} and "gen_ai.messages" in values:
            fallback.setdefault(name, values["gen_ai.messages"])
        elif name in LEGACY_INPUT_EVENTS:
            body = _event_body(values)
            content = body.get("content")
            if content is None and body.get("tool_calls") is not None:
                content = body["tool_calls"]
            if content is not None:
                legacy_in.append((str(body.get("role") or LEGACY_INPUT_EVENTS[name]), _message_event_text(content)))
        elif name == LEGACY_OUTPUT_EVENT:
            body = _event_body(values)
            message = _structured(body.get("message")) if "message" in body else body
            message = message if isinstance(message, dict) else body
            content = message.get("content")
            if content is None:
                content = message.get("tool_calls", body.get("tool_calls"))
            if content is not None:
                legacy_out.append((str(message.get("role") or "assistant"), _message_event_text(content)))
    return fallback, legacy_in, legacy_out


def _canonical(attrs: dict) -> tuple[dict, dict]:
    """Add current-name copies of legacy attributes; the current name wins. -> (attrs, aliases used)."""
    canonical, used = dict(attrs), {}
    for old, new in LEGACY_ATTRIBUTE_ALIASES.items():
        if old in attrs and new not in attrs:
            value = attrs[old]
            if old == "gen_ai.system" and isinstance(value, str):
                value = LEGACY_PROVIDER_VALUES.get(value, value)
            canonical[new] = value
            used[old] = new
    return canonical, used


def _from_unix_nano(nanos: int) -> datetime:
    """Exact integer arithmetic (float seconds mis-round at nanosecond scale); nearest microsecond."""
    return _EPOCH + timedelta(microseconds=(nanos + 500) // 1000)


def span_batches(request) -> list[SpanBatch]:
    """Map an ExportTraceServiceRequest, splitting at Nexus's 100-span limit.

    Validate the whole export before publishing anything. Original resource,
    scope, span attributes, events and links remain in metadata, even when an
    attribute also has a convenience alias for existing Nexus detectors.
    """
    spans = []
    for resource_spans in request.resource_spans:
        resource = _attributes(resource_spans.resource.attributes)
        for scope_spans in resource_spans.scope_spans:
            for source in scope_spans.spans:
                if len(source.trace_id) != 16 or not any(source.trace_id):
                    raise ValueError("traceId must be a nonzero 16-byte ID")
                if len(source.span_id) != 8 or not any(source.span_id):
                    raise ValueError("spanId must be a nonzero 8-byte ID")
                if source.parent_span_id and len(source.parent_span_id) != 8:
                    raise ValueError("parentSpanId must be an 8-byte ID")
                if source.end_time_unix_nano < source.start_time_unix_nano:
                    raise ValueError("span end precedes start")
                raw = _attributes(source.attributes)
                attrs, aliases_used = _canonical(raw)
                operation = attrs.get("gen_ai.operation.name", "")
                if operation == "execute_tool":
                    kind = SpanType.TOOL_CALL
                elif operation in {"invoke_agent", "create_agent", "plan", "invoke_workflow", "invoke_runner"}:
                    kind = SpanType.AGENT_STEP
                elif operation in {"chat", "text_completion", "generate_content", "embeddings", "realtime_inference", "fetch_response"}:
                    kind = SpanType.LLM_CALL
                elif operation == "retrieval":
                    kind = SpanType.RETRIEVAL
                elif operation == "search_memory":
                    kind = SpanType.MEMORY_READ
                elif operation in {"create_memory", "update_memory", "upsert_memory", "delete_memory", "create_memory_store", "delete_memory_store"}:
                    kind = SpanType.MEMORY_WRITE
                else:
                    kind = SpanType.CUSTOM
                metadata = {
                    "otel.attributes": raw,
                    "otel.resource": resource,
                    "otel.scope": _message_to_dict(scope_spans.scope),
                    "otel.span": _message_to_dict(source),
                    "otel.schema_url": scope_spans.schema_url or resource_spans.schema_url,
                }
                if aliases_used:
                    metadata["otel.legacy_aliases"] = aliases_used
                # The nexus.* namespace is ours: promoted verbatim (span wins over resource).
                for scope_attrs in (resource, raw):
                    for key, value in scope_attrs.items():
                        if key.startswith("nexus."):
                            metadata[key] = value
                for key, alias in {
                    "gen_ai.tool.name": "tool_name",
                    "gen_ai.request.model": "model",
                    "gen_ai.provider.name": "provider",
                    "gen_ai.usage.input_tokens": "input_tokens",
                    "gen_ai.usage.output_tokens": "output_tokens",
                }.items():
                    if key in attrs:
                        metadata[alias] = attrs[key]
                for key, alias in NEXUS_AGENT_ATTRIBUTES.items():
                    if key in raw:
                        metadata[alias] = _plan_steps(raw[key]) if alias == "plan_steps" else raw[key]
                tokens = [attrs.get(f"gen_ai.usage.{d}_tokens") for d in ("input", "output")]
                if any(t is not None for t in tokens):
                    metadata["tokens_used"] = sum(t for t in tokens if isinstance(t, (int, float)))
                fallback, legacy_in, legacy_out = _event_content(source.events)
                input_text = _input_content(attrs)
                if input_text is None:
                    input_text = _input_content(fallback)
                if input_text is None and legacy_in:
                    input_text = _joined(legacy_in)
                output_text = _output_content(attrs)
                if output_text is None:
                    output_text = _output_content(fallback)
                if output_text is None and legacy_out:
                    output_text = _joined(legacy_out)
                refs = {k: raw[k] for k in CONTENT_REF_KEYS if k in raw}
                if refs:
                    metadata["nexus.content_refs"] = refs
                if kind != SpanType.CUSTOM and input_text is None and output_text is None:
                    metadata["nexus.content_missing"] = True
                error_type = attrs.get("error.type")
                error_message = source.status.message or None
                for event in source.events:
                    if event.name == "exception":
                        exception = _attributes(event.attributes)
                        error_type = error_type or exception.get("exception.type")
                        error_message = error_message or exception.get("exception.message")
                if source.status.code == 2:
                    error_type = error_type or "OTelError"
                if not any(source.parent_span_id):
                    # Trace completion signal, as the Nexus SDK sets it: the root ends last.
                    metadata.setdefault("final", True)
                spans.append(Span(
                    trace_id=source.trace_id.hex(), span_id=source.span_id.hex(),
                    parent_span_id=source.parent_span_id.hex() if any(source.parent_span_id) else None,
                    agent_name=str(attrs.get("gen_ai.agent.name") or resource.get("service.name") or "otel-agent"),
                    span_type=kind, input=input_text or "", output=output_text,
                    duration_ms=(source.end_time_unix_nano - source.start_time_unix_nano) / 1_000_000,
                    client_timestamp=_from_unix_nano(source.start_time_unix_nano),
                    error_type=str(error_type) if error_type is not None else None,
                    error_message=error_message, metadata=metadata,
                    environment=str(resource.get("deployment.environment.name") or resource.get("deployment.environment") or "development"),
                    sdk_version=str(resource.get("telemetry.sdk.version") or "otel"),
                ))
    # A root span (``final``) completes its trace in the assembler, so within one export it must
    # be published after the other spans, whatever order the exporter wrote them in (some write
    # them in start order, root first). The sort is stable: everything else keeps its order.
    spans.sort(key=lambda s: bool(s.metadata.get("final")))
    return [SpanBatch(spans=spans[i:i + 100]) for i in range(0, len(spans), 100)]
