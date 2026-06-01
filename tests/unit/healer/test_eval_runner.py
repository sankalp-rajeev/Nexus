"""Unit tests for healer.eval_runner and healer.health_emitter."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from services.healer.eval_runner import EvalResult, run_eval
from services.healer.health_emitter import emit_health_diff


# ── eval_runner tests ─────────────────────────────────────────────────────────

class TestEvalRunner:
    def test_eval_result_dataclass(self):
        r = EvalResult(composite_score=0.75, per_metric={"a": 0.8, "b": 0.7})
        assert r.composite_score == pytest.approx(0.75)
        assert "a" in r.per_metric

    def test_run_eval_returns_result_with_deepeval_unavailable(self):
        """run_eval should not raise even when DeepEval/Gemini are unavailable."""
        with patch("services.healer.eval_runner._run_deepeval",
                   side_effect=ImportError("deepeval not installed")):
            with patch("services.healer.eval_runner._run_gemini_fallback",
                       return_value=EvalResult(0.5, {"default": 0.5})):
                result = run_eval("task input", "agent output")
        assert 0.0 <= result.composite_score <= 1.0
        assert result.eval_duration_ms >= 0

    def test_run_eval_fallback_score_in_range(self):
        with patch("services.healer.eval_runner._run_deepeval",
                   side_effect=RuntimeError("test error")):
            with patch("services.healer.eval_runner._run_gemini_fallback",
                       return_value=EvalResult(0.4, {"fallback": 0.4})):
                result = run_eval("some input", "some output")
        assert result.composite_score == pytest.approx(0.4)

    def test_eval_duration_is_populated(self):
        with (patch("services.healer.eval_runner._run_deepeval",
                    return_value=EvalResult(0.7, {"m": 0.7})),):
            result = run_eval("input", "output")
        assert result.eval_duration_ms >= 0


# ── health_emitter tests ──────────────────────────────────────────────────────

class TestHealthEmitter:
    def test_emit_publishes_to_correct_channel(self):
        redis = MagicMock()
        emit_health_diff(
            redis_client=redis,
            agent_name="test_agent",
            patch_id="patch-001",
            failure_type="TOOL_MISFIRE",
            before_score=0.3,
            after_score=0.8,
            score_delta=0.5,
            mlflow_run_id="run-xyz",
        )
        redis.publish.assert_called_once()
        channel, payload_str = redis.publish.call_args[0]
        assert channel == "nexus:health:test_agent"

    def test_emit_payload_structure(self):
        import json
        redis = MagicMock()
        emit_health_diff(
            redis_client=redis,
            agent_name="test_agent",
            patch_id="patch-001",
            failure_type="HALLUCINATION",
            before_score=0.2,
            after_score=0.9,
            score_delta=0.7,
        )
        _, payload_str = redis.publish.call_args[0]
        payload = json.loads(payload_str)
        assert payload["event"] == "health_diff"
        assert payload["improved"] is True
        assert payload["score_delta"] == pytest.approx(0.7)
        assert payload["agent_name"] == "test_agent"

    def test_emit_redis_failure_does_not_raise(self):
        redis = MagicMock()
        redis.publish.side_effect = ConnectionError("Redis down")
        # Should log a warning but not raise
        emit_health_diff(
            redis, "agent", "p-001", "TOOL_MISFIRE",
            0.3, 0.8, 0.5,
        )
