"""MLflow logging utilities for the healer's before/after eval scores."""

from __future__ import annotations

import logging
import os
import tempfile
import json

logger = logging.getLogger("nexus.healer.mlflow_logger")


def log_eval_run(
    patch_id: str,
    patch_type: str,
    failure_type: str,
    agent_name: str,
    before_score: float,
    after_score: float,
    score_delta: float,
    eval_duration_ms: float,
    per_metric: dict[str, float],
    before_trace: dict | None = None,
    after_trace: dict | None = None,
    patch_content: str = "",
    tracking_uri: str | None = None,
) -> str | None:
    """Log a healer eval run to MLflow. Returns run_id or None on failure."""
    uri = tracking_uri or os.getenv("MLFLOW_TRACKING_URI", "")
    if not uri:
        logger.warning("healer: MLFLOW_TRACKING_URI not set; skipping MLflow logging")
        return None

    try:
        import mlflow

        mlflow.set_tracking_uri(uri)
        mlflow.set_experiment("nexus-healer")

        with mlflow.start_run(run_name=f"patch-{patch_id[:8]}") as run:
            mlflow.log_params({
                "patch_id": patch_id,
                "patch_type": patch_type,
                "failure_type": failure_type,
                "agent_name": agent_name,
            })
            mlflow.log_metrics({
                "before_score": before_score,
                "after_score": after_score,
                "score_delta": score_delta,
                "eval_duration_ms": eval_duration_ms,
                **{f"metric_{k}": v for k, v in per_metric.items()},
            })
            _log_artifacts(
                before_trace=before_trace,
                after_trace=after_trace,
                patch_content=patch_content,
            )
            run_id = run.info.run_id
            logger.info("healer: MLflow run logged run_id=%s delta=%.3f",
                        run_id, score_delta)
            return run_id
    except Exception as exc:
        logger.warning("healer: MLflow logging failed: %s", exc)
        return None


def _log_artifacts(before_trace, after_trace, patch_content):
    try:
        import mlflow
        with tempfile.TemporaryDirectory() as tmp:
            if before_trace:
                p = os.path.join(tmp, "before_trace.json")
                with open(p, "w") as f:
                    json.dump(before_trace, f, indent=2, default=str)
                mlflow.log_artifact(p)
            if after_trace:
                p = os.path.join(tmp, "after_trace.json")
                with open(p, "w") as f:
                    json.dump(after_trace, f, indent=2, default=str)
                mlflow.log_artifact(p)
            if patch_content:
                p = os.path.join(tmp, "patch_content.txt")
                with open(p, "w") as f:
                    f.write(patch_content)
                mlflow.log_artifact(p)
    except Exception as exc:
        logger.warning("healer: artifact logging failed: %s", exc)
