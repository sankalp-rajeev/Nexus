"""nexus-collector — FastAPI span ingestion service (port 8000)."""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI

from services.collector.kafka_producer import KafkaSpanProducer
from services.collector.routes.otlp import router as otlp_router
from services.collector.routes.spans import router

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    mode = os.getenv("NEXUS_QUEUE", "kafka")
    if mode == "inprocess":
        from services.collector.lite import LiteSpanProducer

        app.state.producer = LiteSpanProducer(os.getenv("NEXUS_SQLITE_PATH", "nexus-lite.db"))
    elif mode == "kafka":
        app.state.producer = KafkaSpanProducer()
    else:
        raise ValueError(f"Unknown NEXUS_QUEUE: {mode}")
    app.state.start_time = time.time()
    app.state.spans_received_total = 0
    try:
        yield
    finally:
        app.state.producer.flush()
        if hasattr(app.state.producer, "close"):
            app.state.producer.close()


app = FastAPI(title="nexus-collector", version="1.0.0", lifespan=lifespan)
app.include_router(router)
app.include_router(otlp_router)


@app.get("/")
async def root() -> dict:
    return {"service": "nexus-collector", "version": "1.0.0"}
