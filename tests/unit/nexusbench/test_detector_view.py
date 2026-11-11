"""Detector-input contract: nothing from labels.csv or the injection config is
reachable through bench.detector_view (Phase 2 pre-registration, item 1).

Runs over every committed trace. This only inspects inputs; it scores nothing.
"""

from __future__ import annotations

import csv
import glob
import json
import os

import pytest

from bench.detector_view import (
    RESIDUAL_INJECTION_TEXT,
    detector_view,
    detector_view_dict,
    view_id_for,
)
from bench.tools import DRIFT_CUSTOMER, DRIFT_INSTRUCTION, FAULTS
from bench.world import build_world

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DATA = os.path.join(REPO, "data", "nexusbench")
HAVE = os.path.exists(os.path.join(DATA, "traces.jsonl"))
pytestmark = pytest.mark.skipif(not HAVE, reason="NexusBench data not generated")

LABEL_NAMES = ["HALLUCINATION", "CONTEXT_BLEED", "PLAN_DRIFT", "TOOL_MISFIRE", "LOOP_DETECTED",
               "OTHER_FAILURE", "RUN_ERROR"]
CONFOUND_VALUES = ["deepseek", "qwen", "ollama"]
# Directories that hold detector code; they must not hardcode injection strings.
DETECTOR_DIRS = [os.path.join(REPO, "services", "classifier"),
                 os.path.join(REPO, "services", "detectors")]


def _rows():
    with open(os.path.join(DATA, "labels.csv"), encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        return reader.fieldnames, {r["trace_id"]: r for r in reader}


def _traces():
    with open(os.path.join(DATA, "traces.jsonl"), encoding="utf-8") as fh:
        for line in fh:
            yield json.loads(line)


def _keys(obj, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(k)
            _keys(v, out)
    elif isinstance(obj, list):
        for x in obj:
            _keys(x, out)
    return out


@pytest.fixture(scope="module")
def corpus():
    fields, rows = _rows()
    world = build_world()
    views = []
    for t in _traces():
        v = detector_view_dict(t)
        views.append((t, v, json.dumps(v)))
    return fields, rows, world, views


def test_view_is_valid_complete_trace(corpus):
    _, _, _, views = corpus
    t, _, _ = views[0]
    ct = detector_view(t)
    assert ct.trace_id == view_id_for(t["trace_id"])
    assert ct.spans


def test_no_label_column_is_a_key_in_any_view(corpus):
    fields, _, _, views = corpus
    forbidden = set(fields) - {"trace_id"}  # trace_id key holds the opaque view_id
    for _, v, _ in views:
        leaked = _keys(v, set()) & forbidden
        assert not leaked, f"label columns reachable as keys: {leaked}"


def test_no_label_values_reachable(corpus):
    _, rows, _, views = corpus
    for t, v, blob in views:
        r = rows[t["trace_id"]]
        for value in (r["trace_id"], r["run_id"], r["task_id"]):
            assert value not in blob, f"{value} reachable in view {v['trace_id']}"
        for name in LABEL_NAMES:
            assert name not in blob, f"label/fault name {name} reachable"
        for name in FAULTS:
            if name != "NONE":
                assert name not in blob
        low = blob.lower()
        for c in CONFOUND_VALUES:
            assert c not in low, f"model/provider '{c}' reachable (label confound)"


def test_no_injection_config_reachable(corpus):
    _, rows, world, views = corpus
    canaries = [u.canary for u in world.users]
    hexes = [c.split("-", 1)[1] for c in canaries]
    for t, v, blob in views:
        assert DRIFT_CUSTOMER not in blob and DRIFT_CUSTOMER.lower() not in blob.lower()
        for c, h in zip(canaries, hexes):
            assert c not in blob and h not in blob, "canary registry token reachable"
        # Only the reading session may appear; other users' sessions come from the registry.
        reader = {s.get("metadata", {}).get("session_id") for s in v["spans"]
                  if s["span_type"] == "memory_read"}
        for u in world.users:
            if u.session_id not in reader:
                assert u.session_id not in blob, "another user's session id reachable"
        for f in ("item_owners", "item_sessions", "item_users", "task_id", "family", "provider",
                  "model", "cached", "source"):
            assert f not in _keys(v, set())


def test_residual_strings_are_the_only_injection_text(corpus):
    """The drift note is kept (realistic), but its target id is pseudonymised."""
    _, _, _, views = corpus
    tail = DRIFT_INSTRUCTION.split("customer_id")[0]
    seen = any(tail in blob for _, _, blob in views)
    assert seen, "expected the drift note to survive in some views (it is real trace text)"


def test_detector_code_does_not_hardcode_injection_text():
    literals = list(RESIDUAL_INJECTION_TEXT.values()) + [DRIFT_CUSTOMER, "CANARY-", "REF-"]
    for d in DETECTOR_DIRS:
        for path in glob.glob(os.path.join(d, "**", "*.py"), recursive=True):
            src = open(path, encoding="utf-8").read()
            for lit in literals:
                assert lit not in src, f"{os.path.relpath(path, REPO)} hardcodes {lit!r}"


def test_memory_records_in_view_have_no_owner_fields(corpus):
    """Amendment 1: records visible to detectors carry no owner/session/user."""
    _, _, world, views = corpus
    owner_ids = {u.user_id for u in world.users}
    for _, v, _ in views:
        for s in v["spans"]:
            if s["span_type"] != "memory_read" or not s.get("output") or s.get("error_type"):
                continue
            for rec in json.loads(s["output"]):
                assert set(rec) == {"note"}
                assert not any(uid in rec["note"] for uid in owner_ids)
                assert "team-" not in rec["note"]
