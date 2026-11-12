"""Amendment A3: the dev freeze that must precede any Phase 4 test run.

Test mode (``Harness(split="test")``, the test critic and scoring) refuses to start
unless the tag ``phase4-dev-frozen`` is an ancestor of HEAD and none of the frozen
paths has changed since the tag (committed or in the working tree).
"""

from __future__ import annotations

import subprocess

from bench.heal.sets import REPO

FROZEN_TAG = "phase4-dev-frozen"
# Gate, outcome and scoring code; the harness and agent; the selected critic arm
# (prompts, graph, provider, config registry); the frozen Phase 2 detectors; the
# protocol (pre-registration, A1-A3) and the test sets and detector evidence.
FROZEN_PATHS = (
    "services/healer/gate.py",
    "bench/heal/outcomes.py", "bench/heal/score.py", "bench/heal/config.py",
    "bench/heal/critic.py", "bench/heal/generic.py", "bench/heal/harness.py",
    "bench/heal/agent.py", "bench/heal/sets.py", "bench/heal/a2.py",
    "bench/heal/test_phase.py", "bench/heal/freeze.py",
    "bench/agent.py", "bench/tools.py", "bench/world.py", "bench/labeler.py",
    "services/critic", "services/detectors", "bench/detector_view.py",
    "reports/phase4/preregistration.md", "reports/phase4/amendment_a1.md",
    "reports/phase4/amendment_a2.md", "reports/phase4/amendment_a3.md",
    "reports/phase4/prereg_sets.json", "reports/phase4/prereg_sets_test.json",
    "reports/phase4/test/evidence.json",
)


class NotFrozenError(RuntimeError):
    """Raised when test mode is requested before (or after a change to) the freeze."""


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", f"safe.directory={REPO}", *args], cwd=REPO,
                          capture_output=True, text=True)


def assert_frozen(tag: str = FROZEN_TAG) -> str:
    """Return the tag's commit; raise ``NotFrozenError`` unless the freeze holds."""
    rev = _git("rev-parse", "--verify", "--quiet", f"refs/tags/{tag}^{{commit}}")
    if rev.returncode != 0:
        raise NotFrozenError(f"tag {tag} does not exist: the test split stays sealed")
    commit = rev.stdout.strip()
    if _git("merge-base", "--is-ancestor", commit, "HEAD").returncode != 0:
        raise NotFrozenError(f"{tag} is not an ancestor of HEAD")
    changed = _git("diff", "--name-only", commit, "--", *FROZEN_PATHS).stdout.split()
    if changed:
        raise NotFrozenError(f"frozen paths changed since {tag}: {changed[:5]}")
    return commit
