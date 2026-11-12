"""Promotion gate (Phase 4 pre-registration, reports/phase4/preregistration.md, item 1c).

Pure functions over deterministic pass/fail outcomes; no LLM judges anything.

* A task passes iff at least 2 of its 3 runs pass (``task_pass``).
* A patch is promoted only if all three hold:
    1. the failing task now passes;
    2. the held-out pass rate under the patch is strictly above the no-patch
       rate on the same tasks;
    3. no regression task goes from pass (no patch) to fail (patch).
* The old healer rule promotes when a single re-run of the same input improved:
  here, when seed 0 of the failing task passes (the original trace failed).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field

RUNS_PER_TASK = 3
PASS_AT = 2


def task_pass(runs: Sequence[bool]) -> bool:
    if len(runs) != RUNS_PER_TASK:
        raise ValueError(f"a task needs exactly {RUNS_PER_TASK} runs, got {len(runs)}")
    return sum(bool(r) for r in runs) >= PASS_AT


def pass_rate(outcomes: Mapping[str, bool]) -> float | None:
    return sum(outcomes.values()) / len(outcomes) if outcomes else None


@dataclass
class GateDecision:
    check1_own_task: bool
    check2_heldout: bool
    check3_no_regression: bool
    promoted: bool
    heldout_rate_patch: float | None
    heldout_rate_nopatch: float | None
    heldout_n: int
    regression_breaks: list[str] = field(default_factory=list)
    regression_checked: int = 0      # regression tasks that passed with no patch

    def as_dict(self) -> dict:
        return asdict(self)


def gate(*, own_task_pass: bool,
         heldout_patch: Mapping[str, bool], heldout_nopatch: Mapping[str, bool],
         regression_patch: Mapping[str, bool],
         regression_nopatch: Mapping[str, bool]) -> GateDecision:
    if set(heldout_patch) != set(heldout_nopatch):
        raise ValueError("held-out outcomes must cover the same tasks with and without the patch")
    if set(regression_patch) != set(regression_nopatch):
        raise ValueError("regression outcomes must cover the same tasks with and without the patch")
    hp, hn = pass_rate(heldout_patch), pass_rate(heldout_nopatch)
    check2 = hp is not None and hn is not None and hp > hn
    before = [t for t, ok in regression_nopatch.items() if ok]
    breaks = sorted(t for t in before if not regression_patch[t])
    check3 = not breaks
    return GateDecision(check1_own_task=bool(own_task_pass), check2_heldout=check2,
                        check3_no_regression=check3,
                        promoted=bool(own_task_pass) and check2 and check3,
                        heldout_rate_patch=hp, heldout_rate_nopatch=hn,
                        heldout_n=len(heldout_patch), regression_breaks=breaks,
                        regression_checked=len(before))


def old_rule_promotes(seed0_own_task_pass: bool) -> bool:
    """The pre-Phase-4 healer: promote if one re-run of the same input improved."""
    return bool(seed0_own_task_pass)


def is_false_promotion(promoted: bool, decision: GateDecision) -> bool:
    """Plan H4: promoted, but failed generalization (check 2) or broke a passing task (check 3)."""
    return promoted and not (decision.check2_heldout and decision.check3_no_regression)


def harmful_own_pass(decision: GateDecision) -> bool:
    """Pre-registration 1g ("P20-style"): fixes its own task but breaks regression tasks."""
    return decision.check1_own_task and not decision.check3_no_regression


def clopper_pearson(k: int, n: int, alpha: float = 0.05) -> tuple[float, float] | None:
    """Exact two-sided (1 - alpha) interval for k successes in n trials; None if n == 0."""
    if not 0 <= k <= n:
        raise ValueError("need 0 <= k <= n")
    if n == 0:
        return None
    from scipy.stats import beta
    lo = 0.0 if k == 0 else float(beta.ppf(alpha / 2, k, n - k + 1))
    hi = 1.0 if k == n else float(beta.ppf(1 - alpha / 2, k + 1, n - k))
    return (round(lo, 4), round(hi, 4))


def proportion(k: int, n: int) -> dict:
    return {"k": k, "n": n, "value": round(k / n, 4) if n else None,
            "ci95_clopper_pearson": clopper_pearson(k, n)}
