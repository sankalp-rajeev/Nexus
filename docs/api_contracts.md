# Nexus — API Contracts

Source: NEXUS_PRD.md Section 14.

## Collector Service (port 8000)

```
POST /v1/spans
  Request:
    Content-Type: application/json
    Body: SpanBatch
  Response 202 Accepted:
    {"accepted": int, "rejected": int, "batch_id": str, "trace_ids": [str]}
  Response 422 Unprocessable Entity:
    {"detail": [{"loc": [...], "msg": str, "type": str}]}
  Action: validate each span, assign server-side timestamps, publish to
          Kafka topic nexus.spans.raw

POST /v1/spans/single
  Request:  Span
  Response: {"span_id": str, "trace_id": str}

GET /health
  Response: {"status": "ok|degraded", "kafka_connected": bool,
             "spans_received_total": int, "uptime_seconds": float}
```

### Kafka Producer Config

```python
KAFKA_CONFIG = {
    "bootstrap.servers": "kafka:9092",
    "acks": "1",                    # leader ack only — low latency
    "linger.ms": 5,                 # micro-batch
    "batch.size": 16384,            # 16KB batches
    "compression.type": "lz4",
    "message.max.bytes": 1048576,   # 1MB max span
}
TOPIC_RAW_SPANS = "nexus.spans.raw"
```

## API Service (port 8001)

```
GET /v1/traces
  Query: agent_name?, limit=50, offset=0, status?
  Response: {"traces": [Trace], "total": int}

GET /v1/traces/{trace_id}
  Response: {"trace": Trace, "spans": [Span],
             "classification": Classification | null, "alert": Alert | null}

GET /v1/alerts
  Query: agent_name?, status=OPEN, limit=20
  Response: {"alerts": [Alert], "total": int}

GET /v1/patches
  Query: agent_name?, status?, limit=20
  Response: {"patches": [PatchProposal], "total": int}

POST /v1/patches/{proposal_id}/approve
  Response: {"proposal_id": str, "status": "APPROVED", "healer_triggered": bool}

POST /v1/patches/{proposal_id}/reject
  Body: {"reason": str}
  Response: {"proposal_id": str, "status": "REJECTED"}

GET /v1/agents/{agent_name}/health
  Response: {"agent_name": str, "health_score": float,
             "last_failure_type": str | null, "last_failure_at": datetime | null,
             "open_alerts": int}

GET /v1/eval-runs
  Query: agent_name?, limit=20
  Response: {"eval_runs": [EvalRun], "total": int}

WebSocket: ws://localhost:8001/ws/traces
```

### WebSocket Protocol

```ts
// Client connects to: ws://localhost:8001/ws/traces
type NexusWSMessage =
  | { type: "span"; data: Span }
  | { type: "alert"; data: Alert }
  | { type: "patch_proposal"; data: PatchProposal }
  | { type: "health_diff"; data: HealthDiff }
  | { type: "ping" }  // every 30s keepalive
```
