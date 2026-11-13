"""NEXUS_HEALER_AUTO_APPLY: off by default (evaluate and log, never apply); on keeps the legacy path."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from services.healer.eval_runner import EvalResult

from services.healer import db as healer_db
from services.healer.consumer import AUTO_APPLY_ENV, HealerConsumer, auto_apply_from_env


def _proposal():
    return {"proposal_id": "patch_test01", "alert_id": "a1", "trace_id": "t1",
            "failure_type": "TOOL_MISFIRE", "patch_type": "TOOL_CONFIG_PATCH",
            "target_component": "search_tool", "patch_content": "{}"}


def _run(consumer: HealerConsumer):
    with (
        patch("services.healer.consumer.apply_patch", return_value="cfg-1") as apply,
        patch("services.healer.consumer.run_eval",
              side_effect=[EvalResult(composite_score=0.2), EvalResult(composite_score=0.8)]),
        patch("services.healer.consumer.log_eval_run", return_value="mlflow-1") as log,
        patch("services.healer.consumer.emit_health_diff") as emit,
    ):
        result = consumer.process_patch(_proposal())
    return result, apply, log, emit


@pytest.mark.parametrize("raw, expected", [
    (None, False), ("", False), ("false", False), ("0", False), ("no", False), ("maybe", False),
    ("true", True), ("TRUE", True), ("1", True), ("yes", True), ("on", True),
])
def test_env_parsing_defaults_to_off(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv(AUTO_APPLY_ENV, raising=False)
    else:
        monkeypatch.setenv(AUTO_APPLY_ENV, raw)
    assert auto_apply_from_env() is expected


def test_default_evaluates_and_logs_but_never_applies(monkeypatch, caplog):
    monkeypatch.delenv(AUTO_APPLY_ENV, raising=False)
    redis = MagicMock()
    consumer = HealerConsumer(conn=None, redis_client=redis, agent_run_fn=lambda i, n: ("out", None))
    assert consumer.auto_apply is False
    with caplog.at_level("INFO", logger="nexus.healer.consumer"):
        result, apply, log, emit = _run(consumer)
    apply.assert_not_called()           # no Config Store write, no config-update publish
    emit.assert_not_called()            # no health-diff event
    redis.publish.assert_not_called()
    log.assert_called_once()            # the evaluation is still logged
    assert result["applied"] is False and result["config_id"] is None
    assert result["health_diff_emitted"] is False
    assert "auto-apply disabled" in caplog.text


def test_true_applies_and_emits_legacy(monkeypatch):
    monkeypatch.setenv(AUTO_APPLY_ENV, "true")
    consumer = HealerConsumer(conn=None, redis_client=MagicMock(), agent_run_fn=lambda i, n: ("out", None))
    assert consumer.auto_apply is True
    result, apply, log, emit = _run(consumer)
    apply.assert_called_once()
    emit.assert_called_once()
    assert result["applied"] is True and result["config_id"] == "cfg-1"
    assert result["health_diff_emitted"] is True


def test_explicit_argument_overrides_env(monkeypatch):
    monkeypatch.setenv(AUTO_APPLY_ENV, "true")
    assert HealerConsumer(conn=None, auto_apply=False).auto_apply is False


def test_pending_fetch_skips_already_evaluated_when_auto_apply_is_off():
    """An evaluated-but-unapplied proposal stays PENDING_REVIEW; the poll must not re-run it."""
    cursor = MagicMock()
    cursor.description = []
    cursor.fetchall.return_value = []
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    healer_db.fetch_pending_patches(conn, exclude_evaluated=True)
    assert "NOT EXISTS (SELECT 1 FROM eval_runs" in cursor.execute.call_args[0][0]
    healer_db.fetch_pending_patches(conn)
    assert "eval_runs" not in cursor.execute.call_args[0][0]
