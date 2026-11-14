"""Healer consumer — polls Postgres for PENDING_REVIEW patches and evaluates each one.

Auto-apply is OFF by default (``NEXUS_HEALER_AUTO_APPLY``, default ``false``). With it off the
healer evaluates a proposal and logs the scores (MLflow, ``eval_runs``) but never writes the patch
to the Config Store, never publishes a config update and never emits a health-diff event; each
proposal is evaluated once and stays ``PENDING_REVIEW``.

``NEXUS_HEALER_AUTO_APPLY=true`` keeps the legacy behaviour: apply the patch, re-run the eval,
emit a health diff. That path is LEGACY AND UNVERIFIED: it does not run the three-check promotion
gate (``services/healer/gate.py``), which so far runs only in the offline evaluation harness.

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

AUTO_APPLY_ENV = "NEXUS_HEALER_AUTO_APPLY"


def auto_apply_from_env(value: str | None = None) -> bool:
    """``NEXUS_HEALER_AUTO_APPLY``: true/1/yes/on enables it; unset or anything else is off."""
    raw = os.getenv(AUTO_APPLY_ENV, "") if value is None else value
    return raw.strip().lower() in {"1", "true", "yes", "on"}


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
        auto_apply: bool | None = None,
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
        # None reads NEXUS_HEALER_AUTO_APPLY; the default is off.
        self.auto_apply = auto_apply_from_env() if auto_apply is None else bool(auto_apply)
        self._evaluated: set[str] = set()   # proposals already evaluated with auto-apply off

    # ── Public API ────────────────────────────────────────────────────────────

    def process_patch(self, proposal: dict[str, Any]) -> dict[str, Any]:
        """Evaluate one patch proposal; apply it only when auto-apply is on (legacy).

        Returns a result dict with keys:
            config_id (None unless applied), applied, before_score, after_score, score_delta,
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

        # ── STEP 2: PATCH APPLICATION (only with auto-apply on; legacy, no gate) ──
        config_id = None
        if self.auto_apply:
            logger.warning("healer: auto-apply ON (legacy, unverified: the promotion gate is not run); "
                           "applying patch %s", pid)
            config_id = apply_patch(proposal, self.conn, self.redis)
        else:
            logger.info("healer: auto-apply disabled (%s=false); evaluating patch %s without applying it",
                        AUTO_APPLY_ENV, pid)

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

        # ── STEP 5: HEALTH DIFF (only for an applied patch) ──────────────────
        health_emitted = False
        if not self.auto_apply:
            self._evaluated.add(pid)
        elif self.redis:
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
            "applied": config_id is not None,
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
            "healer: starting (autonomous=%s, auto_apply=%s, poll_interval=%.1fs)",
            self.autonomous_mode, self.auto_apply, self.poll_interval,
        )
        if not self.auto_apply:
            logger.info("healer: auto-apply disabled (%s=false): proposals are evaluated and logged, "
                        "never applied", AUTO_APPLY_ENV)
        while True:
            try:
                # With auto-apply off a proposal stays PENDING_REVIEW, so skip the ones already
                # evaluated (an eval_runs row, or seen in this process) instead of re-running them.
                patches = _db.fetch_pending_patches(self.conn, exclude_evaluated=not self.auto_apply)
                patches = [p for p in patches if p["proposal_id"] not in self._evaluated]
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
