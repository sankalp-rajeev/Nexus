"""Unit tests: NexusConfig, NexusClient build/record/flush, start/end span."""

from __future__ import annotations

import queue

import pytest

from nexus_agent.client import NexusClient
from nexus_agent.config import NexusConfig
from nexus_agent.models import SpanType


def test_config_requires_agent_name():
    with pytest.raises(ValueError):
        NexusConfig(agent_name="")


def test_config_rejects_bad_timeout():
    with pytest.raises(ValueError):
        NexusConfig(agent_name="a", export_timeout_ms=0)


def test_config_defaults():
    cfg = NexusConfig(agent_name="a")
    assert cfg.collector_url == "http://localhost:8000"
    assert cfg.async_export is True
    assert cfg.environment == "development"


def test_build_span_truncates_input_output():
    cfg = NexusConfig(agent_name="a", async_export=False, max_input_chars=5, max_output_chars=3)
    client = NexusClient(cfg)
    span = client.build_span(
        span_type=SpanType.LLM_CALL,
        span_id="span_x",
        trace_id="t",
        parent_span_id=None,
        input_text="abcdefghij",
        output_text="wxyz",
        duration_ms=1.0,
    )
    assert span.input == "abcde"
    assert span.output == "wxy"
    assert span.sdk_version  # populated from package version


def test_record_and_flush_exports(nexus_client):
    client, exporter = nexus_client
    span = client.build_span(
        span_type=SpanType.CUSTOM,
        span_id="span_1",
        trace_id="t1",
        parent_span_id=None,
        input_text="in",
        output_text="out",
        duration_ms=2.0,
    )
    client.record(span)  # async_export=False → exports synchronously
    assert len(exporter.spans) == 1
    assert exporter.spans[0].span_id == "span_1"


def test_start_and_end_span(nexus_client):
    client, exporter = nexus_client
    sid = client.start_span(SpanType.TOOL_CALL, tool_name="search")
    client.end_span(sid, output="done", metadata={"rows": 3})
    assert len(exporter.spans) == 1
    span = exporter.spans[0]
    assert span.span_id == sid
    assert span.output == "done"
    assert span.metadata["tool_name"] == "search"
    assert span.metadata["rows"] == 3
    assert span.duration_ms >= 0


def test_end_span_unknown_id_is_noop(nexus_client):
    client, exporter = nexus_client
    client.end_span("does_not_exist", output="x")  # must not raise
    assert exporter.spans == []


def test_queue_full_drops_fail_silent():
    cfg = NexusConfig(agent_name="a", async_export=False)
    client = NexusClient(cfg)
    client.config.async_export = True  # take the enqueue path in record()
    client._queue = queue.Queue(maxsize=1)
    s1 = client.build_span(span_type=SpanType.CUSTOM, span_id="s1", trace_id="t",
                           parent_span_id=None, input_text="", output_text=None, duration_ms=1.0)
    s2 = client.build_span(span_type=SpanType.CUSTOM, span_id="s2", trace_id="t",
                           parent_span_id=None, input_text="", output_text=None, duration_ms=1.0)
    client.record(s1)  # fills queue
    client.record(s2)  # dropped, must not raise
    assert client.stats["dropped"] == 1


def test_flush_is_fail_silent_when_exporter_raises(nexus_client):
    client, _ = nexus_client

    class Boom:
        def export(self, batch):
            raise RuntimeError("kapow")

        def close(self):
            pass

    client._exporter = Boom()
    client.config.async_export = True
    span = client.build_span(span_type=SpanType.CUSTOM, span_id="s", trace_id="t",
                             parent_span_id=None, input_text="", output_text=None, duration_ms=1.0)
    client._queue.put_nowait(span)
    client.flush()  # exporter raises internally → flush must not propagate


def test_stats_keys(nexus_client):
    client, _ = nexus_client
    assert set(client.stats) == {"queued", "exported", "dropped", "pending"}
