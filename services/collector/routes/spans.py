"""Span ingestion routes (Section 7.4 / 14.1)."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from nexus_agent.models import Span, SpanBatch

logger = logging.getLogger("nexus.collector.routes")

router = APIRouter()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _publish(request: Request, span: Span) -> bool:
    """Stamp server_timestamp and publish to Kafka. Returns True if accepted."""
    span.server_timestamp = _now()
    producer = request.app.state.producer
    try:
        producer.produce_span(span.trace_id, span.model_dump(mode="json"))
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("nexus-collector: publish failed for %s (%s)", span.span_id, exc)
        return False


@router.post("/v1/spans", status_code=202)
async def ingest_spans(batch: SpanBatch, request: Request) -> JSONResponse:
    accepted = 0
    rejected = 0
    trace_ids: list[str] = []
    for span in batch.spans:
        if _publish(request, span):
            accepted += 1
            if span.trace_id not in trace_ids:
                trace_ids.append(span.trace_id)
        else:
            rejected += 1
    request.app.state.spans_received_total += len(batch.spans)
    return JSONResponse(
        status_code=202,
        content={
            "accepted": accepted,
            "rejected": rejected,
            "batch_id": batch.batch_id,
            "trace_ids": trace_ids,
        },
    )


@router.post("/v1/spans/single")
async def ingest_single(span: Span, request: Request) -> dict:
    _publish(request, span)
    request.app.state.spans_received_total += 1
    return {"span_id": span.span_id, "trace_id": span.trace_id}


@router.get("/health")
async def health(request: Request) -> dict:
    producer = request.app.state.producer
    connected = producer.is_connected()
    return {
        "status": "ok" if connected else "degraded",
        "kafka_connected": connected,
        "spans_received_total": request.app.state.spans_received_total,
        "uptime_seconds": round(time.time() - request.app.state.start_time, 2),
    }
