from __future__ import annotations

import copy
import csv
import io
import json

import pytest

from dashboard.scripts import export_replay
from dashboard.scripts.export_replay import (
    SOURCES,
    assert_publishable,
    build_replay,
    committed_sources,
)


@pytest.fixture(scope="module")
def sources():
    return committed_sources()


def test_replay_uses_only_committed_dev_traces_and_explicit_placeholders(sources):
    content, blobs = sources
    replay = build_replay(content, blobs)
    assert replay == build_replay(content, blobs)
    rows = csv.DictReader(io.StringIO(content[SOURCES[1]].decode()))
    test_ids = {row["trace_id"] for row in rows if row["split"] == "test"}
    assert replay["split"] == "dev" and replay["read_only"]
    assert 6 <= len(replay["traces"]) <= 12
    assert replay["alerts"] and replay["proposals"] and replay["gate_decisions"]
    trace_ids = {trace["trace_id"] for trace in replay["traces"]}
    assert not trace_ids & test_ids
    assert all(p["trace_id"] in trace_ids and p["illustrative"] and p["excerpt_only"] for p in replay["proposals"])
    assert all(g["status"] == "placeholder" and g["decision"] is None for g in replay["gate_decisions"])
    assert not any(key in replay for key in ("health_scores", "eval_runs", "api_key"))
    assert set(replay["provenance"]["source_blobs"]) == set(SOURCES)
    assert all(len(blob) == 40 for blob in blobs.values())


def test_replay_rejects_non_dev_prediction(sources):
    content, blobs = sources
    altered = copy.copy(content)
    predictions = json.loads(altered[SOURCES[3]])
    predictions["predictions"]["non-dev"] = {"pred": "NORMAL"}
    altered[SOURCES[3]] = json.dumps(predictions).encode()
    with pytest.raises(ValueError, match="non-DEV"):
        build_replay(altered, blobs)


def test_replay_rejects_disagreement_with_task_split(sources):
    content, blobs = sources
    altered = copy.copy(content)
    splits = json.loads(altered[SOURCES[0]])
    splits = {key: "test" for key in splits}
    altered[SOURCES[0]] = json.dumps(splits).encode()
    with pytest.raises(ValueError, match="split"):
        build_replay(altered, blobs)


@pytest.mark.parametrize("marked", [
    {"gate_decisions": [{"status": "placeholder"}]},
    {"proposals": [{"source": "committed_MOCK_template"}]},
    {"provenance": {"source_blobs": {"results/critic_smoke_mock.json": "abc"}}},
    {"notices": ["These are not mock results"]},
    {"deep": [{"nested": {"provider": "MockProvider"}}]},
    {"placeholder": None},
    {"mock": False},
    {"proposals": [{"illustrative": True}]},
    {"proposals": [{"excerpt_only": True}]},
])
def test_publication_guard_rejects_all_nested_markers(marked):
    with pytest.raises(ValueError, match="Replay publication blocked"):
        assert_publishable(marked)


def test_publication_guard_accepts_unmarked_data():
    assert_publishable({
        "mode": "replay", "split": "dev", "read_only": True,
        "traces": [{"trace_id": "dev-real"}],
        "proposals": [{"source": "committed_evaluation", "illustrative": False}],
        "gate_decisions": [{"status": "evaluated", "decision": "PASS"}],
        "provenance": {"source_blobs": {"results/critic_dev/c1.json": "abc"}},
    })


def test_current_replay_is_blocked_before_export_writes_any_files(sources, monkeypatch, tmp_path):
    monkeypatch.setattr(export_replay, "committed_sources", lambda: sources)
    monkeypatch.setattr(export_replay, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="Replay publication blocked"):
        export_replay.main()
    assert not (tmp_path / "dashboard/public/replay.json").exists()
