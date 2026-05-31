"""Kafka consumer: nexus.spans.raw -> assemble -> classify -> publish.

Publishes every classification to nexus.spans.classified and a non-NORMAL
Alert to nexus.alerts (keyed by agent_name).
"""

from __future__ import annotations

import json
import logging
import os

from nexus_agent.models import Alert, Span

from services.classifier.classifier import FailureClassifier
from services.common.trace_buffer import TraceBuffer

logger = logging.getLogger("nexus.classifier.consumer")

TOPIC_RAW = os.getenv("COLLECTOR_KAFKA_TOPIC", "nexus.spans.raw")
TOPIC_CLASSIFIED = "nexus.spans.classified"
TOPIC_ALERTS = "nexus.alerts"


def build_consumer():
    from confluent_kafka import Consumer

    return Consumer(
        {
            "bootstrap.servers": os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
            "group.id": "nexus-classifier",
            "auto.offset.reset": "earliest",
            "enable.auto.commit": True,
        }
    )


def build_producer():
    from confluent_kafka import Producer

    return Producer({"bootstrap.servers": os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")})


class ClassifierService:
    def __init__(self, classifier: FailureClassifier, buffer: TraceBuffer | None = None) -> None:
        self.classifier = classifier
        self.buffer = buffer or TraceBuffer()
        self._producer = None
        self._running = False

    def _emit(self, topic: str, key: str, value: dict) -> None:
        self._producer.produce(topic, key=key.encode(), value=json.dumps(value).encode())
        self._producer.poll(0)

    def process_trace(self, trace) -> Alert | None:
        """Classify one assembled trace; publish results. Returns the Alert if any."""
        classification = self.classifier.classify(trace)
        self._emit(
            TOPIC_CLASSIFIED, trace.trace_id, classification.model_dump(mode="json")
        )
        if classification.failure_type.value == "NORMAL":
            return None
        alert = Alert(
            trace_id=trace.trace_id,
            classification_id=classification.classification_id,
            agent_name=trace.agent_name,
            failure_type=classification.failure_type,
        )
        self._emit(TOPIC_ALERTS, trace.agent_name, alert.model_dump(mode="json"))
        logger.info("nexus-classifier: ALERT %s for trace %s", alert.failure_type.value, trace.trace_id)
        return alert

    def _handle(self, value: bytes) -> None:
        span = Span.model_validate_json(value)
        completed = self.buffer.add(span)
        if completed is not None:
            self.process_trace(completed)

    def run(self) -> None:
        consumer = build_consumer()
        consumer.subscribe([TOPIC_RAW])
        self._producer = build_producer()
        self._running = True
        logger.info("nexus-classifier: consuming %s", TOPIC_RAW)
        try:
            while self._running:
                msg = consumer.poll(1.0)
                if msg is None:
                    for trace in self.buffer.sweep():
                        self.process_trace(trace)
                    self._producer.flush(1)
                    continue
                if msg.error():
                    logger.warning("nexus-classifier: consume error %s", msg.error())
                    continue
                try:
                    self._handle(msg.value())
                except Exception as exc:  # noqa: BLE001
                    logger.exception("nexus-classifier: failed to handle span (%s)", exc)
        finally:
            consumer.close()
            if self._producer is not None:
                self._producer.flush(5)

    def stop(self) -> None:
        self._running = False
