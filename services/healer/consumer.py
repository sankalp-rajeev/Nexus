"""Healer consumer — polls Postgres for PENDING_REVIEW patches and runs
the full 5-step healing workflow for each one.

Can be used directly in tests by passing mock dependencies.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable

from services.healer.eval_runner import run_eval
from services.healer.health_emitter import emit_health_diff
from services.healer.mlflow_logger import log_eval_run
from services.healer.patch_applicator import apply_patch
from services.healer.slack_notifier import notify_patch_proposal

logger = logging.getLogger("nexus.healer.consumer")

# Re-run sentinel: function signature (input_text, agent_name) -> (output, trace)
AgentRunFn = Callable[[str, str], tuple[str, dict | None]]


def _default_agent_run(input_text: str, agent_name: str) -> tuple[str, dict | None]:
    """Stub re-run: returns a generic success response.

    In production this calls the agent's /run endpoint; in tests it's replaced
    with a mock that reflects the patched behavior.
    """
    logger.warning(
        "healer: no agent_run_fn provided; using stub output for %s", agent_name
    )
    return f"[stub] task completed after patch: {input_text[:100]}", None


class HealerConsumer:
    def __init__(
        self,
        conn=None,
        redis_client=None,
        autonomous_mode: bool = True,
        auto_approve_delay_seconds: float = 0.0,
        slack_webhook_url: str | None = None,
        gemini_api_key: str | None = None,
        mlflow_tracking_uri: str | None = None,
        agent_run_fn: AgentRunFn = _default_agent_run,
        poll_interval_seconds: float = 5.0,
    ) -> None:
        self.conn = conn
        self.redis = redis_client
        self.autonomous_mode = autonomous_mode
        self.auto_approve_delay = auto_approve_delay_seconds
        self.slack_url = slack_webhook_url or os.getenv("SLACK_WEBHOOK_URL", "")
        self.gemini_key = gemini_api_key or os.getenv("GEMINI_API_KEY", "")
        self.mlflow_uri = mlflow_tracking_uri or os.getenv("MLFLOW_TRACKING_URI", "")
        self.agent_run_fn = agent_run_fn
        self.poll_interval = poll_interval_seconds

    # ── Public API ────────────────────────────────────────────────────────────

    def process_patch(self, proposal: dict[str, Any]) -> dict[str, Any]:
        """Execute the full 5-step healing workflow for one patch proposal.

        Returns a result dict with keys:
            config_id, before_score, after_score, score_delta,
            mlflow_run_id, health_diff_emitted
        """
        pid = proposal["proposal_id"]
        logger.info("healer: processing patch %s (%s)", pid, proposal.get("patch_type"))
        t_start = time.perf_counter()

        # ── STEP 1: NOTIFICATION ──────────────────────────────────────────────
        if self.slack_url and not self.autonomous_mode:
            notify_patch_proposal(proposal, self.slack_url)

        if self.autonomous_mode:
            if self.auto_approve_delay > 0:
                time.sleep(self.auto_approve_delay)
        else:
            # Human approval path — for now auto-approve after notification
            notify_patch_proposal(proposal, self.slack_url)

        # ── STEP 2: PATCH APPLICATION ─────────────────────────────────────────
        config_id = apply_patch(proposal, self.conn, self.redis)

        # ── STEP 3: EVAL RE-RUN ───────────────────────────────────────────────
        trace_info = self._fetch_trace(proposal["trace_id"])
        root_input = (trace_info or {}).get("root_input") or "evaluate agent output"
        agent_name = (trace_info or {}).get("agent_name") or "unknown_agent"
        before_output = (trace_info or {}).get("final_output") or ""

        before_result = run_eval(
            input_text=root_input,
            actual_output=before_output,
            gemini_api_key=self.gemini_key,
        )

        after_output, after_trace = self.agent_run_fn(root_input, agent_name)
        after_result = run_eval(
            input_text=root_input,
            actual_output=after_output,
            gemini_api_key=self.gemini_key,
        )

        score_delta = after_result.composite_score - before_result.composite_score

        # ── STEP 4: SCORE LOGGING ─────────────────────────────────────────────
        mlflow_run_id = log_eval_run(
            patch_id=pid,
            patch_type=proposal.get("patch_type", ""),
            failure_type=proposal.get("failure_type", ""),
            agent_name=agent_name,
            before_score=before_result.composite_score,
            after_score=after_result.composite_score,
            score_delta=score_delta,
            eval_duration_ms=before_result.eval_duration_ms + after_result.eval_duration_ms,
            per_metric={**{f"before_{k}": v for k, v in before_result.per_metric.items()},
                        **{f"after_{k}": v for k, v in after_result.per_metric.items()}},
            before_trace=trace_info,
            after_trace=after_trace,
            patch_content=proposal.get("patch_content", ""),
            tracking_uri=self.mlflow_uri,
        )

        if self.conn:
            self._write_eval_run(
                pid, proposal["trace_id"], agent_name,
                before_result, after_result, mlflow_run_id,
            )

        # ── STEP 5: HEALTH DIFF ───────────────────────────────────────────────
        health_emitted = False
        if self.redis:
            try:
                emit_health_diff(
                    self.redis, agent_name, pid,
                    proposal.get("failure_type", ""),
                    before_result.composite_score,
                    after_result.composite_score,
                    score_delta,
                    mlflow_run_id,
                )
                health_emitted = True
            except Exception as exc:
                logger.warning("healer: health_diff emit failed: %s", exc)

        elapsed_ms = (time.perf_counter() - t_start) * 1000
        logger.info(
            "healer: patch %s processed in %.0f ms | delta=%.3f | mlflow=%s",
            pid[:8], elapsed_ms, score_delta, mlflow_run_id,
        )
        return {
            "config_id": config_id,
            "before_score": before_result.composite_score,
            "after_score": after_result.composite_score,
            "score_delta": score_delta,
            "mlflow_run_id": mlflow_run_id,
            "health_diff_emitted": health_emitted,
            "elapsed_ms": elapsed_ms,
        }

    def run(self) -> None:
        """Blocking poll loop — runs until KeyboardInterrupt."""
        from services.healer import db as _db

        if self.conn is None:
            self.conn = _db.get_connection()

        logger.info(
            "healer: starting (autonomous=%s, poll_interval=%.1fs)",
            self.autonomous_mode, self.poll_interval,
        )
        while True:
            try:
                patches = _db.fetch_pending_patches(self.conn)
                for p in patches:
                    self.process_patch(p)
                if not patches:
                    time.sleep(self.poll_interval)
            except KeyboardInterrupt:
                logger.info("healer: shutting down")
                break
            except Exception as exc:
                logger.error("healer: poll loop error: %s", exc)
                time.sleep(self.poll_interval)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _fetch_trace(self, trace_id: str) -> dict | None:
        if self.conn is None:
            return None
        try:
            from services.healer import db as _db
            return _db.fetch_trace(self.conn, trace_id)
        except Exception as exc:
            logger.warning("healer: fetch_trace failed: %s", exc)
            return None

    def _write_eval_run(self, patch_id, trace_id, agent_name,
                        before_result, after_result, mlflow_run_id):
        try:
            from services.healer import db as _db
            _db.write_eval_run(
                self.conn, patch_id, trace_id, agent_name,
                before_result.composite_score, after_result.composite_score,
                {**before_result.per_metric, **after_result.per_metric},
                before_result.eval_duration_ms + after_result.eval_duration_ms,
                mlflow_run_id,
            )
        except Exception as exc:
            logger.warning("healer: write_eval_run failed: %s", exc)
