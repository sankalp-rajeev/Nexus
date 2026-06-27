"""Redis pub/sub publisher for HealthDiff events.

Publishes to channel: nexus:health:{agent_name}
Dashboard WebSocket consumers subscribe to this channel for real-time updates.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger("nexus.healer.health_emitter")


def emit_health_diff(
    redis_client,
    agent_name: str,
    patch_id: str,
    failure_type: str,
    before_score: float,
    after_score: float,
    score_delta: float,
    mlflow_run_id: str | None = None,
) -> None:
    """Publish a HealthDiff event to the agent's Redis health channel."""
    channel = f"nexus:health:{agent_name}"
    payload = {
        "event": "health_diff",
        "agent_name": agent_name,
        "patch_id": patch_id,
        "failure_type": failure_type,
        "before_score": round(before_score, 4),
        "after_score": round(after_score, 4),
        "score_delta": round(score_delta, 4),
        "improved": score_delta > 0,
        "mlflow_run_id": mlflow_run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        redis_client.publish(channel, json.dumps(payload))
        logger.info(
            "healer: health_diff emitted to %s (delta=%.3f)",
            channel, score_delta,
        )
    except Exception as exc:
        logger.warning("healer: health_diff emit failed: %s", exc)
