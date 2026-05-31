"""Integration: span POST → collector → Kafka topic nexus.spans.raw.

Requires a running Kafka broker (and reads from it directly). Skipped
automatically when Kafka is not reachable, so the suite stays green without
Docker. Run the full path with:

    docker compose up -d kafka
    pytest tests/integration/test_collector_kafka.py -v
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone

import pytest

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
TOPIC = "nexus.spans.raw"


def _kafka_available() -> bool:
    try:
        from confluent_kafka.admin import AdminClient

        md = AdminClient({"bootstrap.servers": KAFKA_BOOTSTRAP}).list_topics(timeout=3)
        return md is not None
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(
    not _kafka_available(), reason="Kafka broker not reachable; integration test skipped"
)


@pytest.fixture
def collector_client():
    from fastapi.testclient import TestClient

    from services.collector.main import app

    with TestClient(app) as client:
        yield client


def _make_span(trace_id: str, marker: str) -> dict:
    return {
        "trace_id": trace_id,
        "agent_name": "itest-agent",
        "span_type": "llm_call",
        "input": marker,
        "output": "ok",
        "duration_ms": 1.0,
        "client_timestamp": datetime.now(timezone.utc).isoformat(),
        "sdk_version": "1.0.0",
    }


def test_health_reports_kafka_connected(collector_client):
    resp = collector_client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["kafka_connected"] is True
    assert body["status"] == "ok"


def test_post_batch_accepted(collector_client):
    trace_id = f"trace_{uuid.uuid4().hex[:12]}"
    batch = {"spans": [_make_span(trace_id, f"m{i}") for i in range(5)]}
    resp = collector_client.post("/v1/spans", json=batch)
    assert resp.status_code == 202
    body = resp.json()
    assert body["accepted"] == 5
    assert body["rejected"] == 0
    assert trace_id in body["trace_ids"]


def test_post_single_span(collector_client):
    trace_id = f"trace_{uuid.uuid4().hex[:12]}"
    resp = collector_client.post("/v1/spans/single", json=_make_span(trace_id, "single"))
    assert resp.status_code == 200
    assert resp.json()["trace_id"] == trace_id


def test_spans_appear_in_kafka(collector_client):
    from confluent_kafka import Consumer

    marker = f"probe_{uuid.uuid4().hex[:8]}"
    trace_id = f"trace_{uuid.uuid4().hex[:12]}"

    consumer = Consumer(
        {
            "bootstrap.servers": KAFKA_BOOTSTRAP,
            "group.id": f"itest_{uuid.uuid4().hex[:8]}",
            "auto.offset.reset": "earliest",
        }
    )
    consumer.subscribe([TOPIC])

    collector_client.post("/v1/spans", json={"spans": [_make_span(trace_id, marker)]})
    collector_client.app.state.producer.flush(5)

    found = False
    deadline = time.time() + 15
    while time.time() < deadline and not found:
        msg = consumer.poll(1.0)
        if msg is None or msg.error():
            continue
        payload = json.loads(msg.value())
        if payload.get("input") == marker:
            assert payload["server_timestamp"] is not None
            found = True
    consumer.close()
    assert found, "span with marker never appeared in nexus.spans.raw"


def test_collector_counts_received(collector_client):
    before = collector_client.get("/health").json()["spans_received_total"]
    trace_id = f"trace_{uuid.uuid4().hex[:12]}"
    collector_client.post("/v1/spans", json={"spans": [_make_span(trace_id, "count")]})
    after = collector_client.get("/health").json()["spans_received_total"]
    assert after == before + 1
