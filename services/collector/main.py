"""nexus-collector — FastAPI span ingestion service (port 8000)."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI

from services.collector.kafka_producer import KafkaSpanProducer
from services.collector.routes.spans import router

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.producer = KafkaSpanProducer()
    app.state.start_time = time.time()
    app.state.spans_received_total = 0
    yield
    try:
        app.state.producer.flush()
    except Exception:  # noqa: BLE001
        pass


app = FastAPI(title="nexus-collector", version="1.0.0", lifespan=lifespan)
app.include_router(router)


@app.get("/")
async def root() -> dict:
    return {"service": "nexus-collector", "version": "1.0.0"}
