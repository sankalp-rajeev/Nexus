"""OTLP wire interoperability using a real OTel SDK tracer, no sockets."""

from __future__ import annotations

import gzip
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from google.protobuf.json_format import MessageToDict
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import Status, StatusCode

from services.collector.main import app


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUS_QUEUE", "inprocess")
    monkeypatch.setenv("NEXUS_SQLITE_PATH", str(tmp_path / "otel.db"))
    with TestClient(app) as client:
        yield client


def attributes(target, values):
    for key, value in values.items():
        attr = target.add(key=key).value
        if isinstance(value, str):
            attr.string_value = value
        elif isinstance(value, bool):
            attr.bool_value = value
        elif isinstance(value, int):
            attr.int_value = value
        elif isinstance(value, float):
            attr.double_value = value
        else:
            for item in value:
                attr.array_value.values.add(string_value=item)


def sdk_request(spans):
    """Encode actual ReadableSpans to the official OTLP protobuf schema."""
    export = ExportTraceServiceRequest()
    for span in spans:
        resource = export.resource_spans.add()
        attributes(resource.resource.attributes, span.resource.attributes)
        scope = resource.scope_spans.add()
        scope.scope.name = span.instrumentation_scope.name
        scope.scope.version = span.instrumentation_scope.version or ""
        wire = scope.spans.add(
            trace_id=span.context.trace_id.to_bytes(16, "big"),
            span_id=span.context.span_id.to_bytes(8, "big"),
            parent_span_id=span.parent.span_id.to_bytes(8, "big") if span.parent else b"",
            name=span.name, kind=span.kind.value + 1,
            start_time_unix_nano=span.start_time, end_time_unix_nano=span.end_time,
        )
        wire.status.code = span.status.status_code.value
        wire.status.message = span.status.description or ""
        attributes(wire.attributes, span.attributes)
        for event in span.events:
            attributes(wire.events.add(name=event.name, time_unix_nano=event.timestamp).attributes, event.attributes)
    return export


@pytest.mark.parametrize("media_type", ["application/x-protobuf", "application/json"])
def test_real_otel_sdk_tracer_to_nexus_spans(client, media_type):
    responses = []

    class InProcessOTLPExporter(SpanExporter):
        def export(self, spans):
            request = sdk_request(spans)
            if media_type == "application/json":
                body = MessageToDict(request)
                for resource in body["resourceSpans"]:
                    for scope in resource["scopeSpans"]:
                        for source, sdk in zip(scope["spans"], spans):
                            source["traceId"] = f"{sdk.context.trace_id:032x}"
                            source["spanId"] = f"{sdk.context.span_id:016x}"
                            if sdk.parent:
                                source["parentSpanId"] = f"{sdk.parent.span_id:016x}"
                payload = json.dumps(body).encode()
            else:
                payload = request.SerializeToString()
            responses.append(client.post("/v1/traces", content=gzip.compress(payload), headers={
                "Content-Type": media_type, "Content-Encoding": "gzip",
            }))
            return SpanExportResult.SUCCESS

    provider = TracerProvider(resource=Resource({
        "service.name": "otel-demo", "deployment.environment.name": "dev",
        "telemetry.sdk.version": "sdk-test", "custom.resource": "kept",
    }))
    provider.add_span_processor(SimpleSpanProcessor(InProcessOTLPExporter()))
    tracer = provider.get_tracer("real-test", "1.0")
    with tracer.start_as_current_span("agent", attributes={"gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": "researcher"}) as root:
        with tracer.start_as_current_span("chat", attributes={
            "gen_ai.operation.name": "chat", "gen_ai.request.model": "recorded-model",
            "gen_ai.input.messages": '[{"role":"user","parts":[{"type":"text","content":"hello"}]}]',
            "gen_ai.output.messages": '[{"role":"assistant","parts":[{"type":"text","content":"hi"}]}]',
            "gen_ai.usage.input_tokens": 7, "gen_ai.usage.output_tokens": 3,
            "custom.span": ("a", "b"),
        }) as chat:
            chat.add_event("custom.event", {"preserved": True})
        with tracer.start_as_current_span("tool", attributes={
            "gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": "search",
            "gen_ai.tool.call.arguments": '{"query":"hello"}',
            "gen_ai.tool.call.result": '{"found":false}', "error.type": "SearchError",
        }) as tool:
            tool.record_exception(ValueError("failed lookup"))
            tool.set_status(Status(StatusCode.ERROR, "search unavailable"))
    provider.shutdown()
    assert len(responses) == 3 and all(r.status_code == 200 for r in responses)
    if media_type == "application/x-protobuf":
        assert all(not ExportTraceServiceResponse.FromString(r.content).HasField("partial_success") for r in responses)
    else:
        assert all(r.json() == {} for r in responses)
    assert app.state.producer.flush() == 0
    trace = client.get("/v1/lite/snapshot").json()["traces"][0]
    mapped = {s["span_id"]: s for s in trace["spans"]}
    root_span = mapped[f"{root.context.span_id:016x}"]
    llm = mapped[f"{chat.context.span_id:016x}"]
    tool_span = mapped[f"{tool.context.span_id:016x}"]
    assert root_span["agent_name"] == "researcher"
    assert root_span["span_type"] == "agent_step"
    assert llm["trace_id"] == f"{root.context.trace_id:032x}"
    assert llm["parent_span_id"] == root_span["span_id"]
    assert llm["span_type"] == "llm_call" and llm["agent_name"] == "otel-demo"
    assert json.loads(llm["input"])[0]["role"] == "user"
    assert json.loads(llm["output"])[0]["role"] == "assistant"
    assert llm["duration_ms"] == (chat.end_time - chat.start_time) / 1e6
    assert llm["environment"] == "dev" and llm["sdk_version"] == "sdk-test"
    assert llm["server_timestamp"] is not None
    assert llm["metadata"]["tokens_used"] == 10
    assert llm["metadata"]["otel.attributes"]["custom.span"] == ["a", "b"]
    assert llm["metadata"]["otel.resource"]["custom.resource"] == "kept"
    assert llm["metadata"]["otel.scope"]["name"] == "real-test"
    assert llm["metadata"]["otel.span"]["events"][0]["name"] == "custom.event"
    assert tool_span["span_type"] == "tool_call"
    assert tool_span["metadata"]["tool_name"] == "search"
    assert json.loads(tool_span["input"]) == {"query": "hello"}
    assert tool_span["error_type"] == "SearchError"
    assert tool_span["error_message"] == "search unavailable"


def payload(count=1):
    return {"resourceSpans": [{"scopeSpans": [{"spans": [{
        "traceId": "01" * 16, "spanId": f"{i + 1:016x}", "name": "chat",
        "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1001000000",
        "attributes": [{"key": "unknown", "value": {"kvlistValue": {"values": [
            {"key": "nested", "value": {"boolValue": True}},
        ]}}}],
    } for i in range(count)]}]}]}


def test_otlp_chunks_large_export_without_dropping_attributes(client):
    produced = []
    with patch.object(app.state.producer, "produce_span", side_effect=lambda key, value: produced.append(value)):
        response = client.post("/v1/traces", json=payload(101))
    assert response.status_code == 200 and len(produced) == 101
    assert produced[0]["span_type"] == "custom"
    assert produced[0]["metadata"]["otel.attributes"]["unknown"] == {"nested": True}


@pytest.mark.parametrize("body", [b"{", b'[]', b'{"resourceSpans":"bad"}', b'{"resourceSpans":[{"scopeSpans":[{"spans":[{"traceId":"xx"}]}]}]}'])
def test_invalid_otlp_returns_400_without_publishing(client, body):
    with patch.object(app.state.producer, "produce_span") as produce:
        response = client.post("/v1/traces", content=body, headers={"content-type": "application/json"})
    assert response.status_code == 400
    produce.assert_not_called()


def test_otlp_queue_failure_and_partial_success(client):
    with patch.object(app.state.producer, "produce_span", side_effect=RuntimeError("full")):
        assert client.post("/v1/traces", json=payload()).status_code == 503
    with patch.object(app.state.producer, "produce_span", side_effect=[None, RuntimeError("full")]):
        response = client.post("/v1/traces", json=payload(2))
    assert response.status_code == 200
    assert response.json()["partialSuccess"]["rejectedSpans"] == "1"


def test_otlp_empty_unsupported_and_compression_limits(client):
    assert client.post("/v1/traces", json={}).json() == {}
    assert client.post("/v1/traces", content=b"", headers={"content-type": "text/plain"}).status_code == 415
    assert client.post("/v1/traces", json={}, headers={"content-encoding": "br"}).status_code == 415
    assert client.post("/v1/traces", content=b"bad", headers={"content-type": "application/x-protobuf", "content-encoding": "gzip"}).status_code == 400
    assert client.post("/v1/traces", content=gzip.compress(b" " * (4 * 1024 * 1024 + 1)), headers={"content-type": "application/json", "content-encoding": "gzip"}).status_code == 413


def test_invalid_id_or_time_does_not_publish(client):
    bad = payload(2)
    bad["resourceSpans"][0]["scopeSpans"][0]["spans"][1]["endTimeUnixNano"] = "1"
    with patch.object(app.state.producer, "produce_span") as produce:
        assert client.post("/v1/traces", json=bad).status_code == 400
    produce.assert_not_called()


@pytest.mark.parametrize("operation,expected", [
    ("retrieval", "retrieval"), ("search_memory", "memory_read"),
    ("create_memory", "memory_write"), ("plan", "agent_step"),
])
def test_additional_genai_operations_and_zero_parent(client, operation, expected):
    body = payload()
    span = body["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    span["parentSpanId"] = "00" * 8
    span["attributes"].append({"key": "gen_ai.operation.name", "value": {"stringValue": operation}})
    with patch.object(app.state.producer, "produce_span") as produce:
        assert client.post("/v1/traces", json=body).status_code == 200
    assert produce.call_args.args[1]["span_type"] == expected
    assert produce.call_args.args[1]["parent_span_id"] is None
