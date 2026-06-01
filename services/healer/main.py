"""Entry point for the nexus-healer service."""

from __future__ import annotations

import logging
import os

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("nexus.healer")


def main() -> None:
    import redis as redis_lib

    from services.healer.consumer import HealerConsumer

    autonomous = os.getenv("AUTONOMOUS_MODE", "false").lower() == "true"
    delay = float(os.getenv("AUTO_APPROVE_DELAY_SECONDS", "0"))
    slack_url = os.getenv("SLACK_WEBHOOK_URL", "")

    redis_client = None
    try:
        redis_client = redis_lib.Redis(
            host=os.getenv("REDIS_HOST", "redis"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            decode_responses=True,
        )
        redis_client.ping()
        logger.info("healer: Redis connected")
    except Exception as exc:
        logger.warning("healer: Redis unavailable (%s); HealthDiff disabled", exc)
        redis_client = None

    consumer = HealerConsumer(
        redis_client=redis_client,
        autonomous_mode=autonomous,
        auto_approve_delay_seconds=delay,
        slack_webhook_url=slack_url,
    )
    consumer.run()


if __name__ == "__main__":
    main()
