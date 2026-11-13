"""GenAI semconv pinning, legacy aliases, content projection and the missing-content flag."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

from nexus_agent.integrations import otel
from nexus_agent.integrations.otel import span_batches
from services.collector.main import app

ROOT = Path(__file__).resolve().parents[3]
TEXT = lambda role, text: [{"role": role, "parts": [{"type": "text", "content": text}]}]  # noqa: E731


def put(target, mapping):
    for key, value in mapping.items():
        attr = target.add(key=key).value
        if isinstance(value, bool):
            attr.bool_value = value
        elif isinstance(value, int):
            attr.int_value = value
        elif isinstance(value, float):
            attr.double_value = value
        elif isinstance(value, str):
            attr.string_value = value
        elif isinstance(value, dict):
            put(attr.kvlist_value.values, value)
        else:
            for item in value:
                if isinstance(item, dict):
                    put(attr.array_value.values.add().kvlist_value.values, item)
                else:
                    attr.array_value.values.add(string_value=item)


def spans_for(attributes=None, *, events=(), resource=None, operation="chat", start=1_000_000_000, end=1_001_000_000):
    request = ExportTraceServiceRequest()
    resource_spans = request.resource_spans.add()
    put(resource_spans.resource.attributes, resource or {"service.name": "svc"})
    wire = resource_spans.scope_spans.add().spans.add(
        trace_id=b"\x01" * 16, span_id=b"\x02" * 8, name="s", start_time_unix_nano=start, end_time_unix_nano=end)
    put(wire.attributes, ({"gen_ai.operation.name": operation} if operation else {}) | (attributes or {}))
    for name, values in events:
        put(wire.events.add(name=name, time_unix_nano=start).attributes, values)
    return span_batches(request)[0].spans[0]


def jtext(role, text):
    return json.dumps(TEXT(role, text))


# ── pinned versions ──────────────────────────────────────────────────────────

def test_pinned_versions_are_recorded_in_code_and_docs():
    assert re.fullmatch(r"[0-9a-f]{40}", otel.SEMCONV_GENAI_COMMIT)
    assert otel.SEMCONV_CORE_VERSION.startswith("v1.41.")
    docs = (ROOT / "docs" / "otel_mapping.md").read_text(encoding="utf-8")
    for pinned in (otel.SEMCONV_GENAI_COMMIT, otel.SEMCONV_CORE_VERSION, otel.SEMCONV_GENAI_REPO):
        assert pinned in docs


# ── attribute aliases ────────────────────────────────────────────────────────

def test_legacy_system_maps_to_provider_name():
    span = spans_for({"gen_ai.system": "openai"})
    assert span.metadata["provider"] == "openai"
    assert span.metadata["otel.legacy_aliases"] == {"gen_ai.system": "gen_ai.provider.name"}
    assert span.metadata["otel.attributes"]["gen_ai.system"] == "openai"  # raw attribute is untouched


@pytest.mark.parametrize("legacy,current", [
    ("vertex_ai", "gcp.vertex_ai"), ("gemini", "gcp.gemini"),
    ("az.ai.inference", "azure.ai.inference"), ("az.ai.openai", "azure.ai.openai"), ("anthropic", "anthropic"),
])
def test_legacy_system_values_follow_the_provider_renames(legacy, current):
    assert spans_for({"gen_ai.system": legacy}).metadata["provider"] == current


def test_current_provider_name_wins_over_legacy_system():
    span = spans_for({"gen_ai.system": "az.ai.openai", "gen_ai.provider.name": "openai"})
    assert span.metadata["provider"] == "openai"
    assert "otel.legacy_aliases" not in span.metadata


def test_provider_value_is_not_renamed_when_the_current_name_is_used():
    assert spans_for({"gen_ai.provider.name": "gemini"}).metadata["provider"] == "gemini"


def test_legacy_prompt_and_completion_tokens_map_to_input_and_output():
    span = spans_for({"gen_ai.usage.prompt_tokens": 11, "gen_ai.usage.completion_tokens": 4})
    assert (span.metadata["input_tokens"], span.metadata["output_tokens"], span.metadata["tokens_used"]) == (11, 4, 15)
    assert span.metadata["otel.legacy_aliases"] == {
        "gen_ai.usage.prompt_tokens": "gen_ai.usage.input_tokens",
        "gen_ai.usage.completion_tokens": "gen_ai.usage.output_tokens",
    }


def test_current_token_names_win_and_mixed_forms_combine():
    span = spans_for({"gen_ai.usage.input_tokens": 5, "gen_ai.usage.prompt_tokens": 99, "gen_ai.usage.completion_tokens": 2})
    assert (span.metadata["input_tokens"], span.metadata["output_tokens"], span.metadata["tokens_used"]) == (5, 2, 7)
    assert span.metadata["otel.legacy_aliases"] == {"gen_ai.usage.completion_tokens": "gen_ai.usage.output_tokens"}


# ── content: attributes ──────────────────────────────────────────────────────

def test_input_output_messages_attributes_project_to_text():
    span = spans_for({"gen_ai.input.messages": jtext("user", "What is 2+2?"), "gen_ai.output.messages": jtext("assistant", "4")})
    assert (span.input, span.output) == ("What is 2+2?", "4")
    assert "nexus.content_missing" not in span.metadata


def test_system_instructions_precede_the_input_messages():
    parts = json.dumps([{"type": "text", "content": "Be brief."}, {"type": "text", "content": "Use SI units."}])
    span = spans_for({"gen_ai.system_instructions": parts, "gen_ai.input.messages": jtext("user", "Height of K2?")})
    assert span.input == "system: Be brief.\nUse SI units.\nuser: Height of K2?"


def test_system_instructions_alone_are_the_input():
    span = spans_for({"gen_ai.system_instructions": json.dumps([{"type": "text", "content": "You translate."}])})
    assert span.input == "You translate." and span.output is None
    assert "nexus.content_missing" not in span.metadata


def test_multi_message_history_keeps_roles():
    history = json.dumps(TEXT("user", "hi") + TEXT("assistant", "hello") + TEXT("user", "bye"))
    assert spans_for({"gen_ai.input.messages": history}).input == "user: hi\nassistant: hello\nuser: bye"


def test_structured_anyvalue_messages_project_like_json_strings():
    structured = [{"role": "user", "parts": [{"type": "text", "content": "structured hi"}]}]
    assert spans_for({"gen_ai.input.messages": structured}).input == "structured hi"


def test_non_text_parts_stay_json_so_nothing_is_lost():
    history = json.dumps([{"role": "assistant", "parts": [{"type": "tool_call", "id": "c1", "name": "w", "arguments": {"q": 1}}]}])
    span = spans_for({"gen_ai.input.messages": history})
    assert span.input == history
    assert spans_for({"gen_ai.output.messages": history}).output == history


def test_plain_text_in_a_messages_attribute_is_kept_verbatim():
    assert spans_for({"gen_ai.input.messages": "not json at all"}).input == "not json at all"


def test_current_content_attribute_wins_over_legacy_attribute():
    span = spans_for({"gen_ai.input.messages": jtext("user", "current"), "gen_ai.prompt": "legacy",
                      "gen_ai.output.messages": jtext("assistant", "new"), "gen_ai.completion": "old"})
    assert (span.input, span.output) == ("current", "new")


def test_legacy_prompt_and_completion_attributes():
    span = spans_for({"gen_ai.prompt": "old prompt", "gen_ai.completion": "old completion"})
    assert (span.input, span.output) == ("old prompt", "old completion")


def test_legacy_indexed_prompt_and_completion_attributes():
    span = spans_for({"gen_ai.prompt.0.role": "system", "gen_ai.prompt.0.content": "rules",
                      "gen_ai.prompt.1.role": "user", "gen_ai.prompt.1.content": "question",
                      "gen_ai.completion.0.role": "assistant", "gen_ai.completion.0.content": "answer",
                      "gen_ai.prompt.name": "template-name"})
    assert span.input == "system: rules\nuser: question" and span.output == "answer"


def test_tool_retrieval_memory_and_documents_content():
    tool = spans_for({"gen_ai.tool.call.arguments": '{"q":1}', "gen_ai.tool.call.result": "ok"}, operation="execute_tool")
    assert (tool.input, tool.output) == ('{"q":1}', "ok")
    retrieval = spans_for({"gen_ai.retrieval.query.text": "find", "gen_ai.retrieval.documents": '[{"id":"d1"}]'}, operation="retrieval")
    assert (retrieval.input, retrieval.output) == ("find", '[{"id":"d1"}]')
    memory = spans_for({"gen_ai.memory.query.text": "tier", "gen_ai.memory.records": "gold"}, operation="search_memory")
    assert (memory.input, memory.output) == ("tier", "gold")


# ── content: events ──────────────────────────────────────────────────────────

def test_pre_1_37_per_message_events_supply_content():
    span = spans_for({"gen_ai.system": "openai"}, events=[
        ("gen_ai.system.message", {"content": "Be terse."}),
        ("gen_ai.user.message", {"content": "Capital of France?"}),
        ("gen_ai.choice", {"index": 0, "finish_reason": "stop", "message": json.dumps({"role": "assistant", "content": "Paris"})}),
    ])
    assert span.input == "system: Be terse.\nuser: Capital of France?"
    assert span.output == "Paris"
    assert "nexus.content_missing" not in span.metadata


def test_pre_1_37_events_with_the_json_blob_attribute():
    span = spans_for(events=[
        ("gen_ai.user.message", {"gen_ai.event.content": json.dumps({"content": "blob question", "role": "user"})}),
        ("gen_ai.choice", {"gen_ai.event.content": json.dumps({"index": 0, "finish_reason": "stop", "message": {"content": "blob answer"}})}),
    ])
    assert (span.input, span.output) == ("blob question", "blob answer")


def test_pre_1_37_events_keep_multiple_turns_and_tool_messages():
    span = spans_for(events=[
        ("gen_ai.user.message", {"content": "weather?"}),
        ("gen_ai.assistant.message", {"tool_calls": [{"id": "1", "type": "function"}]}),
        ("gen_ai.tool.message", {"content": "rainy", "id": "1"}),
        ("gen_ai.choice", {"index": 0, "message": {"content": "It is rainy."}}),
    ])
    assert span.input == 'user: weather?\nassistant: [{"id": "1", "type": "function"}]\ntool: rainy'
    assert span.output == "It is rainy."


def test_inference_details_event_carries_current_names():
    span = spans_for(events=[("gen_ai.client.inference.operation.details", {
        "gen_ai.input.messages": jtext("user", "from event"), "gen_ai.output.messages": jtext("assistant", "event reply"),
        "gen_ai.system_instructions": json.dumps([{"type": "text", "content": "sys"}]),
    })])
    assert span.input == "system: sys\nuser: from event" and span.output == "event reply"


def test_span_attributes_win_over_events():
    span = spans_for({"gen_ai.input.messages": jtext("user", "attribute")}, events=[("gen_ai.user.message", {"content": "event"})])
    assert span.input == "attribute"


def test_message_event_without_content_is_ignored():
    span = spans_for(events=[("gen_ai.user.message", {"role": "user"})])
    assert span.input == "" and span.metadata["nexus.content_missing"] is True


# ── missing content ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("operation", ["chat", "execute_tool", "search_memory", "retrieval", "invoke_agent"])
def test_span_without_content_is_flagged_not_dropped(operation):
    span = spans_for({"gen_ai.request.model": "m"}, operation=operation)
    assert span.input == "" and span.output is None
    assert span.metadata["nexus.content_missing"] is True


def test_non_genai_span_is_not_flagged():
    assert "nexus.content_missing" not in spans_for({"http.method": "GET"}, operation=None).metadata


def test_one_direction_of_content_is_enough_to_not_flag():
    assert "nexus.content_missing" not in spans_for({"gen_ai.output.messages": jtext("assistant", "hi")}).metadata


def test_externally_stored_content_is_missing_but_referenced():
    span = spans_for({"gen_ai.input.messages_ref": "s3://b/in.json", "gen_ai.output.messages_ref": "s3://b/out.json"})
    assert span.metadata["nexus.content_missing"] is True
    assert span.metadata["nexus.content_refs"] == {
        "gen_ai.input.messages_ref": "s3://b/in.json", "gen_ai.output.messages_ref": "s3://b/out.json"}


def test_documented_limit_contentless_repeats_look_like_a_loop_to_the_classifier_rules():
    """docs/otel_mapping.md: the flag is informational; the frozen-behaviour rules do not read it."""
    from datetime import datetime, timezone

    from nexus_agent.models import CompleteTrace
    from services.classifier.rules import apply_rules

    spans = []
    for i in range(3):
        span = spans_for({"gen_ai.request.model": "m"})
        span.span_id = f"{i:016x}"
        spans.append(span)
    trace = CompleteTrace(trace_id="t", agent_name="a", started_at=datetime.now(timezone.utc), spans=spans)
    assert all(s.metadata["nexus.content_missing"] for s in spans)
    assert apply_rules(trace).triggered_rule == "loop_detector"


def test_contentless_export_is_accepted_over_http(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_QUEUE", "inprocess")
    monkeypatch.setenv("NEXUS_SQLITE_PATH", str(tmp_path / "otel.db"))
    request = ExportTraceServiceRequest()
    wire = request.resource_spans.add().scope_spans.add().spans.add(
        trace_id=b"\x03" * 16, span_id=b"\x04" * 8, name="chat", start_time_unix_nano=1, end_time_unix_nano=2)
    put(wire.attributes, {"gen_ai.operation.name": "chat"})
    with TestClient(app) as client, patch.object(app.state.producer, "produce_span") as produce:
        response = client.post("/v1/traces", content=request.SerializeToString(), headers={"content-type": "application/x-protobuf"})
    assert response.status_code == 200
    published = produce.call_args.args[1]
    assert published["input"] == "" and published["metadata"]["nexus.content_missing"] is True


# ── nexus.* namespace, operations, timestamps, lazy imports ──────────────────

def test_nexus_synthetic_boolean_is_promoted_to_top_level_metadata():
    span = spans_for({"nexus.synthetic": True})
    assert span.metadata["nexus.synthetic"] is True
    # exactly what ClassifierService.is_synthetic reads
    assert span.metadata.get("nexus.synthetic") is True


def test_nexus_resource_attribute_is_promoted_and_span_attribute_wins():
    assert spans_for(resource={"nexus.synthetic": True}).metadata["nexus.synthetic"] is True
    both = spans_for({"nexus.tag": "span"}, resource={"nexus.tag": "resource", "nexus.other": "kept"})
    assert both.metadata["nexus.tag"] == "span" and both.metadata["nexus.other"] == "kept"


def test_string_true_is_not_the_synthetic_flag():
    assert spans_for({"nexus.synthetic": "true"}).metadata["nexus.synthetic"] == "true"


@pytest.mark.parametrize("operation", ["invoke_workflow", "invoke_runner"])
def test_workflow_and_runner_operations_are_agent_steps(operation):
    assert spans_for(operation=operation).span_type.value == "agent_step"


def test_timestamp_uses_exact_integer_arithmetic():
    span = spans_for(start=1_700_000_000_123_456_789, end=1_700_000_000_123_456_789 + 25_200)
    assert span.client_timestamp.isoformat() == "2023-11-14T22:13:20.123457+00:00"
    assert span.duration_ms == 0.0252


def test_base_sdk_import_pulls_in_no_otel_or_protobuf():
    code = (
        "import sys; import nexus_agent, nexus_agent.integrations.otel as o;"
        "bad = sorted(m for m in sys.modules if m.split('.')[0] == 'opentelemetry' or m.startswith('google.protobuf'));"
        "print(bad); assert not bad"
    )
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT / "sdk"), str(ROOT)])}
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=ROOT)
    assert result.returncode == 0, result.stdout + result.stderr


# -- plan attributes for PLAN_DRIFT (Nexus extension; semconv has no plan) ----

def test_nexus_agent_plan_attributes_become_detector_metadata():
    span = spans_for({"nexus.agent.role": "planner", "nexus.agent.plan_steps": ["get_order", "refund"]},
                     operation="invoke_agent")
    assert span.span_type.value == "agent_step"
    assert span.metadata["role"] == "planner" and span.metadata["plan_steps"] == ["get_order", "refund"]


def test_plan_steps_accept_a_json_array_string_or_a_single_step():
    assert spans_for({"nexus.agent.plan_steps": '["a", "b"]'}, operation="invoke_agent").metadata["plan_steps"] == ["a", "b"]
    assert spans_for({"nexus.agent.plan_steps": "only_step"}, operation="invoke_agent").metadata["plan_steps"] == ["only_step"]


def test_a_plan_in_app_attributes_is_not_guessed_into_detector_metadata():
    span = spans_for({"app.role": "planner", "app.plan_steps": ["a"]}, operation="invoke_agent")
    assert "role" not in span.metadata and "plan_steps" not in span.metadata
    assert span.metadata["otel.attributes"]["app.role"] == "planner"  # still preserved raw
