"""Phase 4 reconciliation, loader compatibility and zero-call idempotent resume."""
import io
import json

import numpy as np
import pytest

from services.critic.dev_adapter import dev_labels
from services.critic.phase4_handoff import (
    contract_modules, export_record, partition_records, read_records, reconcile_sets,
)
from services.critic.round3_part_b import Round3Ledger, run_experiment
from services.critic.detector_adapter import critic_view, from_detector
from tests.unit.critic.test_groundwork import trace
from tests.unit.critic.test_round3 import StructuredDouble, VID


def prereg_fixture():
    rows = [{"trace_id": f"t{i}", "task_id": f"q{i}", "family": "qa", "fault": "HALLUCINATION",
             "provider": "deepseek", "model": "fixture", "label": "HALLUCINATION", "split": "dev"}
            for i in range(59)]
    failures = [{k: v for k, v in r.items() if k not in {"label", "split"}} | {
        "v11_label": r["label"], "selection_label": r["label"], "failure_id": f"failure-{i}"}
        for i, r in enumerate(rows)]
    return {"failures": failures}, rows


def test_all_preregistered_rows_are_checked_against_authoritative_dev_labels():
    sets, rows = prereg_fixture()
    selected, audit = reconcile_sets(sets, rows)
    assert len(selected) == 59 and audit["mismatch_count"] == 0
    rows[3]["label"] = "NORMAL"
    rows[9]["model"] = "wrong-model"
    selected, audit = reconcile_sets(sets, rows)
    assert audit["mismatch_count"] == 2
    assert {r["trace_id"] for r in audit["mismatches"]} == {"t3", "t9"}


def test_preregistration_refuses_duplicate_or_missing_trace_ids():
    sets, rows = prereg_fixture()
    sets["failures"][-1] = sets["failures"][0]
    with pytest.raises(ValueError, match="59 unique"):
        reconcile_sets(sets, rows)


def test_remote_label_stream_still_discards_test_payload_before_deserialization():
    stream = io.StringIO('run_id,trace_id,task_id,family,split,label\nr1,t1,q1,qa,dev,HALLUCINATION\nr2,t2,q2,qa,test,opaque,not,a,valid,row\n')
    assert list(dev_labels(stream)) == [{"run_id": "r1", "trace_id": "t1", "task_id": "q1", "family": "qa", "split": "dev", "label": "HALLUCINATION"}]


def test_partition_keeps_completed_detector_misses_and_excludes_only_outside_set():
    rows = [{"trace_id": "a", "arm": "new", "proposal": None},
            {"trace_id": "b", "arm": "new", "proposal": {"source": "fixture"}}]
    kept, excluded = partition_records(rows, {"a"})
    assert kept == rows[:1] and excluded == rows[1:]
    with pytest.raises(ValueError, match="Duplicate"):
        partition_records(rows+rows[:1], {"a"})


def test_exact_remote_phase4_loader_accepts_export_and_normalizes_prompt_alias(tmp_path):
    from bench.agent import _BASE_SYSTEM
    cfg, loader = contract_modules()
    record = {"trace_id": "fixture", "arm": "new", "evidence_mode": "detector",
        "c1_valid": True, "dry_run_applied": True,
        "proposal": {"target_component": "_BASE_SYSTEM", "patch_content": _BASE_SYSTEM,
                     "provenance": {"source": "llm", "model": "fixture"}, "fix_tag": "other_fix"}}
    failure = {"failure_id": "failure", "task_id": "task", "fault": "HALLUCINATION"}
    exported = export_record(record, failure, cfg, reused=True)
    assert exported["source"] == "llm" and exported["provenance"] == record["proposal"]["provenance"]
    assert exported["fix_tag"] == "reverts_injection"
    assert exported["proposal"]["phase3_exact_restore_tag"] == "other_fix"
    assert record["proposal"]["fix_tag"] == "other_fix"  # no in-place model-output mutation
    path = tmp_path / "new.jsonl"
    path.write_text(json.dumps(exported)+"\n", encoding="utf-8")
    loaded = loader.load_round3(str(path), "new", {"fixture": "HALLUCINATION"})
    assert loaded["fixture"].status == "patch"
    assert loaded["fixture"].phase3_fix_tag == "reverts_injection"
    path.write_text(json.dumps(exported)+"\n"+json.dumps(exported)+"\n", encoding="utf-8")
    with pytest.raises(ValueError, match="two new records"):
        loader.load_round3(str(path), "new", {"fixture": "HALLUCINATION"})


def test_resume_completed_trace_arm_pairs_never_calls_provider_or_appends(tmp_path):
    raw = trace()
    view = raw.model_copy(deep=True, update={"trace_id": VID})
    view.spans[0].trace_id = VID
    view = critic_view(view)
    rows = [{"trace_id": tid, "split": "dev", "label": "HALLUCINATION"} for tid in ("a", "b")]
    predictions = {"a": {"pred": "HALLUCINATION"}, "b": {"pred": "NORMAL"}}
    ev = {"a": from_detector(predictions["a"], view), "b": None}
    ledger = Round3Ledger(tmp_path / "calls.jsonl", "fixture")
    class Embeddings:
        def encode(self, texts):
            return np.ones((len(texts), 1)), [1]*len(texts)
    args = dict(rows=rows, traces={"a": raw, "b": raw}, predictions=predictions,
        views={"a": view, "b": view}, evidence=ev, legacy=None, ledger=ledger,
        config={"_BASE_SYSTEM": "Existing baseline prompt"}, embedder=Embeddings(), output=tmp_path,
        arms=("new", "v1_structured"))
    run_experiment(**args, providers={arm: StructuredDouble(ledger=ledger) for arm in args["arms"]})
    initial_bytes = {arm: (tmp_path/f"{arm}.jsonl").read_bytes() for arm in args["arms"]}
    calls = len(ledger.rows())
    completed = {arm: read_records(tmp_path/f"{arm}.jsonl") for arm in args["arms"]}
    class Forbidden:
        def complete_patch(self, *args, **kwargs):
            raise AssertionError("Completed trace/arm resent")
        complete_diagnosis = complete_patch
    run_experiment(**args, providers={arm: Forbidden() for arm in args["arms"]}, completed=completed)
    assert len(ledger.rows()) == calls == 3
    assert all((tmp_path/f"{arm}.jsonl").read_bytes() == initial_bytes[arm] for arm in args["arms"])
