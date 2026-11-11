"""Pre-registered scoring rules (reports/phase2/preregistration.md §3)."""

from __future__ import annotations

import pytest

from bench.scoring import SealedSplitError, clopper_pearson, load_rows, score


def test_clopper_pearson_known_values():
    assert clopper_pearson(0, 10) == (0.0, pytest.approx(0.3085, abs=1e-4))
    assert clopper_pearson(10, 10) == (pytest.approx(0.6915, abs=1e-4), 1.0)
    lo, hi = clopper_pearson(5, 10)
    assert lo == pytest.approx(0.1871, abs=1e-4) and hi == pytest.approx(0.8129, abs=1e-4)
    assert clopper_pearson(0, 0) is None


def test_test_split_is_sealed():
    with pytest.raises(SealedSplitError):
        load_rows("test")


def _rows(labels, model="m"):
    return [{"trace_id": f"t{i}", "label": lab, "model": model} for i, lab in enumerate(labels)]


def test_other_failure_excluded_from_per_class_but_counts_as_any_failure():
    rows = _rows(["PLAN_DRIFT", "OTHER_FAILURE", "NORMAL"])
    preds = {"t0": "PLAN_DRIFT", "t1": "PLAN_DRIFT", "t2": "NORMAL"}
    res = score(rows, preds)["all"]
    pd = res["per_class"]["PLAN_DRIFT"]
    assert pd["precision"]["k"] == 1 and pd["precision"]["n"] == 1  # OTHER not a false positive
    assert pd["recall"]["value"] == 1.0
    assert res["any_failure"]["recall"]["k"] == 2  # OTHER flagged = true detection
    assert res["any_failure"]["other_failure_flagged"]["value"] == 1.0


def test_headline_and_secondary_macro():
    rows = _rows(["HALLUCINATION", "CONTEXT_BLEED", "PLAN_DRIFT", "NORMAL"])
    preds = {"t0": "HALLUCINATION", "t1": "NORMAL", "t2": "PLAN_DRIFT", "t3": "NORMAL"}
    pc = score(rows, preds)["all"]["per_class"]
    assert pc["macro_recall_headline"] == pytest.approx(2 / 3, abs=1e-4)
    assert pc["macro_recall_secondary_H_PD"] == 1.0
    assert pc["TOOL_MISFIRE"]["kind"] == "rule-defined"


def test_per_model_breakdown():
    rows = _rows(["HALLUCINATION"], "a") + [{"trace_id": "x", "label": "PLAN_DRIFT", "model": "b"}]
    res = score(rows, {"t0": "HALLUCINATION", "x": "NORMAL"})
    assert set(res["per_model"]) == {"a", "b"}
    assert res["per_model"]["b"]["per_class"]["headline_classes_scored"] == ["PLAN_DRIFT"]
