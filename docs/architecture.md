# Nexus — Architecture

Nexus is a self-hosted LLMOps platform that closes the loop from production
observation to automated remediation for multi-agent AI systems.

## The Loop

```
OBSERVE (SDK) → STREAM (Kafka) → DETECT (Classifier) → DIAGNOSE (Critic) → PATCH (Healer) → EVALUATE (Eval Loop) → OBSERVE
```

## High-Level Data Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                        USER'S AGENT APPLICATION                      │
│                                                                      │
│   @nexus.trace(agent="planner")                                      │
│   def run_planner(task: str) -> str: ...                             │
│                                                                      │
│   NexusClient.tool_call(name, args, result, duration, error)         │
└───────────────────────────┬──────────────────────────────────────────┘
                            │ HTTP POST  (async, non-blocking)
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     NEXUS COLLECTOR SERVICE (FastAPI)                │
│   - Validates span schema                                            │
│   - Assigns trace_id, span_id, timestamps                            │
│   - Publishes to Kafka topic: nexus.spans.raw                        │
└───────────────────────────┬──────────────────────────────────────────┘
                            │ Kafka publish
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     KAFKA BROKER                                     │
│   Topics: nexus.spans.raw | nexus.spans.classified | nexus.alerts   │
└────────────┬────────────────────────────┬────────────────────────────┘
             │                            │
             ▼                            ▼
┌────────────────────────┐    ┌───────────────────────────────────────┐
│  TRACE ASSEMBLER       │    │  FAILURE CLASSIFIER                   │
│  - Groups spans by     │    │  - Consumes nexus.spans.raw           │
│    trace_id            │    │  - Embeds spans via sentence-xfmr     │
│  - Detects trace       │    │  - PatchCore memory bank lookup       │
│    completion          │    │  - Classifies: HALLUCINATION /        │
│  - Writes complete     │    │    TOOL_MISFIRE / CONTEXT_BLEED /     │
│    trace to Postgres   │    │    PLAN_DRIFT / LOOP_DETECTED /       │
└────────────┬───────────┘    │    NORMAL                             │
             │                │  - Publishes to nexus.spans.classified│
             │                └────────────────┬──────────────────────┘
             │                                 │
             ▼                                 ▼
┌────────────────────────────────────────────────────────────────────┐
│                       POSTGRES (timescaledb)                        │
│   Tables: traces | spans | classifications | patches | eval_runs    │
└───────────────────────┬────────────────────────────────────────────┘
                        │
        ┌───────────────┼────────────────────┐
        │                                    │
        ▼                                    ▼
┌───────────────────┐              ┌──────────────────────────────────┐
│  LLM CRITIC AGENT │              │  DASHBOARD (React 18 + FastAPI)  │
│  - Receives alert │              │  - Live trace stream             │
│  - Reads full     │              │  - Failure timeline              │
│    trace context  │              │  - Critic explanations           │
│  - Diagnoses root │              │  - Patch history + score deltas  │
│    cause via CoT  │              │  - Health score per agent        │
│  - Proposes patch │              └──────────────────────────────────┘
└───────────┬───────┘
            │
            ▼
┌────────────────────────────────────────────────────────────────────┐
│                    AUTO-HEALER                                      │
│  - Renders proposed patch for human review (Slack webhook / UI)    │
│  - On approval (or autonomous mode): applies patch to config store  │
│  - Re-runs eval suite via DeepEval harness                         │
│  - Logs before/after scores to MLflow                              │
│  - Emits health_diff event → Dashboard                             │
└────────────────────────────────────────────────────────────────────┘
```

## Service Inventory

| Service | Language | Port | Responsibility |
|---|---|---|---|
| `nexus-collector` | Python / FastAPI | 8000 | Span ingestion, schema validation, Kafka publish |
| `nexus-assembler` | Python | — | Kafka consumer, trace assembly, Postgres writes |
| `nexus-classifier` | Python | — | Kafka consumer, embedding, anomaly detection, classification |
| `nexus-critic` | Python / LangGraph | — | Alert consumer, LLM root cause agent, patch proposal |
| `nexus-healer` | Python | — | Patch application, eval re-run, MLflow logging |
| `nexus-api` | Python / FastAPI | 8001 | Dashboard data API (REST + WebSocket for live stream) |
| `nexus-dashboard` | TypeScript / React 18 | 3000 | Frontend UI |
| `kafka` | bitnami | 9092 | Event stream |
| `postgres` | TimescaleDB | 5432 | Persistent trace/eval storage |
| `redis` | Redis 7 | 6379 | State cache, dedup buffer |
| `mlflow` | MLflow 2.x | 5000 | Eval run tracking |

## Kafka Topics

| Topic | Partition Key | Value | Retention | Partitions |
|---|---|---|---|---|
| `nexus.spans.raw` | `trace_id` | `Span` JSON | 7 days | 3 |
| `nexus.spans.classified` | `trace_id` | `ClassifiedSpan` JSON | 7 days | 3 |
| `nexus.alerts` | `agent_name` | `Alert` JSON | 30 days | 1 |
