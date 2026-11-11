"""OTLP/HTTP trace receiver, JSON and binary protobuf, at /v1/traces."""

from __future__ import annotations

import base64
import gzip
import io
import json

from fastapi import APIRouter, HTTPException, Request, Response
from google.protobuf.json_format import MessageToJson, ParseDict, ParseError
from google.protobuf.message import DecodeError
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)

from nexus_agent.integrations.otel import span_batches
from services.collector.routes.spans import _publish

router = APIRouter()
MAX_BYTES = 4 * 1024 * 1024


def _json_ids(value):
    """OTLP JSON IDs are hex, unlike ordinary protobuf JSON bytes fields."""
    if isinstance(value, list):
        return [_json_ids(v) for v in value]
    if isinstance(value, dict):
        return {
            k: base64.b64encode(bytes.fromhex(v)).decode() if k in
            {"traceId", "spanId", "parentSpanId"} else _json_ids(v)
            for k, v in value.items()
        }
    return value


@router.post("/v1/traces")
async def ingest_otlp(request: Request) -> Response:
    media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if media_type not in {"application/json", "application/x-protobuf"}:
        raise HTTPException(415, "Use application/json or application/x-protobuf")
    encoding = request.headers.get("content-encoding", "identity").lower()
    if encoding not in {"identity", "gzip"}:
        raise HTTPException(415, "Only identity and gzip content encodings are supported")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BYTES:
            raise HTTPException(413, "OTLP request exceeds 4 MiB")
    try:
        if encoding == "gzip":
            with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream:
                body = stream.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise HTTPException(413, "Decompressed OTLP request exceeds 4 MiB")
        export = ExportTraceServiceRequest()
        if media_type == "application/json":
            document = json.loads(body)
            if not isinstance(document, dict):
                raise ValueError("OTLP JSON must be an object")
            ParseDict(_json_ids(document), export, ignore_unknown_fields=True)
        else:
            export.ParseFromString(bytes(body))
        batches = span_batches(export)
    except (ValueError, TypeError, ParseError, DecodeError, OSError, EOFError) as exc:
        raise HTTPException(400, f"Invalid OTLP trace request: {exc}") from exc
    accepted = rejected = 0
    for batch in batches:
        for span in batch.spans:
            if _publish(request, span):
                accepted += 1
            else:
                rejected += 1
    request.app.state.spans_received_total += accepted + rejected
    if rejected and not accepted:
        raise HTTPException(503, "Span queue unavailable; retry export")
    response = ExportTraceServiceResponse()
    if rejected:
        response.partial_success.rejected_spans = rejected
        response.partial_success.error_message = "Some spans could not be queued"
    content = MessageToJson(response) if media_type == "application/json" else response.SerializeToString()
    return Response(content=content, media_type=media_type)
