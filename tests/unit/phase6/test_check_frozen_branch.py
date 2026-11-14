"""scripts/phase6/check_frozen.py refuses only on main; any other branch may run the frozen check."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.phase6 import check_frozen  # noqa: E402


def test_refuses_on_main():
    with pytest.raises(RuntimeError, match="not on main"):
        check_frozen.check_branch("main")


@pytest.mark.parametrize("branch", ["phase-6-demo", "media-refresh", "feature/main-docs", "mainline", ""])
def test_allows_any_other_branch_and_detached_head(branch):
    check_frozen.check_branch(branch)  # no exception


def test_main_runs_the_branch_rule_before_any_frozen_check(monkeypatch):
    """main() checks the branch first: on main it stops before touching the frozen tag."""
    calls = []

    def fake_git(*args):
        calls.append(args)
        if args[:2] == ("branch", "--show-current"):
            return b"main\n"
        raise AssertionError(f"frozen checks ran on main: git {args}")

    monkeypatch.setattr(check_frozen, "git", fake_git)
    with pytest.raises(RuntimeError, match="not on main"):
        check_frozen.main()
    assert calls == [("branch", "--show-current")]
