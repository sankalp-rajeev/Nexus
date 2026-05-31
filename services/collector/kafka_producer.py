"""Thin wrapper over confluent-kafka Producer for the collector (Section 7.4)."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger("nexus.collector.kafka")

TOPIC_RAW_SPANS = os.getenv("COLLECTOR_KAFKA_TOPIC", "nexus.spans.raw")


def build_kafka_config() -> dict[str, Any]:
    return {
        "bootstrap.servers": os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
        "acks": "1",  # leader ack only — optimize for low latency
        "linger.ms": 5,  # micro-batch for efficiency
        "batch.size": 16384,  # 16KB batches
        "compression.type": "lz4",  # fast compression
        "message.max.bytes": 1048576,  # 1MB max span (large LLM outputs)
    }


class KafkaSpanProducer:
    """Publishes spans to ``nexus.spans.raw`` keyed by trace_id.

    Constructing a Producer does not block on a broker connection; failures
    surface lazily on produce()/flush() and are logged, not raised.
    """

    def __init__(self, topic: str = TOPIC_RAW_SPANS) -> None:
        self.topic = topic
        self._producer = None
        self._init_error: str | None = None
        try:
            from confluent_kafka import Producer

            self._producer = Producer(build_kafka_config())
        except Exception as exc:  # noqa: BLE001
            self._init_error = f"{exc.__class__.__name__}: {exc}"
            logger.error("nexus-collector: failed to create Kafka producer: %s", self._init_error)

    def is_connected(self, timeout: float = 1.0) -> bool:
        if self._producer is None:
            return False
        try:
            self._producer.list_topics(timeout=timeout)
            return True
        except Exception:  # noqa: BLE001
            return False

    def produce_span(self, trace_id: str, value: dict[str, Any]) -> None:
        if self._producer is None:
            raise RuntimeError(f"Kafka producer unavailable ({self._init_error})")
        self._producer.produce(
            self.topic,
            key=trace_id.encode("utf-8"),
            value=json.dumps(value).encode("utf-8"),
        )
        self._producer.poll(0)  # serve delivery callbacks without blocking

    def flush(self, timeout: float = 5.0) -> int:
        if self._producer is None:
            return 0
        return self._producer.flush(timeout)
