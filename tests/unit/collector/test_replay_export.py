"""CI guard for dashboard/public/replay.json (the published DEV replay).

Fails if the file is missing, carries placeholder/mock content, is not DEV-only, or is stale: any source
it was built from has changed, or its traces, headline numbers or heal bookkeeping no longer re-derive from
the in-repository sources. The raw Phase 5 runs live outside the repository, so heal bodies are verified
against the committed Phase 5 result files (and, locally, by `export_replay.py --check`).
"""
from __future__ import annotations

import copy
import json
import subprocess

import pytest

from dashboard.scripts import export_replay
from dashboard.scripts.export_replay import (
    DESTINATION,
    HEAL_RULES,
    SOURCES,
    assert_publishable,
    verify_committed,
)


@pytest.fixture(scope="module")
def committed():
    assert DESTINATION.is_file(), "dashboard/public/replay.json is missing: run dashboard/scripts/export_replay.py"
    return json.loads(DESTINATION.read_text(encoding="utf-8"))


def test_committed_replay_is_current_dev_only_and_free_of_placeholders(committed):
    assert verify_committed(committed) == []


def test_committed_replay_shape(committed):
    assert committed["split"] == "dev" and committed["read_only"] and committed["mode"] == "replay"
    assert committed["provenance"]["llm_calls"] == 0
    assert 8 <= len(committed["heals"]) <= 12
    assert len(committed["traces"]) >= 12
    decisions = {heal["gate"]["decision"] for heal in committed["heals"]}
    assert decisions == {"promoted", "rejected"}
    assert {rule[0] for rule in HEAL_RULES} == {h["category"] for h in committed["heals"]}
    assert not DESTINATION.read_text(encoding="utf-8").lower().count("placeholder")
    assert not DESTINATION.read_text(encoding="utf-8").lower().count("mock")
    # Every number carries the file it came from.
    items = [item for group in committed["headline"]["groups"] for item in group["items"]]
    assert len(items) >= 10
    assert all(item["source"]["path"] and item["source"]["locator"] for item in items)
    assert 0 < DESTINATION.stat().st_size < 600_000


def test_generated_from_commit_is_a_real_commit_when_history_is_available(committed):
    commit = committed["provenance"]["generated_from_commit"]
    assert len(commit) == 40
    shallow = subprocess.run(["git", "rev-parse", "--is-shallow-repository"], capture_output=True, text=True)
    if shallow.stdout.strip() == "true":
        pytest.skip("shallow clone: the export commit may not be fetched")
    exists = subprocess.run(["git", "cat-file", "-e", f"{commit}^{{commit}}"], capture_output=True)
    assert exists.returncode == 0


def test_missing_replay_is_reported(monkeypatch, tmp_path):
    monkeypatch.setattr(export_replay, "DESTINATION", tmp_path / "replay.json")
    with pytest.raises(ValueError, match="replay.json is missing"):
        export_replay.main(["--verify"])


@pytest.mark.parametrize("mutate, expected", [
    (lambda r: r["provenance"]["sources"].__setitem__(SOURCES[0], "0" * 40), "stale: "),
    (lambda r: r["provenance"]["sources"].pop(SOURCES[0]), "does not list"),
    (lambda r: r.__setitem__("split", "test"), "not a read-only DEV replay"),
    (lambda r: r.__setitem__("schema_version", 1), "not a read-only DEV replay"),
    (lambda r: r["notices"].append("a placeholder for later"), "Replay publication blocked"),
    (lambda r: r["heals"][0]["critic"].__setitem__("explanation", "Mock critic text"), "Replay publication blocked"),
    (lambda r: r["headline"]["groups"][0]["items"][0].__setitem__("value", "0.5"), "headline numbers differ"),
    (lambda r: r["traces"][0].__setitem__("final_output", "edited"), "trace blocks differ"),
    (lambda r: r["traces"].append({**r["traces"][0], "trace_id": "not-a-dev-trace"}), "traces must be exactly"),
    (lambda r: r["heals"][0]["gate"].__setitem__("decision", "rejected"), "inconsistent"),
    (lambda r: r["provenance"]["phase5_runs"]["main_run"].__setitem__("records_sha256", "0" * 64), "heal provenance"),
    (lambda r: r["provenance"].__setitem__("llm_calls", 3), "llm_calls"),
])
def test_stale_or_tampered_replay_is_rejected(committed, mutate, expected):
    altered = copy.deepcopy(committed)
    mutate(altered)
    problems = verify_committed(altered)
    assert problems and any(expected in problem for problem in problems), problems


def test_gemini_side_row_decision_must_match_committed_pairs(committed):
    altered = copy.deepcopy(committed)
    heal = next(h for h in altered["heals"] if h["run"] == "gemini")
    # Flip the recorded outcome consistently (checks and decision) so only the paired-decision rule can catch it.
    flipped = "promoted" if heal["gate"]["decision"] == "rejected" else "rejected"
    heal["gate"]["decision"] = flipped
    for check in heal["gate"]["checks"]:
        check["outcome"] = "pass" if flipped == "promoted" else "fail"
    problems = verify_committed(altered)
    assert any("gemini_side.json" in problem for problem in problems), problems


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


def test_publication_guard_accepts_recorded_data():
    assert_publishable({
        "mode": "replay", "split": "dev", "read_only": True,
        "traces": [{"trace_id": "dev-real"}],
        "heals": [{"gate": {"decision": "promoted"}, "critic": {"explanation": "Recorded text"}}],
        "provenance": {"sources": {"results/phase5/heal_latency_cost.json": "abc"}},
    })
