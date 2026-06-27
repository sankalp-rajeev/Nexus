"""End-to-end integration test: full Nexus healing loop.

Tests the complete pipeline:
  TOOL_MISFIRE alert → HealerConsumer.process_patch() →
  patch applied + eval scored + MLflow logged + HealthDiff emitted

Runs entirely in-process with mocked Postgres, Redis, MLflow and agent.
No Docker/Kafka required.

SCENARIO (test_full_loop_tool_misfire):
  A CrewAI-style agent calls a search tool with bad arguments (empty query),
  gets an error, retries identically. Nexus detects TOOL_MISFIRE, the critic
  proposes a TOOL_CONFIG_PATCH, and the healer applies it and re-evaluates.

ASSERTIONS:
  - patch applied (config_id returned)
  - after_score > before_score (improvement from patch)
  - score_delta >= 0.0
  - MLflow run logged (run_id returned)
  - HealthDiff emitted to Redis
  - MTTR (alert-to-MLflow-logged) <= 90 seconds
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch



# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_proposal(failure_type: str = "TOOL_MISFIRE",
                   patch_type: str = "TOOL_CONFIG_PATCH") -> dict[str, Any]:
    return {
        "proposal_id": str(uuid.uuid4()),
        "alert_id": str(uuid.uuid4()),
        "trace_id": "trace_e2e_test_001",
        "failure_type": failure_type,
        "patch_type": patch_type,
        "target_component": "test_crewai_agent:search_tool",
        "explanation": (
            "Search tool called with empty query string. "
            "Add non-empty query validation before dispatch."
        ),
        "patch_content": (
            "Add input validation: assert query.strip(), "
            "'Query must be non-empty before calling search tool'"
        ),
        "confidence": "HIGH",
        "estimated_impact": "Prevents empty-query errors; improves tool reliability",
        "root_cause_analysis": "Agent dispatcher not validating query before tool call",
        "status": "PENDING_REVIEW",
        "created_at": datetime.now(timezone.utc),
    }


def _make_trace_info(agent_name: str = "test_crewai_agent",
                     root_input: str = "Search for recent AI papers") -> dict:
    return {
        "trace_id": "trace_e2e_test_001",
        "agent_name": agent_name,
        "root_input": root_input,
        "final_output": "Tool call failed: empty query string",
        "status": "failed",
    }


def _mock_conn(trace_info: dict | None = None):
    """Return a MagicMock database connection."""
    conn = MagicMock()
    cur = MagicMock()
    cur.__enter__ = lambda s: s
    cur.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value = cur
    return conn


def _mock_redis():
    redis = MagicMock()
    redis.publish = MagicMock(return_value=1)
    return redis


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestFullLoopToolMisfire:
    """End-to-end test: TOOL_MISFIRE → heal → improved eval score."""

    def _run_healer(self, proposal, trace_info, after_output: str,
                    before_score: float = 0.3, after_score: float = 0.8):
        """Wire up HealerConsumer with all mocks and run process_patch."""
        from services.healer.consumer import HealerConsumer
        from services.healer.eval_runner import EvalResult

        redis = _mock_redis()
        conn = _mock_conn()

        with (
            patch("services.healer.consumer.apply_patch", return_value="cfg-123") as mock_apply,
            patch("services.healer.consumer.run_eval") as mock_eval,
            patch("services.healer.consumer.log_eval_run", return_value="mlflow-run-abc") as mock_mlf,
            patch("services.healer.consumer.emit_health_diff") as mock_hd,
            patch("services.healer.db.fetch_trace", return_value=trace_info),
        ):
            # Before eval returns low score; after eval returns high score
            mock_eval.side_effect = [
                EvalResult(composite_score=before_score,
                           per_metric={"answer_relevancy": before_score}),
                EvalResult(composite_score=after_score,
                           per_metric={"answer_relevancy": after_score}),
            ]

            agent_run_fn = lambda inp, name: (after_output, {"trace_id": "after_001"})

            consumer = HealerConsumer(
                conn=conn,
                redis_client=redis,
                autonomous_mode=True,
                auto_approve_delay_seconds=0.0,
                agent_run_fn=agent_run_fn,
            )
            t0 = time.perf_counter()
            result = consumer.process_patch(proposal)
            elapsed = (time.perf_counter() - t0) * 1000

            return result, elapsed, mock_apply, mock_eval, mock_mlf, mock_hd

    def test_tool_misfire_patch_applied(self):
        proposal = _make_proposal("TOOL_MISFIRE", "TOOL_CONFIG_PATCH")
        trace = _make_trace_info()
        result, *_ = self._run_healer(proposal, trace,
                                       after_output="Found 5 relevant AI papers")
        assert result["config_id"] == "cfg-123"

    def test_tool_misfire_score_improves(self):
        proposal = _make_proposal("TOOL_MISFIRE", "TOOL_CONFIG_PATCH")
        trace = _make_trace_info()
        result, *_ = self._run_healer(proposal, trace,
                                       after_output="Found 5 relevant AI papers",
                                       before_score=0.3, after_score=0.8)
        assert result["after_score"] > result["before_score"]
        assert result["score_delta"] >= 0.20

    def test_tool_misfire_mlflow_run_logged(self):
        proposal = _make_proposal("TOOL_MISFIRE", "TOOL_CONFIG_PATCH")
        trace = _make_trace_info()
        result, _, _, _, mock_mlf, _ = self._run_healer(
            proposal, trace, after_output="task completed"
        )
        assert result["mlflow_run_id"] == "mlflow-run-abc"
        mock_mlf.assert_called_once()
        call_kwargs = mock_mlf.call_args[1]
        assert call_kwargs["patch_type"] == "TOOL_CONFIG_PATCH"
        assert call_kwargs["failure_type"] == "TOOL_MISFIRE"
        assert call_kwargs["score_delta"] >= 0.20

    def test_tool_misfire_health_diff_emitted(self):
        proposal = _make_proposal("TOOL_MISFIRE", "TOOL_CONFIG_PATCH")
        trace = _make_trace_info()
        result, _, _, _, _, mock_hd = self._run_healer(
            proposal, trace, after_output="task completed"
        )
        assert result["health_diff_emitted"] is True
        mock_hd.assert_called_once()
        hd_kwargs = mock_hd.call_args[0]
        assert hd_kwargs[1] == "test_crewai_agent"  # agent_name

    def test_tool_misfire_mttr_under_90s(self):
        proposal = _make_proposal("TOOL_MISFIRE", "TOOL_CONFIG_PATCH")
        trace = _make_trace_info()
        _, elapsed_ms, *_ = self._run_healer(
            proposal, trace, after_output="task completed"
        )
        assert elapsed_ms < 90_000, f"MTTR {elapsed_ms:.0f}ms exceeded 90s"

    def test_apply_patch_called_with_correct_proposal(self):
        proposal = _make_proposal("TOOL_MISFIRE", "TOOL_CONFIG_PATCH")
        trace = _make_trace_info()
        _, _, mock_apply, *_ = self._run_healer(
            proposal, trace, after_output="task completed"
        )
        mock_apply.assert_called_once()
        call_args = mock_apply.call_args[0]
        assert call_args[0]["proposal_id"] == proposal["proposal_id"]
        assert call_args[0]["patch_type"] == "TOOL_CONFIG_PATCH"


class TestFullLoopHallucination:
    """End-to-end test: HALLUCINATION → PROMPT_PATCH → eval improvement."""

    def test_hallucination_patch_applied_and_improves(self):
        from services.healer.consumer import HealerConsumer
        from services.healer.eval_runner import EvalResult

        proposal = _make_proposal("HALLUCINATION", "PROMPT_PATCH")
        proposal["patch_content"] = (
            "Add grounding instruction: always cite retrieved context verbatim "
            "before synthesizing a response."
        )
        trace = _make_trace_info(
            root_input="What year was Python first released?",
        )
        trace["final_output"] = "Python was first released in 1994."  # wrong

        with (
            patch("services.healer.consumer.apply_patch", return_value="cfg-hall-456"),
            patch("services.healer.consumer.run_eval") as mock_eval,
            patch("services.healer.consumer.log_eval_run", return_value="mlflow-hall-run"),
            patch("services.healer.consumer.emit_health_diff"),
            patch("services.healer.db.fetch_trace", return_value=trace),
        ):
            mock_eval.side_effect = [
                EvalResult(composite_score=0.2,
                           per_metric={"answer_relevancy": 0.2}),
                EvalResult(composite_score=0.85,
                           per_metric={"answer_relevancy": 0.85}),
            ]
            consumer = HealerConsumer(
                conn=_mock_conn(),
                redis_client=_mock_redis(),
                autonomous_mode=True,
                agent_run_fn=lambda inp, name: (
                    "Python was first released in 1991 by Guido van Rossum.", None
                ),
            )
            result = consumer.process_patch(proposal)

        assert result["config_id"] == "cfg-hall-456"
        assert result["after_score"] > result["before_score"]
        assert result["score_delta"] >= 0.20
        assert result["mlflow_run_id"] == "mlflow-hall-run"
