"""Publication reads only approved aggregate results, never raw TRAIL or TEST."""
import copy
import json
from pathlib import Path

import pytest

from scripts import trail_publication as pub
from scripts.phase5.pytest_dev_only import guard


@pytest.mark.parametrize("path", ["results/detect_test.json", "results/external/other_test.json",
    "data/external/trail/b_source/trace.json", "../.env"])
def test_only_exact_aggregate_paths_are_allowed(path):
    with pytest.raises(ValueError, match="approved"):
        pub.load_aggregate(path)


def test_export_is_an_allowlist_even_when_inputs_have_extra_text(monkeypatch):
    docs = {p: copy.deepcopy(pub.load_aggregate(p)) for p in pub.EXTERNAL_AGGREGATES}
    for doc in docs.values():
        doc["trace"] = {"span_text": "synthetic private canary"}
        doc["prompt"] = "synthetic private canary"
    docs[pub.B_RESULT]["mappings"]["primary"]["v2"]["classes"]["LOOP_DETECTED"]["output"] = "synthetic private canary"
    monkeypatch.setattr(pub, "load_aggregate", lambda path, root: docs[path])
    result = pub.build_external_trail()
    assert "synthetic private canary" not in json.dumps(result)
    assert len(result["rows"]) == 5 * len(pub.CLASSES)
    assert result["aggregate_only"] and not result["guardrail"]["v2_live_candidate"]


def test_metric_denominators_and_unregistered_reasons_fail_closed():
    node = pub.load_aggregate(pub.B_RESULT)["mappings"]["primary"]["v2"]["classes"]["LOOP_DETECTED"]
    broken = copy.deepcopy(node)
    broken["evaluated"] += 1
    with pytest.raises(ValueError, match="denominator"):
        pub.row(broken, "TRAIL-B", "v2", "LOOP_DETECTED", node["cohort_denominator"], pub.B_RESULT)
    broken = copy.deepcopy(node)
    broken["abstentions"] = {"unregistered text": 1}
    with pytest.raises(ValueError, match="Unregistered"):
        pub.row(broken, "TRAIL-B", "v2", "LOOP_DETECTED", node["cohort_denominator"], pub.B_RESULT)


def test_undefined_metrics_and_primary_secondary_scopes_are_preserved():
    data = pub.build_external_trail()
    old_loop = next(r for r in data["rows"] if r["cohort"] == "TRAIL-B" and r["version"] == "v1" and r["class_name"] == "LOOP_DETECTED")
    assert old_loop["precision"]["estimate"] is None
    assert old_loop["precision"]["wilson95"] is None
    assert {r["mapping"] for r in data["rows"] if r["cohort"] == "TRAIL-A"} == {"primary"}
    assert {r["mapping"] for r in data["rows"] if r["cohort"] == "TRAIL-B"} == {"primary", "C3_secondary"}


def test_test_audit_guard_keeps_nexus_and_unknown_external_results_sealed():
    root = Path(__file__).resolve().parents[3]
    for relative in (pub.A_RESULT, pub.B_RESULT):
        guard("open", (str(root / relative), "r", 0))
    for relative in ("results/detect_test.json", "results/external/not_approved_test.json"):
        with pytest.raises(RuntimeError, match="sealed TEST"):
            guard("open", (str(root / relative), "r", 0))
