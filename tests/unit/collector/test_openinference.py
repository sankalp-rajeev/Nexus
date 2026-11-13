"""Synthetic OpenInference exports only. Never load TRAIL in unit tests."""
from copy import deepcopy
import json

import pytest

from nexus_agent.models import SpanType
from services.collector.openinference import RETRIEVAL_TOOL_NAMES, complete_trace, to_otlp
from services.detectors import hallucination, pipeline
from services.detectors.common import planned_tools, tool_calls

TRACE_ID = "ab" * 16


def span(index=1, *, kind="AGENT", attrs=None, parent=None, start="2025-01-01T00:00:00Z", duration="PT1S", children=None):
    return {"trace_id": TRACE_ID, "span_id": f"{index:016x}", "parent_span_id": parent,
            "span_name": "synthetic", "timestamp": start, "duration": duration,
            "status_code": "Ok", "status_message": "", "resource_attributes": {"service.name": "synthetic-agent"},
            "span_attributes": {"openinference.span.kind": kind, **(attrs or {})},
            "events": [], "child_spans": children or []}


def convert(*spans):
    return complete_trace({"trace_id": TRACE_ID, "spans": list(spans)})


def test_nested_parents_content_and_completion_order():
    child = span(2, kind="TOOL", duration="PT0.25S", attrs={"tool.name": "lookup", "input.value": '{"id": "A-123"}', "tool.parameters": '{"id": {"type": "string"}}', "output.value": "synthetic result"})
    root = span(attrs={"input.value": "synthetic question", "output.value": "synthetic answer"}, children=[child])
    trace = convert(root)
    assert [s.span_id for s in trace.spans] == [child["span_id"], root["span_id"]]
    assert trace.spans[0].parent_span_id == root["span_id"]
    assert trace.root_input == "synthetic question"
    assert trace.final_output == "synthetic answer"
    assert trace.total_duration_ms == 1000
    call = tool_calls(trace)[0]
    assert call.tool == "lookup" and call.args == {"id": "A-123"}
    assert call.span.agent_name == "synthetic-agent"


def test_actual_tool_input_is_used_and_parameter_schema_is_retained():
    trace = convert(span(kind="TOOL", attrs={"tool.name": "lookup", "input.value": '{"args": [], "kwargs": {"x": 1}}', "tool.parameters": {"x": {"type": "integer"}}, "output.value": ["synthetic"]}))
    call = tool_calls(trace)[0]
    assert call.args == {"args": [], "kwargs": {"x": 1}}
    assert json.loads(call.span.output) == ["synthetic"]
    assert "input.value" in call.span.metadata["otel.attributes"]
    assert call.span.metadata["otel.attributes"]["tool.parameters"] == {"x": {"type": "integer"}}


def test_schema_without_actual_arguments_is_not_an_invocation():
    s = convert(span(kind="TOOL", attrs={"tool.parameters": {"x": {"type": "integer"}}, "output.value": "synthetic output"})).spans[0]
    assert s.input == ""
    assert s.metadata["nexus.arguments_missing"] is True


def test_tool_input_fallback_and_missing_capture_marker():
    assert tool_calls(convert(span(kind="TOOL", attrs={"input.value": {"x": 2}})))[0].args == {"x": 2}
    assert convert(span(kind="LLM")).spans[0].metadata["nexus.content_missing"] is True


@pytest.mark.parametrize("kind,expected", [("LLM", SpanType.LLM_CALL), ("TOOL", SpanType.TOOL_CALL), ("AGENT", SpanType.AGENT_STEP), ("CHAIN", SpanType.AGENT_STEP), ("RETRIEVER", SpanType.RETRIEVAL), ("EMBEDDING", SpanType.LLM_CALL), ("RERANKER", SpanType.CUSTOM), ("UNRECOGNIZED", SpanType.CUSTOM)])
def test_kinds(kind, expected):
    assert convert(span(kind=kind)).spans[0].span_type == expected


def test_indexed_messages_numeric_order_and_token_aliases():
    trace = convert(span(kind="LLM", attrs={
        "llm.input_messages.10.message.role": "user", "llm.input_messages.10.message.content": "last",
        "llm.input_messages.2.message.role": "system", "llm.input_messages.2.message.content": "first",
        "llm.output_messages.0.message.role": "assistant", "llm.output_messages.0.message.content": "answer",
        "llm.model_name": "synthetic-model", "llm.token_count.prompt": "10", "llm.token_count.completion": "3"}))
    s = trace.spans[0]
    assert s.input == "system: first\nuser: last"
    assert s.output == "answer"
    assert s.metadata["tokens_used"] == 13
    assert s.metadata["model"] == "synthetic-model"


def test_direct_messages_and_mixed_tool_message_are_not_dropped():
    trace = convert(span(kind="LLM", attrs={
        "llm.input_messages": json.dumps([{"role": "user", "content": "synthetic input"}]),
        "llm.output_messages.0.message.role": "assistant",
        "llm.output_messages.0.message.content": "synthetic preface",
        "llm.output_messages.0.message.tool_calls.0.tool_call.function.name": "lookup",
        "llm.output_messages.0.message.tool_calls.0.tool_call.function.arguments": '{"x": 1}'}))
    s = trace.spans[0]
    assert s.input == "synthetic input"
    parsed = json.loads(s.output)
    assert parsed[0]["parts"][0]["content"] == "synthetic preface"
    assert parsed[0]["parts"][1]["fields"]["tool_calls.0.tool_call.function.name"] == "lookup"


def test_status_and_exported_exception_event_with_inherited_timezone():
    source = span(kind="TOOL")
    source["status_code"] = "Error"
    source["events"] = [{"Timestamp": "2025-01-01T00:00:00.123456", "Name": "exception", "Attributes": {"exception.type": "SyntheticError", "exception.message": "synthetic failure"}}]
    s = convert(source).spans[0]
    assert s.error_type == "SyntheticError" and s.error_message == "synthetic failure"
    wire = to_otlp({"trace_id": TRACE_ID, "spans": [source]}).resource_spans[0].scope_spans[0].spans[0]
    assert wire.events[0].time_unix_nano - wire.start_time_unix_nano == 123456000


def test_direct_mixed_message_preserves_tool_call_alongside_text():
    s = convert(span(kind="LLM", attrs={"llm.output_messages": [
        {"role": "assistant", "content": "synthetic preface", "tool_calls": [{"name": "lookup"}]}]})).spans[0]
    parsed = json.loads(s.output)
    assert parsed[0]["parts"][0]["content"] == "synthetic preface"
    assert parsed[0]["parts"][1]["fields"]["tool_calls"] == [{"name": "lookup"}]


def test_explicit_plan_only_and_no_tool_name_inference():
    source = span(attrs={"input.value": "Please plan a lookup", "output.value": "I will use lookup"})
    assert planned_tools(convert(source)) is None
    source["span_attributes"].update({"nexus.agent.role": "planner", "nexus.agent.plan_steps": '["lookup"]'})
    assert planned_tools(convert(source)) == ["lookup"]
    retrieved = convert(span(kind="TOOL", attrs={"tool.name": "web_search", "output.value": "synthetic evidence text"})).spans[0]
    assert retrieved.span_type == SpanType.RETRIEVAL
    assert retrieved.metadata["tool_name"] == "web_search"


def test_exact_nanoseconds_and_iso_duration():
    source = span(start="2025-01-01T01:00:00.123456789+01:00", duration="PT1M2.000000001S")
    wire = to_otlp({"trace_id": TRACE_ID, "spans": [source]}).resource_spans[0].scope_spans[0].spans[0]
    assert wire.start_time_unix_nano % 1_000_000_000 == 123456789
    assert wire.end_time_unix_nano - wire.start_time_unix_nano == 62_000_000_001


def test_flat_attributes_alias_and_empty_structures():
    source = span(kind="TOOL", attrs={"tool.name": "lookup", "input.value": {}, "tool.parameters": {}, "synthetic.empty": []})
    source["attributes"] = source.pop("span_attributes")
    s = convert(source).spans[0]
    assert s.input == "{}"
    assert s.metadata["otel.attributes"]["synthetic.empty"] == []
    assert s.metadata["otel.attributes"]["tool.parameters"] == {}


def test_batch_boundary_keeps_all_spans_and_root():
    children = [span(i, kind="TOOL", duration="PT0.1S") for i in range(2, 104)]
    trace = convert(span(children=children))
    assert trace.span_count == 103
    assert trace.spans[-1].span_id == f"{1:016x}"


@pytest.mark.parametrize("fault", ["id", "duplicate", "foreign_trace", "parent_conflict", "cycle", "timezone", "duration", "status", "empty"])
def test_invalid_exports_fail_closed(fault):
    sources = [span()]
    if fault == "id": sources[0]["span_id"] = "not-an-id"
    elif fault == "duplicate": sources.append(deepcopy(sources[0]))
    elif fault == "foreign_trace": sources[0]["trace_id"] = "cd" * 16
    elif fault == "parent_conflict": sources[0]["child_spans"] = [span(2, parent=f"{3:016x}")]
    elif fault == "cycle": sources[0]["parent_span_id"] = sources[0]["span_id"]
    elif fault == "timezone": sources[0]["timestamp"] = "2025-01-01T00:00:00"
    elif fault == "duration": sources[0]["duration"] = "-PT1S"
    elif fault == "status": sources[0]["status_code"] = "arbitrary"
    elif fault == "empty": sources = []
    with pytest.raises(ValueError): convert(*sources)


def test_frozen_pipeline_synthetic_loop_and_misfire_without_nli(monkeypatch):
    def no_model():
        pytest.fail("No evidence is present: NLI must abstain before loading a model")
    monkeypatch.setattr("services.detectors.hallucination._nli", no_model)
    calls = [span(i, kind="TOOL", attrs={"tool.name": "lookup", "input.value": '{"x": 1}', "tool.parameters": '{"x": {"type": "integer"}}'}) for i in range(1, 4)]
    result = pipeline.compute_scores(convert(*calls))
    assert result.loop is True and result.halluc is None
    calls[0]["status_code"] = "Error"
    assert pipeline.compute_scores(convert(*calls)).misfire is True


@pytest.mark.parametrize("name", sorted(RETRIEVAL_TOOL_NAMES))
def test_a1_retrieval_tools_preserve_arguments_output_and_identity(name):
    source = span(kind="TOOL", attrs={"tool.name": name, "input.value": '{"query":"synthetic"}',
        "tool.parameters": {"query": {"type": "string"}}, "output.value": "Synthetic external source text for grounding.",
        "gen_ai.operation.name": "execute_tool"})
    trace = convert(source)
    s = trace.spans[0]
    assert trace.span_count == 1 and s.span_id == source["span_id"]
    assert s.span_type == SpanType.RETRIEVAL
    assert s.input == '{"query":"synthetic"}'
    assert s.output == "Synthetic external source text for grounding."
    assert s.metadata["tool_name"] == name
    assert s.metadata["otel.attributes"]["openinference.span.kind"] == "TOOL"
    assert s.metadata["otel.attributes"]["tool.parameters"] == {"query": {"type": "string"}}
    assert hallucination.retrieved_context(trace) == [s.output]


@pytest.mark.parametrize("name", ["final_answer", "find_archived_url", "visualizer", "synthetic_unknown", "WEB_SEARCH", "web_search_extra"])
def test_a1_nonmatching_tools_keep_original_type(name):
    assert convert(span(kind="TOOL", attrs={"tool.name": name})).spans[0].span_type == SpanType.TOOL_CALL


def test_a1_tool_name_does_not_retag_llm_and_retriever_kind_needs_no_name():
    assert convert(span(kind="LLM", attrs={"tool.name": "web_search"})).spans[0].span_type == SpanType.LLM_CALL
    trace = convert(span(kind="RETRIEVER", attrs={"output.value": "Synthetic retrieved document text."}))
    assert trace.spans[0].span_type == SpanType.RETRIEVAL
    assert hallucination.retrieved_context(trace) == ["Synthetic retrieved document text."]


@pytest.mark.parametrize("missing_output", [False, True])
def test_a1_missing_or_failed_retrieval_does_not_become_source(missing_output):
    source = span(kind="TOOL", attrs={"tool.name": "visit_page"})
    if not missing_output:
        source["span_attributes"]["output.value"] = "Synthetic error text must not become evidence."
        source["status_code"] = "Error"
    trace = convert(source)
    assert trace.spans[0].span_type == SpanType.RETRIEVAL
    assert hallucination.retrieved_context(trace) == []


def test_a1_retrieval_output_reaches_frozen_nli_branch_with_synthetic_model(monkeypatch):
    class SyntheticNLI:
        def predict(self, pairs, *, apply_softmax, batch_size):
            assert pairs and apply_softmax is True and batch_size == 16
            return [[0.0, 1.0, 0.0] for _ in pairs]
    monkeypatch.setattr(hallucination, "_nli", lambda: SyntheticNLI())
    source = span(attrs={"input.value": "What is the synthetic measurement?", "output.value": "The synthetic measurement is forty units."},
                  children=[span(2, kind="TOOL", attrs={"tool.name": "inspect_file_as_text", "output.value": "The synthetic measurement is forty units."})])
    assert pipeline.compute_scores(convert(source)).halluc is not None
