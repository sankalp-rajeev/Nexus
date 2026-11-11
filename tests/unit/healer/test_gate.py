"""The Phase 4 promotion gate (pre-registration item 1c)."""

from __future__ import annotations

import pytest

from services.healer.gate import (clopper_pearson, gate, harmful_own_pass, is_false_promotion,
                                  old_rule_promotes, task_pass)


def test_task_pass_is_two_of_three():
    assert task_pass([True, True, False]) and task_pass([True, True, True])
    assert not task_pass([True, False, False])
    with pytest.raises(ValueError):
        task_pass([True, True])


def G(own=True, hp=None, hn=None, rp=None, rn=None):
    hp = hp if hp is not None else {"a": True, "b": False}
    hn = hn if hn is not None else {"a": False, "b": False}
    rp = rp if rp is not None else {"r1": True, "r2": True}
    rn = rn if rn is not None else {"r1": True, "r2": True}
    return gate(own_task_pass=own, heldout_patch=hp, heldout_nopatch=hn,
                regression_patch=rp, regression_nopatch=rn)


def test_all_three_checks_promote():
    d = G()
    assert d.promoted and d.check1_own_task and d.check2_heldout and d.check3_no_regression
    assert d.heldout_rate_patch == 0.5 and d.heldout_rate_nopatch == 0.0


def test_own_task_must_pass():
    assert not G(own=False).promoted


def test_heldout_must_be_strictly_above_no_patch():
    d = G(hp={"a": True, "b": False}, hn={"a": True, "b": False})
    assert not d.check2_heldout and not d.promoted
    # The null patch is its own reference, so it can never pass check 2.
    same = {"a": True, "b": True}
    assert not G(hp=same, hn=same).check2_heldout


def test_regression_break_blocks_promotion_and_is_named():
    d = G(rp={"r1": True, "r2": False})
    assert d.regression_breaks == ["r2"] and not d.promoted
    assert harmful_own_pass(d)   # P20-style: fixes its own task, breaks a passing one


def test_tasks_failing_without_the_patch_are_not_regressions():
    d = G(rp={"r1": True, "r2": False}, rn={"r1": True, "r2": False})
    assert d.check3_no_regression and d.regression_checked == 1


def test_mismatched_task_sets_are_refused():
    with pytest.raises(ValueError):
        G(hp={"a": True}, hn={"b": False})
    with pytest.raises(ValueError):
        G(rp={"r1": True}, rn={"r2": True})


def test_old_rule_and_false_promotion():
    assert old_rule_promotes(True) and not old_rule_promotes(False)
    d = G(hp={"a": False, "b": False})          # own task fixed, does not generalise
    assert is_false_promotion(old_rule_promotes(True), d)
    assert not is_false_promotion(False, d)
    assert not is_false_promotion(True, G())


def test_clopper_pearson_known_values():
    assert clopper_pearson(0, 10) == (0.0, 0.3085)
    assert clopper_pearson(5, 10) == (0.1871, 0.8129)
    assert clopper_pearson(10, 10) == (0.6915, 1.0)
    assert clopper_pearson(0, 0) is None
