from __future__ import annotations

from datetime import datetime, timedelta, timezone
from queue import Full
from threading import Event
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from nexus_agent.models import Span
from services.collector.lite import LiteSpanProducer
from services.collector.main import app


def spans():
    return [Span(
        span_id=f"tool-{i}", trace_id="lite-test", agent_name="demo", span_type="tool_call",
        input='{"query":"same"}', output="waiting", duration_ms=1,
        metadata={"tool_name": "search"}, parent_span_id="root",
        client_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=i),
        sdk_version="test",
    ) for i in range(3)]


def test_queue_to_detectors_critic_sqlite_and_restart(tmp_path):
    path = str(tmp_path / "lite.db")
    producer = LiteSpanProducer(path)
    try:
        # These entry points must never be needed by the lite path.
        with patch("services.detectors.hallucination._nli", side_effect=AssertionError("model call")), patch("services.critic.graph.run_critic", side_effect=AssertionError("LLM graph")):
            for span in spans() * 2:
                producer.produce_span(span.trace_id, span.model_dump(mode="json"))
            assert producer.flush() == 0
        snapshot = producer.snapshot()
        assert len(snapshot["traces"][0]["spans"]) == 3
        assert len(snapshot["alerts"]) == len(snapshot["proposals"]) == len(snapshot["gate_decisions"]) == 1
        assert snapshot["alerts"][0]["failure_type"] == "LOOP_DETECTED"
        assert snapshot["proposals"][0]["source"] == "generic_fallback_no_llm"
        assert snapshot["gate_decisions"][0]["status"] == "placeholder"
        assert snapshot["gate_decisions"][0]["decision"] is None
        assert producer.is_connected()
    finally:
        producer.close()
    reopened = LiteSpanProducer(path)
    try:
        assert reopened.snapshot() == snapshot
    finally:
        reopened.close()
    with pytest.raises(RuntimeError, match="closed"):
        producer.produce_span("lite-test", spans()[0].model_dump(mode="json"))


def test_collector_lite_http_and_shutdown_drains(monkeypatch, tmp_path):
    path = str(tmp_path / "http.db")
    monkeypatch.setenv("NEXUS_QUEUE", "inprocess")
    monkeypatch.setenv("NEXUS_SQLITE_PATH", path)
    with patch("services.collector.main.KafkaSpanProducer", side_effect=AssertionError("Kafka")), TestClient(app) as client:
        assert client.post("/v1/spans", json={"spans": [s.model_dump(mode="json") for s in spans()]}).json()["accepted"] == 3
        health = client.get("/health").json()
        assert health["queue_backend"] == "inprocess" and health["kafka_connected"] is False
        assert health["queue_connected"] and health["status"] == "ok"
        with patch.object(app.state.producer, "produce_span", side_effect=Full):
            assert client.post("/v1/spans/single", json=spans()[0].model_dump(mode="json")).status_code == 503
    reopened = LiteSpanProducer(path)
    try:
        assert len(reopened.snapshot()["alerts"]) == 1
    finally:
        reopened.close()


def test_queue_rejects_invalid_key_and_reports_processing_errors(tmp_path):
    producer = LiteSpanProducer(str(tmp_path / "errors.db"))
    try:
        with pytest.raises(ValueError, match="key"):
            producer.produce_span("wrong", spans()[0].model_dump(mode="json"))
        with patch.object(producer, "_process", side_effect=RuntimeError("disk full")):
            producer.produce_span("lite-test", spans()[0].model_dump(mode="json"))
            assert producer.flush() == 1
        assert not producer.is_connected()
    finally:
        producer.close()


def test_queue_backpressure_is_bounded_and_recovers(tmp_path):
    producer = LiteSpanProducer(str(tmp_path / "bounded.db"), capacity=1)
    entered, release = Event(), Event()
    original = producer._process

    def process(span):
        entered.set()
        assert release.wait(5)
        original(span)

    try:
        with patch.object(producer, "_process", side_effect=process):
            producer.produce_span("lite-test", spans()[0].model_dump(mode="json"))
            assert entered.wait(5)
            producer.produce_span("lite-test", spans()[1].model_dump(mode="json"))
            with pytest.raises(Full):
                producer.produce_span("lite-test", spans()[2].model_dump(mode="json"))
            release.set()
            assert producer.flush() == 0
        assert len(producer.snapshot()["traces"][0]["spans"]) == 2
    finally:
        release.set()
        producer.close()


def test_span_ids_are_scoped_to_trace(tmp_path):
    producer = LiteSpanProducer(str(tmp_path / "ids.db"))
    try:
        for tid in ("trace-a", "trace-b"):
            span = spans()[0].model_copy(update={"trace_id": tid})
            producer.produce_span(tid, span.model_dump(mode="json"))
        assert producer.flush() == 0
        assert len(producer.snapshot()["traces"]) == 2
    finally:
        producer.close()
