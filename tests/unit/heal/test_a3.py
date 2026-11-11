"""Amendment A3: the test sets are reproducible and test-only; test mode needs the freeze."""

from __future__ import annotations

from collections import Counter

import pytest

from bench.heal.freeze import NotFrozenError, assert_frozen
from bench.heal.sets import (TEST_SETS_PATH, SealedSplitError, assert_split, build_test_sets,
                             dev_splits, load_sets)


def test_committed_test_sets_match_the_code():
    assert build_test_sets() == load_sets(TEST_SETS_PATH)


def test_test_sets_are_test_only_and_follow_the_dev_rules():
    s = load_sets(TEST_SETS_PATH)
    splits = dev_splits()
    ids = {f["task_id"] for f in s["failures"]} | set(s["regression_a2"])
    ids |= {t for f in s["failures"] for t in f["heldout"]}
    assert {splits[t] for t in ids} == {"test"}
    assert len(s["failures"]) + len(s["excluded"]) == 60
    assert Counter(f["fault"] for f in s["failures"]) == {c: 12 for c in (
        "HALLUCINATION", "TOOL_MISFIRE", "CONTEXT_BLEED", "PLAN_DRIFT", "LOOP_DETECTED")}
    for f in s["failures"]:
        assert f["task_id"] not in f["heldout"]
        assert f["v11_label"] == f["fault"]
        assert 1 <= len(f["heldout"]) <= s["heldout_k"]
    assert len(s["regression_a2"]) == 29
    assert sum(t.startswith("qa-") for t in s["regression_a2"]) == 20


def test_split_guard_both_ways():
    s = load_sets(TEST_SETS_PATH)
    test_task = s["failures"][0]["task_id"]
    dev_task = load_sets()["failures"][0]["task_id"]
    assert_split([test_task], "test")
    with pytest.raises(SealedSplitError):
        assert_split([dev_task], "test")
    with pytest.raises(SealedSplitError):
        assert_split([test_task], "dev")


def test_test_mode_refuses_without_the_freeze_tag():
    with pytest.raises(NotFrozenError):
        assert_frozen("phase4-no-such-tag")
