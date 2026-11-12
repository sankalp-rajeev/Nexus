"""Statistical and group-definition checks using invented, offline fixtures."""
import pytest
from scripts.phase5.analyse_run import GATES, STAGES, group_of, latency_group, percentiles


def fixture_record(total, states, decision="rejected"):
    return dict(total_s=total, stage_status=states, gate_decision=decision, status="ok",
                stages_s={s: 1.0 if states[s] == "complete" else 0.0 for s in STAGES})


def test_stage_split_ignores_duration_thresholds_and_retains_partial_cases():
    full = fixture_record(.001, {s: "complete" for s in STAGES})
    fast = fixture_record(999, {s: "skipped" if s in GATES else "complete" for s in STAGES})
    partial = fixture_record(50, dict(full["stage_status"], gate_regression="error"))
    assert group_of(full) == "full_gate"
    assert group_of(fast) == "fast_exit"
    assert group_of(partial) == "partial_or_interrupted"


def test_percentile_bootstrap_is_reproducible_and_handles_degenerate_samples():
    a = percentiles([1, 2, 3, 4, 5], "fixture")
    assert a == percentiles([1, 2, 3, 4, 5], "fixture")
    assert a["p50"] == 3
    assert a["p90"] == pytest.approx(4.6)
    assert percentiles([5] * 10, "constant")["ci95_p90"] == [5, 5]
    assert percentiles([], "empty")["n"] == 0
    with pytest.raises(ValueError):
        percentiles([float("nan")], "invalid")


def test_stage_shares_keep_skips_in_total_denominator():
    full = fixture_record(10, {s: "complete" for s in STAGES})
    fast = fixture_record(5, {s: "skipped" if s in GATES else "complete" for s in STAGES})
    result = latency_group([full, fast], "fixture")
    assert result["stages"]["gate_repair"]["n"] == 1
    assert result["stages"]["gate_repair"]["aggregate_share_of_total"] == pytest.approx(1 / 15)
    assert result["stages"]["gate_repair"]["state_counts"]["skipped"] == 1
    assert result["unattributed_overhead_s"] == 6
