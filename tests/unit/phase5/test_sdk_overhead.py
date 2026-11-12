"""Offline correctness checks for recorded-response replay, not performance tests."""
from unittest.mock import MagicMock
import pytest
import nexus_agent as nexus
from scripts.phase5.sdk_overhead import RecordedLLM, execute_task, load_workload, summary


def event(kind, text, output):
    return dict(kind=kind, input=text, output=output, metadata={}, error_type=None, error_message=None)


def task():
    return dict(root=event("agent_step", "recorded task", "recorded final"), steps=[dict(
        span=event("agent_step", "recorded step", None),
        children=[event("llm_call", "recorded prompt", '{"action":"done","answer":42}')])])


def test_replay_uses_saved_reply_and_enforces_saved_prompt_order():
    replay = RecordedLLM(task())
    with pytest.raises(ValueError, match="prompt order"):
        replay.complete("invented prompt")
    assert replay.complete("recorded prompt") == '{"action":"done","answer":42}'


def test_sdk_off_and_on_preserve_replayed_requests_responses_and_results():
    bare = execute_task(task(), False, "fixture")
    client = nexus.init(agent_name="fixture", async_export=False)
    client._exporter.close()
    exporter = MagicMock()
    exporter.export.return_value = True
    client._exporter = exporter
    instrumented = execute_task(task(), True, "fixture")
    nexus.shutdown()
    assert bare["signature"] == instrumented["signature"]
    assert bare["transcript"] == instrumented["transcript"]
    assert len(instrumented["step_ms"]) == 1
    assert exporter.export.call_count == 3  # task root, agent step, recorded LLM call


def test_workload_is_exact_registered_twenty_dev_occurrences():
    workload = load_workload()
    assert [t["occurrence_id"] for t in workload] == [f"heal-{i:03d}" for i in range(1, 21)]
    assert len({t["trace_id"] for t in workload}) == 20
    assert len({t["task_id"] for t in workload}) == 18
    assert sum(len(t["steps"]) for t in workload) == 113


def test_paired_latency_statistics_do_not_clip_negative_differences():
    values = summary([-1, 0, 1])
    assert values["n"] == 3
    assert values["p50_ms"] == 0
    assert values["p99_ms"] == pytest.approx(.98)
