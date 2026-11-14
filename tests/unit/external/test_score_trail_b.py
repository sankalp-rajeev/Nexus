"""Synthetic B scorer checks; no benchmark or TRAIL fixtures/inference."""
import json
from types import SimpleNamespace
import pytest

from scripts.external import score_trail_b as b
from scripts.external.score_trail import load_requested, ratio


def record(tid="synthetic", version="v2", split="gaia", *, gold=None, loop=False, misfire=False, halluc=False, reason=None):
    return {"trace_id": tid, "version": version, "split": split,
        "gold": gold or {c: False for c in b.CLASSES},
        "flags": {"LOOP_DETECTED": loop, "TOOL_MISFIRE": misfire, "HALLUCINATION": halluc},
        "hallucination_reason": reason, "runtime_seconds": .1}


def test_B_loader_filter_precedes_trace_and_label_decode(tmp_path):
    wanted, sealed = "synthetic_b", "outside"
    (tmp_path / "trace").write_text(json.dumps({"trace_id": wanted}))
    (tmp_path / "label").write_text(json.dumps({"trace_id": wanted, "errors": []}))
    entries = {wanted: {"split": "gaia", "paths": {"trace": "trace", "labels": "label"}},
        sealed: {"split": "swe_bench", "paths": {"trace": "DO_NOT_OPEN", "labels": "DO_NOT_DECODE"}}}
    decoded = []
    def decode(blob):
        obj = json.loads(blob)
        decoded.append(obj["trace_id"])
        return obj
    assert len(list(load_requested(entries, {wanted}, tmp_path, decode=decode))) == 1
    assert decoded == [wanted, wanted]


def test_primary_independent_flags_C3_only_secondary_and_v1_unchanged():
    gold = {c: True for c in b.CLASSES}
    rows = [record(version=v, gold=gold, misfire=True, halluc=True) for v in b.VERSIONS]
    for v in b.VERSIONS:
        primary = b.tables(rows, v)
        assert primary["LOOP_DETECTED"]["fn"] == 1
        assert primary["TOOL_MISFIRE"]["tp"] == primary["HALLUCINATION"]["tp"] == 1
    assert b.tables(rows, "v1", "C3_secondary")["LOOP_DETECTED"]["fn"] == 1
    assert b.tables(rows, "v2", "C3_secondary")["LOOP_DETECTED"]["tp"] == 1


def test_abstentions_and_registered_exclusions_never_enter_confusion_counts():
    gold = dict.fromkeys(b.CLASSES, True)
    rows = [record("one", gold=gold, reason="no_successful_retrieval_text"),
        record("two", gold=gold, reason="no_checkable_claims"),
        record("three", gold=gold, reason="source_below_registered_readability_gate"),
        {"trace_id": "four", "version": "v2", "split": "gaia", "gold": None, "conversion_failure": True}]
    h = b.tables(rows, "v2")["HALLUCINATION"]
    assert h["cohort_denominator"] == 4 and h["evaluated"] == 0
    assert sum(h["abstentions"].values()) == sum(h["exclusions"].values()) == 2
    assert h["precision"] == h["recall"] == ratio(0, 0)
    assert h["gold_positive_in_cohort_assessable"] == 3


def test_gold_exclusion_precedes_hallucination_abstention_and_split_denominators():
    rows = [record("one", gold=dict.fromkeys(b.CLASSES, None), reason="no_successful_retrieval_text"),
        record("two", split="swe_bench")]
    gaia = b.tables(rows, "v2", split="gaia")["HALLUCINATION"]
    assert gaia["cohort_denominator"] == 1 and gaia["abstentions"] == {}
    assert gaia["exclusions"] == {"malformed_category_or_location": 1}
    assert b.tables(rows, "v2", split="swe_bench")["HALLUCINATION"]["tn"] == 1


def test_confusion_metrics_reuse_A_Wilson_and_zero_precision_denominator():
    rows = [record("one", gold=dict.fromkeys(b.CLASSES, True), loop=True),
        record("two", loop=True), record("three", gold=dict.fromkeys(b.CLASSES, True)), record("four")]
    m = b.tables(rows, "v2")["LOOP_DETECTED"]
    assert [m[k] for k in ("tp", "fp", "fn", "tn")] == [1, 1, 1, 1]
    assert m["precision"] == m["recall"] == ratio(1, 2)
    assert b.tables([record()], "v2")["LOOP_DETECTED"]["precision"] == ratio(0, 0)


def test_completed_version_checkpoint_survives_other_version_crash(tmp_path):
    calls = []
    thresholds = {"CONTEXT_BLEED": {"threshold": 1}, "PLAN_DRIFT": {"variant": "synthetic"}, "HALLUCINATION": {"threshold": .5034}}
    gold = dict.fromkeys(b.CLASSES, False)
    view = SimpleNamespace(spans=[], final_output="", root_input="")
    def compute(_):
        calls.append("v1")
        return SimpleNamespace(loop=True, misfire=True, bleed=None, drift={}, halluc=None)
    first = b.version_checkpoint("synthetic", "gaia", "v1", gold, view, thresholds, None, run=tmp_path, compute=compute)
    def crash(_):
        raise RuntimeError("synthetic crash")
    with pytest.raises(RuntimeError):
        b.version_checkpoint("synthetic", "gaia", "v2", gold, view, thresholds, None, run=tmp_path, compute=crash)
    # Resume must read v1's checkpoint without calling a detector again.
    assert b.version_checkpoint("synthetic", "gaia", "v1", gold, view, thresholds, None, run=tmp_path, compute=crash) == first
    assert calls == ["v1"]
    assert first["flags"]["LOOP_DETECTED"] and first["flags"]["TOOL_MISFIRE"]


def test_conversion_failure_creates_checkpoint_without_detectors(tmp_path):
    def never(_):
        pytest.fail("Rejected trace must not run any detector")
    r = b.version_checkpoint("synthetic", "gaia", "v1", None, None, {}, None, run=tmp_path, compute=never)
    assert r["conversion_failure"]
    assert b.tables([r], "v1")["LOOP_DETECTED"]["exclusions"] == {"conversion_failure": 1}
