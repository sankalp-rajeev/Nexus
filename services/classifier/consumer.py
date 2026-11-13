"""Kafka consumer: nexus.spans.raw -> assemble -> classify -> publish.

Publishes every classification to nexus.spans.classified. Only non-synthetic,
non-NORMAL traces publish an Alert to nexus.alerts (keyed by agent_name).
"""

from __future__ import annotations

import json
import logging
import os

from nexus_agent.models import Alert, CompleteTrace, Span

from services.classifier.classifier import FailureClassifier
from services.classifier.embedder import NLIModelUnavailable, NLIScorer
from services.common.trace_buffer import TraceBuffer

logger = logging.getLogger("nexus.classifier.consumer")

TOPIC_RAW = os.getenv("COLLECTOR_KAFKA_TOPIC", "nexus.spans.raw")
TOPIC_CLASSIFIED = "nexus.spans.classified"
TOPIC_ALERTS = "nexus.alerts"


def is_synthetic(trace: CompleteTrace) -> bool:
    """Every future load tool must set boolean metadata['nexus.synthetic']."""
    legacy = "phase5-load-dev"
    return (trace.agent_name == legacy or trace.environment == legacy or any(
        span.metadata.get("nexus.synthetic") is True
        or span.agent_name == legacy or span.environment == legacy
        for span in trace.spans
    ))


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
        self._nli_ready = False
        self._error = "Required NLI model has not initialized"
        self.synthetic_suppressed = 0

    def require_nli(self) -> None:
        """Load the models the active classifier needs; refuse (never substitute) if one is missing."""
        # Looked up on the class so test doubles (MagicMock) keep the legacy NLI requirement.
        require_models = getattr(type(self.classifier), "require_models", None)
        try:
            if require_models is not None:
                require_models(self.classifier)
            else:
                NLIScorer.get()
        except NLIModelUnavailable as exc:
            self._nli_ready = False
            self.mark_unhealthy(str(exc))
            raise
        self._nli_ready = True
        self._error = None

    def mark_unhealthy(self, error: str) -> None:
        self._running = False
        self._error = error

    def health(self) -> dict:
        healthy = self._nli_ready and self._running
        state = {"status": "ok" if healthy else "unhealthy", "nli_ready": self._nli_ready,
                 "consumer_running": self._running, "error": self._error,
                 "synthetic_suppressed": self.synthetic_suppressed,
                 "duplicate_spans_dropped": self.buffer.duplicate_spans_dropped}
        status = getattr(type(self.classifier), "status", None)
        state["classifier"] = "legacy"
        if status is not None:
            state.update(status(self.classifier))
        return state

    def _emit(self, topic: str, key: str, value: dict) -> None:
        self._producer.produce(topic, key=key.encode(), value=json.dumps(value).encode())
        self._producer.poll(0)

    def process_trace(self, trace) -> Alert | None:
        """Classify one assembled trace; publish results. Returns the Alert if any."""
        self.require_nli()
        classification = self.classifier.classify(trace)
        self._emit(
            TOPIC_CLASSIFIED, trace.trace_id, classification.model_dump(mode="json")
        )
        if is_synthetic(trace):
            self.synthetic_suppressed += 1
            logger.info("nexus-classifier: synthetic_suppressed=%d trace_id=%s failure_type=%s",
                        self.synthetic_suppressed, trace.trace_id, classification.failure_type.value)
            return None
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
        # Validate before creating a consumer, subscribing or committing offsets.
        self.require_nli()
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
                except NLIModelUnavailable:
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.exception("nexus-classifier: failed to handle span (%s)", exc)
        finally:
            self._running = False
            consumer.close()
            if self._producer is not None:
                self._producer.flush(5)

    def stop(self) -> None:
        self._running = False
