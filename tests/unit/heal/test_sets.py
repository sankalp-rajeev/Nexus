"""The pre-registered task sets are reproducible from committed data and dev-only."""

from __future__ import annotations

import os

from bench.heal.sets import REPO, SETS_PATH, assert_dev, build_sets, load_sets

SELECTION = os.path.join(REPO, "reports", "phase4", "phase3_selection.json")


def test_committed_sets_match_the_code():
    committed = load_sets(SETS_PATH)
    rebuilt = build_sets(SELECTION)
    assert rebuilt == committed


def test_sets_are_dev_only_and_well_formed():
    s = load_sets(SETS_PATH)
    ids = {f["task_id"] for f in s["failures"]} | set(s["regression"])
    ids |= {t for f in s["failures"] for t in f["heldout"]}
    assert_dev(ids)
    assert len(s["failures"]) + len(s["excluded"]) == 60
    assert len({f["failure_id"] for f in s["failures"]}) == len(s["failures"])
    for f in s["failures"]:
        assert f["task_id"] not in f["heldout"]
        assert len(f["heldout"]) == s["heldout_k"]
        assert f["v11_label"] == f["fault"]
    assert len(s["regression"]) == 12
    assert {t.split("-")[0] for t in s["regression"]} == {"qa", "tool", "plan", "mem"}


def test_a2_regression_widens_only_qa():
    """A2: every dev qa task that passes with no fault; other families unchanged."""
    from bench.heal.sets import dev_label_rows
    s = load_sets(SETS_PATH)
    a2 = s["regression_a2"]
    assert_dev(a2)
    passing_qa = {r["task_id"] for r in dev_label_rows()
                  if r["family"] == "qa" and r["fault"] == "NONE" and r["checker_pass"] == "True"}
    assert {t for t in a2 if t.startswith("qa-")} == passing_qa
    assert [t for t in a2 if not t.startswith("qa-")] == [
        t for t in s["regression"] if not t.startswith("qa-")]
    assert set(s["regression"]) <= set(a2) and len(a2) == len(set(a2)) == 29
