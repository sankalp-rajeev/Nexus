"""Kafka consumer: nexus.spans.raw -> assemble -> Postgres."""

from __future__ import annotations

import json
import logging
import os

from nexus_agent.models import Span

from services.assembler.db import AssemblerDB
from services.common.trace_buffer import TraceBuffer

logger = logging.getLogger("nexus.assembler.consumer")

TOPIC_RAW = os.getenv("COLLECTOR_KAFKA_TOPIC", "nexus.spans.raw")


def build_consumer():
    from confluent_kafka import Consumer

    return Consumer(
        {
            "bootstrap.servers": os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
            "group.id": "nexus-assembler",
            "auto.offset.reset": "earliest",
            "enable.auto.commit": True,
        }
    )


class AssemblerService:
    def __init__(self, db: AssemblerDB | None = None, buffer: TraceBuffer | None = None) -> None:
        self.db = db or AssemblerDB()
        self.buffer = buffer or TraceBuffer()
        self._running = False

    def _handle(self, value: bytes) -> None:
        span = Span.model_validate_json(value)
        completed = self.buffer.add(span)
        if completed is not None:
            self.db.write_trace(completed)

    def run(self) -> None:
        consumer = build_consumer()
        consumer.subscribe([TOPIC_RAW])
        self.db.connect()
        self._running = True
        logger.info("nexus-assembler: consuming %s", TOPIC_RAW)
        try:
            while self._running:
                msg = consumer.poll(1.0)
                if msg is None:
                    for trace in self.buffer.sweep():
                        self.db.write_trace(trace)
                    continue
                if msg.error():
                    logger.warning("nexus-assembler: consume error %s", msg.error())
                    continue
                try:
                    self._handle(msg.value())
                except Exception as exc:  # noqa: BLE001
                    logger.exception("nexus-assembler: failed to handle span (%s)", exc)
        finally:
            consumer.close()
            self.db.close()

    def stop(self) -> None:
        self._running = False
