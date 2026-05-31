"""Kafka consumer: nexus.alerts -> LangGraph critic -> nexus.patches."""

from __future__ import annotations

import logging
import os

from nexus_agent.models import Alert

logger = logging.getLogger("nexus.critic.consumer")

TOPIC_ALERTS = "nexus.alerts"


def build_kafka_consumer():
    from confluent_kafka import Consumer

    return Consumer({
        "bootstrap.servers": os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
        "group.id": "nexus-critic",
        "auto.offset.reset": "earliest",
        "enable.auto.commit": True,
    })


def build_kafka_producer():
    from confluent_kafka import Producer

    return Producer({
        "bootstrap.servers": os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
    })


class CriticConsumer:
    def __init__(self, db, llm_factory=None) -> None:
        self.db = db
        self.llm_factory = llm_factory
        self._running = False

    def run(self) -> None:
        from services.critic.graph import run_critic

        consumer = build_kafka_consumer()
        producer = build_kafka_producer()
        consumer.subscribe([TOPIC_ALERTS])
        self._running = True
        logger.info("nexus-critic: consuming %s", TOPIC_ALERTS)
        try:
            while self._running:
                msg = consumer.poll(1.0)
                if msg is None:
                    continue
                if msg.error():
                    logger.warning("nexus-critic: consume error %s", msg.error())
                    continue
                try:
                    alert = Alert.model_validate_json(msg.value())
                    logger.info("nexus-critic: processing alert %s (type=%s)",
                                alert.alert_id, alert.failure_type.value)
                    proposal = run_critic(
                        alert, self.db,
                        llm_factory=self.llm_factory,
                        kafka_producer=producer,
                    )
                    if proposal:
                        producer.flush(1)
                        logger.info("nexus-critic: published patch %s", proposal.proposal_id)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("nexus-critic: failed to process alert (%s)", exc)
        finally:
            consumer.close()
            producer.flush(5)

    def stop(self) -> None:
        self._running = False
