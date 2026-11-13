"""Official OTel exporter -> real loopback HTTP -> collector -> Kafka -> assembler -> classifier.

Uses ``opentelemetry-sdk`` and ``opentelemetry-exporter-otlp-proto-http`` (both pinned to 1.42.1)
exactly as an application would; nothing Nexus-specific on the sending side except the explicit
``nexus.synthetic=true`` marker, so no alert can reach a paid consumer.

Needs the nexus-phase6 stack: Kafka, Postgres, the collector on :8000, and the assembler and
classifier consuming ``nexus.spans.raw`` (critic and healer stopped). Skipped when any of that is
absent, which is the case for the CI integration job (infra containers only).

    docker compose --project-name nexus-phase6 up -d --wait kafka postgres redis \
        nexus-collector nexus-assembler nexus-classifier
"""

from __future__ import annotations

import json
import os
import socket
import time
import uuid

import httpx
import pytest

pytest.importorskip("opentelemetry.exporter.otlp.proto.http.trace_exporter")

from opentelemetry.exporter.otlp.proto.http import Compression  # noqa: E402
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter  # noqa: E402
from opentelemetry.sdk.resources import Resource  # noqa: E402
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExportResult  # noqa: E402

COLLECTOR = os.getenv("NEXUS_COLLECTOR_URL", "http://127.0.0.1:8000")
KAFKA = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:29092")
PG_HOST, PG_PORT = os.getenv("POSTGRES_HOST", "localhost"), int(os.getenv("POSTGRES_PORT", "55432"))
CLASSIFIED, ALERTS = "nexus.spans.classified", "nexus.alerts"
FAILURE_TYPES = {"NORMAL", "HALLUCINATION", "TOOL_MISFIRE", "CONTEXT_BLEED", "PLAN_DRIFT", "LOOP_DETECTED"}


def _stack_ready() -> bool:
    try:
        health = httpx.get(f"{COLLECTOR}/health", timeout=2, trust_env=False).json()
        if health.get("queue_backend") != "kafka" or not health.get("kafka_connected"):
            return False
        socket.create_connection((PG_HOST, PG_PORT), timeout=2).close()
        from confluent_kafka.admin import AdminClient

        admin = AdminClient({"bootstrap.servers": KAFKA})
        for future in admin.describe_consumer_groups(["nexus-classifier", "nexus-assembler"]).values():
            if not future.result(timeout=5).members:
                return False
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(
    not _stack_ready(),
    reason="needs the nexus-phase6 stack: collector :8000, Kafka, Postgres, assembler and classifier running",
)

PROMPT = "Use the lookup tool to find the refund policy, then answer in one sentence."
ANSWER = "Refunds are available within 30 days of purchase."


def _emit(kind: str, compression: Compression, run: str) -> dict:
    """Send one trace with the official SDK and exporter; return its ids and export results."""
    results: list[SpanExportResult] = []

    class Recording(OTLPSpanExporter):
        def export(self, spans, *args, **kwargs):
            result = super().export(spans, *args, **kwargs)
            results.append(result)
            return result

    provider = TracerProvider(resource=Resource.create({
        "service.name": f"otel-interop-{kind}-{run}", "deployment.environment.name": "interop-test",
    }))
    provider.add_span_processor(BatchSpanProcessor(Recording(
        endpoint=f"{COLLECTOR}/v1/traces", compression=compression, timeout=10)))
    tracer = provider.get_tracer("nexus-interop-test", "1")
    marker = {"nexus.synthetic": True}  # a real boolean; "true" would not suppress alerts
    calls = 3 if kind == "loop" else 1
    with tracer.start_as_current_span("invoke_agent support", attributes={
        "gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": f"support-{kind}", **marker,
    }) as root:
        with tracer.start_as_current_span("chat fake-model", attributes={
            "gen_ai.operation.name": "chat", "gen_ai.provider.name": "fake", "gen_ai.request.model": "fake-model",
            "gen_ai.input.messages": json.dumps([{"role": "user", "parts": [{"type": "text", "content": PROMPT}]}]),
            "gen_ai.output.messages": json.dumps([{"role": "assistant", "finish_reason": "stop",
                                                   "parts": [{"type": "text", "content": ANSWER}]}]),
            "gen_ai.usage.input_tokens": 21, "gen_ai.usage.output_tokens": 9, **marker,
        }) as chat:
            pass
        tools = []
        for i in range(calls):
            query = "refund policy" if kind == "loop" else f"refund policy v{i}"
            with tracer.start_as_current_span("execute_tool lookup", attributes={
                "gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": "lookup",
                "gen_ai.tool.call.arguments": json.dumps({"query": query}),
                "gen_ai.tool.call.result": json.dumps({"hits": 0 if kind == "loop" else 1}), **marker,
            }) as tool:
                tools.append(tool)
    provider.force_flush()
    provider.shutdown()
    return {
        "kind": kind, "trace_id": f"{root.context.trace_id:032x}", "root": f"{root.context.span_id:016x}",
        "chat": f"{chat.context.span_id:016x}", "tools": [f"{t.context.span_id:016x}" for t in tools],
        "span_count": 2 + calls, "results": results, "compression": compression.value,
    }


@pytest.fixture(scope="module")
def interop():
    from confluent_kafka import Consumer

    run = uuid.uuid4().hex[:6]
    sink = Consumer({"bootstrap.servers": KAFKA, "group.id": f"otel-interop-{run}", "auto.offset.reset": "earliest"})
    sink.subscribe([CLASSIFIED, ALERTS])
    sink.poll(2.0)
    before = httpx.get(f"{COLLECTOR}/health", trust_env=False).json()["spans_received_total"]
    sent = [_emit("loop", Compression.Gzip, run), _emit("normal", Compression.NoCompression, run)]
    after = httpx.get(f"{COLLECTOR}/health", trust_env=False).json()["spans_received_total"]
    wanted = {s["trace_id"] for s in sent}
    classified, alerts = {}, []
    deadline = time.time() + 150  # assembly completes after the 30 s inactivity timeout
    while time.time() < deadline and len(classified) < len(wanted):
        msg = sink.poll(1.0)
        if msg is None or msg.error():
            continue
        value = json.loads(msg.value())
        if value.get("trace_id") in wanted:
            (classified.__setitem__(value["trace_id"], value) if msg.topic() == CLASSIFIED else alerts.append(value))
    end = time.time() + 5  # a leaked alert would follow its classification within moments
    while time.time() < end:
        msg = sink.poll(1.0)
        if msg is not None and not msg.error() and msg.topic() == ALERTS and json.loads(msg.value()).get("trace_id") in wanted:
            alerts.append(json.loads(msg.value()))
    sink.close()
    return {"sent": {s["kind"]: s for s in sent}, "classified": classified, "alerts": alerts,
            "collector_delta": after - before, "run": run}


def _db():
    import psycopg2

    return psycopg2.connect(host=PG_HOST, port=PG_PORT, dbname=os.getenv("POSTGRES_DB", "nexus"),
                            user=os.getenv("POSTGRES_USER", "nexus"), password=os.getenv("POSTGRES_PASSWORD", "nexus_dev_password"))


def _assembled(trace_id: str, expected: int, wait: float = 20):
    deadline = time.time() + wait
    while True:
        with _db() as conn, conn.cursor() as cur:
            cur.execute("SELECT agent_name, environment, span_count FROM traces WHERE trace_id = %s", (trace_id,))
            trace = cur.fetchone()
            cur.execute("SELECT span_id, parent_span_id, span_type, input, output, metadata FROM spans WHERE trace_id = %s", (trace_id,))
            spans = cur.fetchall()
        if (trace and trace[2] == expected and len(spans) == expected) or time.time() > deadline:
            return trace, spans
        time.sleep(1)


def test_official_exporter_succeeds_over_loopback_http(interop):
    for sent in interop["sent"].values():
        assert sent["results"] and all(r == SpanExportResult.SUCCESS for r in sent["results"]), sent["results"]
    assert interop["collector_delta"] == sum(s["span_count"] for s in interop["sent"].values())
    assert httpx.get(f"{COLLECTOR}/health", trust_env=False).json()["queue_backend"] == "kafka"


@pytest.mark.parametrize("kind", ["loop", "normal"])
def test_trace_is_assembled_with_content_and_structure(interop, kind):
    sent = interop["sent"][kind]
    trace, spans = _assembled(sent["trace_id"], sent["span_count"])
    assert trace is not None, "assembler never wrote the trace"
    assert trace[1] == "interop-test" and trace[2] == sent["span_count"]
    by_id = {s[0]: s for s in spans}
    assert set(by_id) == {sent["root"], sent["chat"], *sent["tools"]}
    assert by_id[sent["root"]][1] is None
    assert by_id[sent["chat"]][1] == sent["root"] and by_id[sent["chat"]][2] == "llm_call"
    # content survived as plain text, token usage and the synthetic marker as metadata
    assert (by_id[sent["chat"]][3], by_id[sent["chat"]][4]) == (PROMPT, ANSWER)
    chat_meta = by_id[sent["chat"]][5] if isinstance(by_id[sent["chat"]][5], dict) else json.loads(by_id[sent["chat"]][5])
    assert chat_meta["tokens_used"] == 30 and chat_meta["provider"] == "fake" and chat_meta["nexus.synthetic"] is True
    assert all(by_id[t][2] == "tool_call" and by_id[t][1] == sent["root"] for t in sent["tools"])
    assert json.loads(by_id[sent["tools"][0]][3])["query"].startswith("refund policy")


def test_traces_are_classified(interop):
    loop, normal = interop["sent"]["loop"], interop["sent"]["normal"]
    assert set(interop["classified"]) == {loop["trace_id"], normal["trace_id"]}, "a trace was never classified"
    looped = interop["classified"][loop["trace_id"]]
    assert (looped["failure_type"], looped["triggered_rule"]) == ("LOOP_DETECTED", "loop_detector")
    assert looped["failure_span_id"] in loop["tools"]
    assert interop["classified"][normal["trace_id"]]["failure_type"] in FAILURE_TYPES


def test_synthetic_marker_suppresses_alerts(interop):
    assert interop["alerts"] == [], "a synthetic OTLP trace produced an alert"
