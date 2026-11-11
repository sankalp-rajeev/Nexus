"""Lossless OTLP-to-Nexus projection; see reports/phase6/otel-mapping.md."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from google.protobuf.json_format import MessageToDict

from nexus_agent.models import Span, SpanBatch, SpanType


def _value(value):
    kind = value.WhichOneof("value")
    if kind == "array_value":
        return [_value(v) for v in value.array_value.values]
    if kind == "kvlist_value":
        return _attributes(value.kvlist_value.values)
    if kind == "bytes_value":
        return {"base64": MessageToDict(value)["bytesValue"]}
    return getattr(value, kind) if kind else None


def _attributes(attributes) -> dict:
    return {a.key: _value(a.value) for a in attributes}


def _text(value) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _content(attrs: dict, events, direction: str) -> str | None:
    keys = (
        ("gen_ai.tool.call.arguments", "gen_ai.input.messages", "gen_ai.retrieval.query.text", "gen_ai.memory.query.text", "gen_ai.prompt")
        if direction == "input" else
        ("gen_ai.tool.call.result", "gen_ai.output.messages", "gen_ai.memory.records", "gen_ai.completion")
    )
    for key in keys:
        if key in attrs:
            return _text(attrs[key])
    for event in events:
        values = _attributes(event.attributes)
        if event.name == f"gen_ai.{direction}.messages" and "gen_ai.messages" in values:
            return _text(values["gen_ai.messages"])
    return None


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
                attrs = _attributes(source.attributes)
                operation = attrs.get("gen_ai.operation.name", "")
                if operation == "execute_tool":
                    kind = SpanType.TOOL_CALL
                elif operation in {"invoke_agent", "create_agent", "plan"}:
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
                    "otel.attributes": attrs,
                    "otel.resource": resource,
                    "otel.scope": MessageToDict(scope_spans.scope),
                    "otel.span": MessageToDict(source),
                    "otel.schema_url": scope_spans.schema_url or resource_spans.schema_url,
                }
                for key, alias in {
                    "gen_ai.tool.name": "tool_name",
                    "gen_ai.request.model": "model",
                    "gen_ai.provider.name": "provider",
                    "gen_ai.usage.input_tokens": "input_tokens",
                    "gen_ai.usage.output_tokens": "output_tokens",
                }.items():
                    if key in attrs:
                        metadata[alias] = attrs[key]
                tokens = [attrs.get(f"gen_ai.usage.{d}_tokens") for d in ("input", "output")]
                if any(t is not None for t in tokens):
                    metadata["tokens_used"] = sum(t for t in tokens if isinstance(t, (int, float)))
                error_type = attrs.get("error.type")
                error_message = source.status.message or None
                for event in source.events:
                    if event.name == "exception":
                        exception = _attributes(event.attributes)
                        error_type = error_type or exception.get("exception.type")
                        error_message = error_message or exception.get("exception.message")
                if source.status.code == 2:
                    error_type = error_type or "OTelError"
                spans.append(Span(
                    trace_id=source.trace_id.hex(), span_id=source.span_id.hex(),
                    parent_span_id=source.parent_span_id.hex() if any(source.parent_span_id) else None,
                    agent_name=str(attrs.get("gen_ai.agent.name") or resource.get("service.name") or "otel-agent"),
                    span_type=kind, input=_content(attrs, source.events, "input") or "",
                    output=_content(attrs, source.events, "output"),
                    duration_ms=(source.end_time_unix_nano - source.start_time_unix_nano) / 1_000_000,
                    client_timestamp=datetime.fromtimestamp(source.start_time_unix_nano / 1e9, timezone.utc),
                    error_type=str(error_type) if error_type is not None else None,
                    error_message=error_message, metadata=metadata,
                    environment=str(resource.get("deployment.environment.name") or resource.get("deployment.environment") or "development"),
                    sdk_version=str(resource.get("telemetry.sdk.version") or "otel"),
                ))
    return [SpanBatch(spans=spans[i:i + 100]) for i in range(0, len(spans), 100)]
