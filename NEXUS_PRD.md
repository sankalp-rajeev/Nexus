# NEXUS — Product Requirements Document
## Production AI Health Monitor for Agentic Systems

```
Document Version : 1.0.0
Status           : APPROVED FOR DEVELOPMENT
Author           : Sankalp Rajeev
SDLC Model       : Waterfall (sequential, phase-gated)
Total Duration   : 11 weeks (weekend-only, ~12–16 hrs/week)
Target Release   : October 2026
Repo             : github.com/sankalp-rajeev/nexus
PyPI Package     : nexus-agent
```

---

## TABLE OF CONTENTS

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [Goals & Success Metrics](#3-goals--success-metrics)
4. [System Architecture Overview](#4-system-architecture-overview)
5. [Technology Stack](#5-technology-stack)
6. [Phase 1 — Requirements & Design](#6-phase-1--requirements--design)
7. [Phase 2 — Trace Collector SDK](#7-phase-2--trace-collector-sdk)
8. [Phase 3 — Failure Classifier](#8-phase-3--failure-classifier)
9. [Phase 4 — LLM Critic Agent](#9-phase-4--llm-critic-agent)
10. [Phase 5 — Auto-Healer & Eval Loop](#10-phase-5--auto-healer--eval-loop)
11. [Phase 6 — Dashboard & OSS Release](#11-phase-6--dashboard--oss-release)
12. [Phase 7 — Testing & QA](#12-phase-7--testing--qa)
13. [Data Models & Schemas](#13-data-models--schemas)
14. [API Contracts](#14-api-contracts)
15. [Non-Functional Requirements](#15-non-functional-requirements)
16. [Constraints & Assumptions](#16-constraints--assumptions)
17. [Risk Register](#17-risk-register)
18. [Glossary](#18-glossary)

---

## 1. EXECUTIVE SUMMARY

### 1.1 What Is Nexus

Nexus is an open-source LLMOps platform that provides end-to-end observability and autonomous self-healing for multi-agent AI pipelines. It instruments any LangChain, CrewAI, LangGraph, or raw LLM application via a zero-config Python SDK, streams structured trace spans to a real-time processing pipeline, classifies failure modes using anomaly detection on trace embeddings, diagnoses root causes via an LLM Critic agent, and proposes or applies prompt/config patches — then re-evaluates the fixed pipeline and records the improvement delta.

### 1.2 The Loop Nexus Closes

```
OBSERVE (SDK) → STREAM (Kafka) → DETECT (Classifier) → DIAGNOSE (Critic) → PATCH (Healer) → EVALUATE (Eval Loop) → OBSERVE
```

No existing tool in 2026 closes this loop. LangSmith and Langfuse stop at tracing. DeepEval stops at offline evaluation. Nexus is the first system that connects production observation directly to automated remediation.

### 1.3 Target Users

| User | Pain Point Nexus Solves |
|---|---|
| ML Engineers shipping agents | Silent failures in production go undetected for hours |
| AI Platform Teams | No automated way to diagnose why an agent degraded after a model update |
| Indie developers / OSS builders | No lightweight self-hosted alternative to expensive SaaS observability |
| Recruiters / interviewers | (meta) A candidate who built a tool other engineers actually use |

---

## 2. PROBLEM STATEMENT

### 2.1 Background

Multi-agent AI systems fail in four ways that traditional APM cannot detect:

1. **Hallucination cascade** — an LLM produces a plausible but incorrect output; a downstream agent consumes it as fact; the error compounds silently across tool calls.
2. **Tool misfire** — an agent selects the correct tool but passes incorrect arguments; the tool returns an error or a wrong result; the agent retries with the same broken arguments.
3. **Context bleed** — a memory read operation returns stale or cross-user context; the agent's reasoning is corrupted from the input stage.
4. **Plan drift** — a planner agent decomposes a task; partway through execution, the sub-agents deviate from the original plan without detecting the inconsistency.

None of these failures crash the system. They produce valid-looking outputs with degraded quality — the worst class of production bug.

### 2.2 Existing Solutions and Their Gaps

| Tool | What It Does | What It Misses |
|---|---|---|
| LangSmith | Traces LangChain calls, logs inputs/outputs | No failure classification, no auto-diagnosis |
| Langfuse | Open-source trace logging, cost tracking | Evaluation is offline / manual trigger |
| MLflow Tracing | Tracks LLM runs inside MLflow ecosystem | No real-time stream processing |
| Datadog LLM Observability | Infra-level metrics + token counting | No semantic quality evaluation |
| DeepEval / RAGAS | Offline eval harness with LLM judges | Not a production monitoring tool |

**The gap:** No tool automatically classifies a failure from a live production trace, reasons about its root cause, and proposes a concrete fix — all without a human in the diagnostic loop.

### 2.3 Nexus's Position

Nexus sits in the gap between tracing (what happened) and remediation (why it broke and how to fix it). It is designed to be:

- Framework-agnostic via a thin SDK decorator
- Self-hosted with a one-command Docker Compose
- Open-source with a PyPI distribution
- Extensible — users can plug in their own failure classifiers and critic prompts

---

## 3. GOALS & SUCCESS METRICS

### 3.1 Project Goals

```
G1  Ship a working end-to-end system across all 5 modules by Week 11.
G2  Demonstrate the full loop on 3 real agent systems (CodeMind, MeetingMind, a synthetic test agent).
G3  Publish to PyPI and achieve pip install nexus-agent in < 5 seconds.
G4  Reach 100+ GitHub stars within 30 days of OSS launch.
G5  Produce a resume bullet with ≥ 3 quantified metrics (MTTR, precision, star count).
```

### 3.2 Quantitative Success Metrics

| Metric | Target | Measurement Method |
|---|---|---|
| Failure detection precision | ≥ 0.85 | Labeled test set of 200 synthetic + real failure traces |
| Failure detection recall | ≥ 0.80 | Same labeled test set |
| Mean time to agent recovery (MTTR) | < 90 seconds | Timed end-to-end from failure event to patched eval score |
| Trace ingestion latency (p95) | < 500 ms | Kafka consumer lag metrics |
| SDK instrumentation overhead | < 5 ms per span | Benchmarked with `timeit` against uninstrumented baseline |
| Eval score improvement post-patch | ≥ 0.30 delta avg | MLflow logged before/after scores across test failures |
| PyPI monthly downloads | ≥ 200 in first month | PyPI stats API |
| GitHub stars | ≥ 100 within 30 days of launch | GitHub API |

### 3.3 Non-Goals (Explicit Out of Scope)

```
- NOT a model training or fine-tuning platform
- NOT a prompt management SaaS
- NOT a full APM replacement (no CPU/memory profiling)
- NOT multi-cloud managed service
- NOT a security / PII redaction layer (v2 consideration)
- NOT compatible with non-Python agent frameworks in v1 (TypeScript SDK is v2)
```

---

## 4. SYSTEM ARCHITECTURE OVERVIEW

### 4.1 High-Level Data Flow

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

### 4.2 Service Inventory

| Service | Language | Port | Responsibility |
|---|---|---|---|
| `nexus-collector` | Python / FastAPI | 8000 | Span ingestion, schema validation, Kafka publish |
| `nexus-assembler` | Python | — | Kafka consumer, trace assembly, Postgres writes |
| `nexus-classifier` | Python | — | Kafka consumer, embedding, anomaly detection, classification |
| `nexus-critic` | Python / LangGraph | — | Alert consumer, LLM root cause agent, patch proposal |
| `nexus-healer` | Python | — | Patch application, eval re-run, MLflow logging |
| `nexus-api` | Python / FastAPI | 8001 | Dashboard data API (REST + WebSocket for live stream) |
| `nexus-dashboard` | TypeScript / React 18 | 3000 | Frontend UI |
| `kafka` | Confluent/bitnami | 9092 | Event stream |
| `postgres` | TimescaleDB | 5432 | Persistent trace/eval storage |
| `redis` | Redis 7 | 6379 | State cache, dedup buffer |
| `mlflow` | MLflow 2.x | 5000 | Eval run tracking |

---

## 5. TECHNOLOGY STACK

### 5.1 Full Stack

```yaml
language:
  primary: Python 3.11
  frontend: TypeScript 5.x

sdk_and_instrumentation:
  - nexus-agent (PyPI package, this project)
  - opentelemetry-sdk (span ID generation conformance)

stream_processing:
  broker: Apache Kafka 3.6 (bitnami docker image)
  consumer_library: confluent-kafka-python 2.3

ml_and_embeddings:
  embedding_model: sentence-transformers/all-MiniLM-L6-v2  # 22MB, fast, good quality
  anomaly_detection: PatchCore (custom implementation on embedding memory bank)
  alternative_classifier: scikit-learn IsolationForest (fallback if PatchCore memory is cold)
  framework: PyTorch 2.2 (CPU-only in dev, GPU optional)

llm_integration:
  critic_model: gemini-2.0-flash (primary, cheap reasoning)
  fallback_model: gpt-4o-mini
  framework: LangGraph 0.2.x
  eval_framework: DeepEval 1.x (LLM-as-judge scoring)

storage:
  primary_db: PostgreSQL 15 + TimescaleDB extension
  cache: Redis 7
  eval_tracking: MLflow 2.13

backend_api:
  framework: FastAPI 0.111
  async: asyncio + httpx
  websocket: fastapi WebSocket (live trace stream)

frontend:
  framework: React 18 + TypeScript
  build: Vite 5
  charts: Recharts
  styling: Tailwind CSS 3.4
  websocket: native browser WebSocket API

devops:
  containerization: Docker + Docker Compose v3.9
  ci_cd: GitHub Actions
  packaging: PyPI (Hatchling build backend)
  linting: Ruff
  testing: Pytest + pytest-asyncio
  type_checking: mypy
```

### 5.2 External Service Dependencies

| Service | Purpose | Free Tier Sufficient? |
|---|---|---|
| Google AI Studio / Gemini API | Critic LLM inference | Yes (1M tokens/day free) |
| OpenAI API | Fallback critic | Yes (pay-as-you-go, < $2 total dev cost) |
| PyPI | Package distribution | Yes |
| HuggingFace Hub | sentence-transformers download | Yes |
| MLflow (self-hosted) | Eval tracking | Yes |

---

## 6. PHASE 1 — REQUIREMENTS & DESIGN

```
Duration : Week 1 (Weekend 1, ~12 hours)
Gate     : Architecture diagram finalized, all schemas locked, repo scaffolded
Deliverables:
  - /docs/architecture.md  (ASCII diagram + service descriptions)
  - /docs/schemas.md       (all Pydantic models)
  - /docs/api_contracts.md (all FastAPI route specs)
  - Repo scaffolded with all service directories
  - Docker Compose skeleton (services declared, images TBD)
  - GitHub repo public with README stub
```

### 6.1 Repo Structure (Scaffold This Exactly)

```
nexus/
├── sdk/                        # PyPI package (nexus-agent)
│   ├── nexus_agent/
│   │   ├── __init__.py
│   │   ├── client.py           # NexusClient class
│   │   ├── decorators.py       # @nexus.trace, @nexus.tool
│   │   ├── models.py           # Span, Trace Pydantic models
│   │   ├── config.py           # NexusConfig dataclass
│   │   └── exporters/
│   │       ├── http.py         # HTTP exporter to collector
│   │       └── stdout.py       # Debug exporter
│   ├── tests/
│   ├── pyproject.toml
│   └── README.md
│
├── services/
│   ├── collector/              # nexus-collector FastAPI service
│   │   ├── main.py
│   │   ├── routes/
│   │   │   └── spans.py
│   │   ├── kafka_producer.py
│   │   └── Dockerfile
│   │
│   ├── assembler/              # nexus-assembler Kafka consumer
│   │   ├── main.py
│   │   ├── consumer.py
│   │   ├── assembler.py
│   │   └── Dockerfile
│   │
│   ├── classifier/             # nexus-classifier
│   │   ├── main.py
│   │   ├── consumer.py
│   │   ├── embedder.py
│   │   ├── patchcore.py
│   │   ├── classifier.py
│   │   └── Dockerfile
│   │
│   ├── critic/                 # nexus-critic LangGraph agent
│   │   ├── main.py
│   │   ├── graph.py            # LangGraph state machine
│   │   ├── nodes/
│   │   │   ├── context_loader.py
│   │   │   ├── root_cause.py
│   │   │   ├── patch_proposer.py
│   │   │   └── validator.py
│   │   ├── prompts/
│   │   │   ├── root_cause.txt
│   │   │   └── patch_proposer.txt
│   │   └── Dockerfile
│   │
│   ├── healer/                 # nexus-healer
│   │   ├── main.py
│   │   ├── patch_applier.py
│   │   ├── eval_runner.py
│   │   ├── mlflow_logger.py
│   │   └── Dockerfile
│   │
│   └── api/                    # nexus-api (dashboard backend)
│       ├── main.py
│       ├── routes/
│       │   ├── traces.py
│       │   ├── alerts.py
│       │   ├── patches.py
│       │   └── ws.py           # WebSocket live stream
│       └── Dockerfile
│
├── dashboard/                  # React frontend
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── TraceStream.tsx
│   │   │   ├── FailureTimeline.tsx
│   │   │   ├── CriticPanel.tsx
│   │   │   ├── PatchHistory.tsx
│   │   │   └── HealthScore.tsx
│   │   ├── hooks/
│   │   │   └── useNexusWebSocket.ts
│   │   └── types/
│   │       └── nexus.ts
│   ├── package.json
│   └── vite.config.ts
│
├── infra/
│   ├── docker-compose.yml
│   ├── docker-compose.dev.yml
│   └── init/
│       └── postgres_init.sql
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
│       └── test_full_loop.py   # The demo test
│
├── docs/
│   ├── architecture.md
│   ├── schemas.md
│   └── api_contracts.md
│
├── examples/
│   ├── crewai_agent/           # Example instrumented CrewAI agent
│   ├── langchain_agent/        # Example instrumented LangChain agent
│   └── raw_llm_call/           # Example raw instrumented LLM call
│
├── .github/
│   └── workflows/
│       ├── ci.yml
│       └── publish.yml
│
├── pyproject.toml              # Root workspace (if using uv workspaces)
├── docker-compose.yml
└── README.md
```

### 6.2 Phase 1 Exit Criteria

All of the following must be true before proceeding to Phase 2:

- [ ] GitHub repo is public with a stub README and MIT LICENSE
- [ ] All Pydantic schemas in Section 13 are written and committed to `/sdk/nexus_agent/models.py`
- [ ] `docker-compose.yml` declares all 11 services (images can be `TODO`)
- [ ] `postgres_init.sql` contains all CREATE TABLE statements from Section 13
- [ ] Architecture ASCII diagram committed to `/docs/architecture.md`
- [ ] API contracts from Section 14 committed to `/docs/api_contracts.md`

---

## 7. PHASE 2 — TRACE COLLECTOR SDK

```
Duration     : Weeks 2–3 (Weekends 2–3, ~24 hours)
Gate         : SDK installable via pip, collector service running, spans flowing into Kafka
Deliverables :
  - nexus-agent Python package (local install)
  - nexus-collector FastAPI service in Docker
  - Kafka broker running in Docker
  - Integration test: instrumented script emits spans → Kafka topic confirmed
```

### 7.1 SDK Design Principles

The SDK must be:

1. **Zero-config by default** — `import nexus_agent as nexus; nexus.init()` is all that's needed to start emitting spans.
2. **Non-blocking** — all span emission is async or runs in a background thread. The user's agent must never wait on Nexus.
3. **Fail-silent** — if the collector is unreachable, the SDK logs a warning and drops the span. It never raises an exception that could crash the user's agent.
4. **Framework-agnostic** — works as a decorator, a context manager, or explicit method calls.

### 7.2 SDK Public API

```python
# ── Initialization ──────────────────────────────────────────────────
import nexus_agent as nexus

nexus.init(
    collector_url="http://localhost:8000",   # default
    agent_name="my-pipeline",               # required: identifies this agent system
    environment="production",               # default: "development"
    async_export=True,                      # default: True
    export_timeout_ms=200,                  # default: 200ms, fail-silent after
    debug=False                             # if True: print spans to stdout instead
)

# ── Decorator (primary instrumentation method) ───────────────────────
@nexus.trace(span_type="llm_call", model="gemini-2.0-flash")
def call_llm(prompt: str) -> str:
    # SDK automatically captures: input, output, duration, exception if raised
    ...

@nexus.trace(span_type="tool_call", tool_name="web_search")
def search_web(query: str) -> dict:
    ...

@nexus.trace(span_type="agent_step", agent_name="planner")
def planner_step(task: str) -> str:
    ...

# ── Context Manager ──────────────────────────────────────────────────
with nexus.span(span_type="memory_read", key="user_context") as span:
    result = memory.get(key)
    span.set_output(result)
    span.set_metadata({"cache_hit": True})

# ── Manual / Explicit API ────────────────────────────────────────────
span_id = nexus.start_span(span_type="agent_handoff", from_agent="planner", to_agent="executor")
# ... do work ...
nexus.end_span(span_id, output=result, metadata={"tokens_used": 312})

# ── Force flush (call before process exit in scripts) ────────────────
nexus.flush()
```

### 7.3 Span Lifecycle

```
USER CODE CALLS @nexus.trace DECORATED FUNCTION
         │
         ▼
nexus_agent creates SpanContext {trace_id, span_id, parent_span_id}
         │
         ▼
Function executes (nexus is NOT in the call path — no overhead on execution)
         │
         ▼
On function return OR exception:
  - SDK captures: output (first 2000 chars), duration_ms, exception_type, exception_message
  - SDK builds Span object (see Section 13.1)
  - SDK enqueues Span to background queue (thread-safe)
         │
         ▼
Background exporter thread (runs every 100ms OR when queue hits 50 spans):
  - Batches spans into SpanBatch
  - POST /v1/spans to nexus-collector (timeout: 200ms)
  - On timeout or error: log warning, drop batch, continue
```

### 7.4 Collector Service Specification

**Service:** `nexus-collector`
**Port:** 8000
**Framework:** FastAPI with `asyncio`

#### Routes

```
POST /v1/spans
  Body    : SpanBatch (see Section 13)
  Response: {"accepted": int, "rejected": int, "trace_ids": [str]}
  Action  : Validate each span, assign server-side timestamps, publish to Kafka topic nexus.spans.raw

POST /v1/spans/single
  Body    : Span
  Response: {"span_id": str, "trace_id": str}
  Action  : Same as above but single span

GET /health
  Response: {"status": "ok", "kafka_connected": bool, "spans_received_total": int}
```

#### Kafka Producer Configuration

```python
KAFKA_CONFIG = {
    "bootstrap.servers": "kafka:9092",
    "acks": "1",                    # leader ack only — optimize for low latency
    "linger.ms": 5,                 # micro-batch for efficiency
    "batch.size": 16384,            # 16KB batches
    "compression.type": "lz4",     # fast compression
    "message.max.bytes": 1048576,   # 1MB max span (handles large LLM outputs)
}
TOPIC_RAW_SPANS = "nexus.spans.raw"
```

### 7.5 Kafka Topic Schema

```
Topic: nexus.spans.raw
  Partition key : trace_id  (ensures all spans of one trace go to same partition)
  Value         : JSON-serialized Span (see Section 13.1)
  Retention     : 7 days
  Partitions    : 3 (sufficient for dev/OSS scale)

Topic: nexus.spans.classified
  Partition key : trace_id
  Value         : JSON-serialized ClassifiedSpan
  Retention     : 7 days
  Partitions    : 3

Topic: nexus.alerts
  Partition key : agent_name
  Value         : JSON-serialized Alert
  Retention     : 30 days
  Partitions    : 1
```

### 7.6 Phase 2 Exit Criteria

- [ ] `pip install -e ./sdk` installs `nexus_agent` cleanly with no errors
- [ ] `nexus.init()` + `@nexus.trace` decorator emits spans without blocking the decorated function (benchmark: < 5ms overhead measured with `timeit`)
- [ ] `nexus-collector` starts via Docker Compose and returns `{"status": "ok"}` on GET /health
- [ ] A test script in `examples/raw_llm_call/` emits 10 spans; they appear in Kafka topic `nexus.spans.raw` (verified via `kafka-console-consumer`)
- [ ] SDK handles collector unreachable without raising an exception (fail-silent test)
- [ ] `pytest tests/unit/sdk/` passes (min 10 unit tests covering: span creation, decorator wrapping, fail-silent behavior, flush)

---

## 8. PHASE 3 — FAILURE CLASSIFIER

```
Duration     : Weeks 4–6 (Weekends 4–6, ~36 hours)
Gate         : Classifier correctly labels ≥ 85% of synthetic failure traces; alerts flowing to nexus.alerts topic
Deliverables :
  - nexus-classifier service (Kafka consumer + inference pipeline)
  - nexus-assembler service (trace assembly + Postgres writes)
  - Labeled synthetic dataset of 200 traces (100 normal, 100 failures across 5 classes)
  - Classifier precision/recall report
```

### 8.1 Failure Taxonomy (Canonical Labels)

```python
class FailureType(str, Enum):
    HALLUCINATION     = "HALLUCINATION"      # LLM output contradicts retrieved context or known facts
    TOOL_MISFIRE      = "TOOL_MISFIRE"       # Tool called with bad args, returned error, retried identically
    CONTEXT_BLEED     = "CONTEXT_BLEED"      # Memory read returned data inconsistent with current task context
    PLAN_DRIFT        = "PLAN_DRIFT"         # Agent execution deviated from planner's stated subtask list
    LOOP_DETECTED     = "LOOP_DETECTED"      # Same tool+args combination called ≥ 3 times in one trace
    NORMAL            = "NORMAL"             # No anomaly detected
```

### 8.2 Classifier Architecture

The classifier uses a two-stage pipeline:

**Stage 1 — Rule-Based Pre-filter (fast, zero ML cost)**

Apply these rules first. If any fires, skip embedding entirely and classify immediately.

```python
RULE_BASED_CLASSIFIERS = [
    {
        "name": "loop_detector",
        "type": FailureType.LOOP_DETECTED,
        "logic": """
            Group spans by (tool_name, input_hash) within a trace.
            If any group has count >= 3, fire LOOP_DETECTED.
            input_hash = sha256(json.dumps(span.input, sort_keys=True))[:16]
        """
    },
    {
        "name": "tool_error_retry",
        "type": FailureType.TOOL_MISFIRE,
        "logic": """
            If a span with span_type=tool_call has error_type IS NOT NULL,
            AND within the next 3 spans in the same trace there exists another
            span with the same tool_name AND identical input_hash,
            fire TOOL_MISFIRE.
        """
    }
]
```

**Stage 2 — Embedding + PatchCore (semantic anomaly detection)**

For traces that pass Rule-Based pre-filter without firing:

```
1. SPAN FEATURE EXTRACTION
   For each span in the trace, extract a feature string:
   
   feature = f"""
   type: {span.span_type}
   model: {span.metadata.get('model', 'none')}
   input_summary: {span.input[:200]}
   output_summary: {span.output[:200]}
   duration_ms: {span.duration_ms}
   has_error: {span.error_type is not None}
   token_count: {span.metadata.get('tokens_used', 0)}
   """

2. TRACE-LEVEL EMBEDDING
   - Embed each span feature string using sentence-transformers/all-MiniLM-L6-v2
   - Produce trace embedding by mean-pooling all span embeddings
   - Result: 384-dimensional float32 vector per trace

3. PATCHCORE MEMORY BANK
   - On first N=50 NORMAL traces (collected during calibration run), 
     store their embeddings in the memory bank (Faiss IndexFlatL2)
   - For each new trace: compute nearest-neighbor distance to memory bank
   - Anomaly score = min distance to any memory bank entry
   - Threshold τ (default 0.45): if score > τ → ANOMALY, else NORMAL

4. ANOMALY SUB-CLASSIFICATION
   If PatchCore flags ANOMALY, run a secondary SVM classifier 
   (trained on labeled synthetic dataset) to determine which of:
   HALLUCINATION / CONTEXT_BLEED / PLAN_DRIFT
```

### 8.3 Synthetic Dataset Generation

Build a script `tests/fixtures/generate_synthetic_traces.py` that generates labeled training data:

```python
SYNTHETIC_SCENARIOS = {
    FailureType.HALLUCINATION: [
        # Scenario: RAG agent retrieves context about topic A, but LLM output references topic B
        # Signal: output_summary has low semantic similarity to input_summary (< 0.3 cosine)
        #         AND span_type == "llm_call"
        "Generate 20 traces where the LLM output embedding is far from the input context embedding"
    ],
    FailureType.CONTEXT_BLEED: [
        # Scenario: Memory read returns entries with different user_id than current session
        # Signal: metadata['memory_key'] contains a different session marker than trace-level session_id
        "Generate 20 traces with mismatched session context in memory reads"
    ],
    FailureType.PLAN_DRIFT: [
        # Scenario: Planner emits [task_A, task_B, task_C], but executor only performs task_A and task_C
        # Signal: output of agent_step spans don't mention task_B from planner's output
        "Generate 20 traces where subtask coverage is incomplete"
    ],
    FailureType.TOOL_MISFIRE: [
        # Rule-based, so generate 20 traces with error + identical retry pattern
        "Generate 20 traces with tool error followed by identical tool call"
    ],
    FailureType.LOOP_DETECTED: [
        # Rule-based, so generate 20 traces with repeated (tool, args) tuples
        "Generate 20 traces with 3+ identical (tool_name, input_hash) pairs"
    ],
    FailureType.NORMAL: [
        # Healthy traces with varied but coherent span sequences
        "Generate 100 normal traces from CodeMind and MeetingMind example agents"
    ]
}
```

### 8.4 Assembler Service Specification

The assembler consumes `nexus.spans.raw` and groups spans into complete traces:

```python
TRACE_COMPLETION_RULES = {
    "timeout_seconds": 30,          # If no new span arrives for trace_id in 30s, close it
    "max_spans_per_trace": 500,     # Hard limit — prevents runaway agents from consuming memory
    "completion_signal": "agent_step with metadata.final == True",  # Explicit completion
}
```

On trace completion, assembler writes to Postgres `traces` and `spans` tables (schema in Section 13).

### 8.5 Phase 3 Exit Criteria

- [ ] `nexus-classifier` and `nexus-assembler` start cleanly via Docker Compose
- [ ] Synthetic dataset of 200 traces generated and committed to `tests/fixtures/`
- [ ] Classification precision ≥ 0.85 and recall ≥ 0.80 on synthetic test set (200 traces held-out)
- [ ] Classifier correctly labels all 3 examples in `examples/crewai_agent/` (manually labeled)
- [ ] Alerts for non-NORMAL classifications appear in `nexus.alerts` Kafka topic
- [ ] Postgres `traces` and `spans` tables are populated after end-to-end run
- [ ] `pytest tests/unit/classifier/` passes (min 15 unit tests: rule-based logic, embedding shape, PatchCore threshold behavior)

---

## 9. PHASE 4 — LLM CRITIC AGENT

```
Duration     : Weeks 7–8 (Weekends 7–8, ~24 hours)
Gate         : Critic produces actionable patch proposals for all 5 failure types; proposals are coherent and specific
Deliverables :
  - nexus-critic service (LangGraph state machine)
  - Prompt library in /services/critic/prompts/
  - Patch proposal schema (PatchProposal Pydantic model)
  - Manual evaluation of 20 critic outputs (human-scored)
```

### 9.1 Critic Agent Design Philosophy

The critic is NOT a general-purpose LLM chat assistant. It is a narrow, structured reasoning agent with a fixed output schema. Every critic run must produce a `PatchProposal` with a `patch_type`, an `explanation`, and a concrete `patch_content`. Vague outputs ("try improving the prompt") are rejected by a validator node.

### 9.2 LangGraph State Machine

```python
# State definition
class CriticState(TypedDict):
    alert: Alert                        # Input: the fired alert
    trace: CompleteTrace                # Input: full trace context loaded from Postgres
    failure_type: FailureType           # From alert
    root_cause_analysis: str            # Output of root_cause node
    patch_proposal: PatchProposal | None  # Output of patch_proposer node
    validation_passed: bool             # Output of validator node
    retry_count: int                    # Loop control

# Graph nodes and edges
GRAPH_DEFINITION = """
START
  → context_loader        [loads full trace from Postgres by trace_id]
  → root_cause            [LLM node: CoT reasoning over trace, produces root_cause_analysis]
  → patch_proposer        [LLM node: produces structured PatchProposal]
  → validator             [deterministic: checks PatchProposal schema completeness]
  → (if validation failed AND retry_count < 2) → root_cause  [retry loop]
  → (if validation failed AND retry_count >= 2) → fallback    [emit generic patch]
  → (if validation passed) → publisher  [write PatchProposal to Postgres + emit to healer]
END
"""
```

### 9.3 Prompt Specifications

#### Root Cause Prompt (`/services/critic/prompts/root_cause.txt`)

```
You are a senior ML infrastructure engineer performing post-mortem analysis on a failed AI agent execution.

You will be given:
1. The failure type that was automatically detected
2. The complete execution trace as a sequence of spans
3. Each span contains: span_type, input (truncated to 500 chars), output (truncated to 500 chars), duration_ms, error details

Your task: Identify the EXACT span where the failure originated, explain what went wrong mechanistically, and identify the proximate cause (the specific input, prompt instruction, tool argument, or memory entry that triggered the failure).

## Failure Type
{failure_type}

## Execution Trace ({span_count} spans)
{formatted_trace}

## Instructions
- Think step by step. Label your steps.
- Identify the failure span by its span_id.
- Do NOT suggest fixes yet. Only diagnose.
- Be specific. "The prompt did not specify output format" is acceptable. "The prompt was bad" is not.
- Your output MUST follow this exact format:

FAILURE_SPAN_ID: <span_id>
ROOT_CAUSE: <one sentence, mechanistic description>
CONTRIBUTING_FACTORS:
- <factor 1>
- <factor 2>
CONFIDENCE: <HIGH|MEDIUM|LOW>
REASONING: <step-by-step chain of thought>
```

#### Patch Proposer Prompt (`/services/critic/prompts/patch_proposer.txt`)

```
You are a senior ML infrastructure engineer. You have completed root cause analysis on a failed agent execution.

Your task: Propose ONE concrete, actionable patch that addresses the root cause.

## Root Cause Analysis
{root_cause_analysis}

## Failure Type
{failure_type}

## Failure Span
{failure_span_content}

## Available Patch Types
PROMPT_PATCH      : Modify a system prompt or user prompt template. Provide the exact text change.
TOOL_CONFIG_PATCH : Modify a tool's argument schema or validation logic. Provide the exact config change.
MEMORY_PATCH      : Add a memory validation rule or clear a specific memory key. Provide the rule.
RETRY_POLICY_PATCH: Change retry behavior (max_retries, backoff, stop conditions). Provide new config.

## Instructions
- Choose exactly ONE patch type.
- The patch_content must be copy-pasteable. No pseudocode.
- Explain WHY this patch addresses the root cause in 2-3 sentences.
- Estimate confidence that this patch will resolve the issue.

You MUST respond with valid JSON matching this exact schema:
{
  "patch_type": "PROMPT_PATCH | TOOL_CONFIG_PATCH | MEMORY_PATCH | RETRY_POLICY_PATCH",
  "target_component": "<name of the function, prompt, or config being patched>",
  "explanation": "<2-3 sentences explaining why this patch addresses the root cause>",
  "patch_content": "<the exact patch — new prompt text, config dict, or code snippet>",
  "confidence": "HIGH | MEDIUM | LOW",
  "estimated_impact": "<what metric should improve and by how much>"
}
```

### 9.4 PatchProposal Schema

```python
class PatchType(str, Enum):
    PROMPT_PATCH       = "PROMPT_PATCH"
    TOOL_CONFIG_PATCH  = "TOOL_CONFIG_PATCH"
    MEMORY_PATCH       = "MEMORY_PATCH"
    RETRY_POLICY_PATCH = "RETRY_POLICY_PATCH"

class PatchProposal(BaseModel):
    proposal_id    : str = Field(default_factory=lambda: f"patch_{uuid4().hex[:8]}")
    alert_id       : str
    trace_id       : str
    failure_type   : FailureType
    patch_type     : PatchType
    target_component: str           # e.g., "planner_system_prompt", "search_tool_validator"
    explanation    : str            # 2-3 sentences
    patch_content  : str            # The actual patch — prompt text, config JSON, code snippet
    confidence     : Literal["HIGH", "MEDIUM", "LOW"]
    estimated_impact: str           # e.g., "eval score expected to improve by 0.2–0.4"
    root_cause_analysis: str        # Preserved from root_cause node
    created_at     : datetime
    status         : Literal["PENDING_REVIEW", "APPROVED", "REJECTED", "APPLIED"] = "PENDING_REVIEW"
```

### 9.5 Validator Logic

```python
def validate_patch_proposal(proposal: dict) -> tuple[bool, str]:
    """Returns (is_valid, rejection_reason)."""

    required_fields = ["patch_type", "target_component", "explanation", "patch_content", "confidence"]
    for field in required_fields:
        if not proposal.get(field) or len(str(proposal[field])) < 10:
            return False, f"Field '{field}' is missing or too short (< 10 chars)"

    if proposal["patch_type"] not in PatchType.__members__:
        return False, f"Invalid patch_type: {proposal['patch_type']}"

    if proposal["confidence"] not in ("HIGH", "MEDIUM", "LOW"):
        return False, f"Invalid confidence value"

    vague_phrases = ["try improving", "consider changing", "might help", "could be better"]
    for phrase in vague_phrases:
        if phrase in proposal["explanation"].lower():
            return False, f"Explanation too vague: contains '{phrase}'"

    return True, ""
```

### 9.6 Phase 4 Exit Criteria

- [ ] `nexus-critic` service starts cleanly and consumes from `nexus.alerts`
- [ ] Critic produces a valid `PatchProposal` for each of the 5 failure types in the synthetic test set
- [ ] Manual evaluation: 20 proposals reviewed, ≥ 15 rated "actionable" (the patch_content is copy-pasteable and relevant)
- [ ] Validator correctly rejects 5 intentionally vague proposals injected as test cases
- [ ] `PatchProposal` records written to Postgres `patches` table
- [ ] Retry loop triggers correctly when validator rejects (verified in integration test)
- [ ] `pytest tests/unit/critic/` passes (min 10 tests: validator logic, prompt formatting, state machine transitions)

---

## 10. PHASE 5 — AUTO-HEALER & EVAL LOOP

```
Duration     : Weeks 8–9 (Weekends 8–9, ~24 hours)
Gate         : Full loop demonstrated end-to-end — failure detected, patch proposed, approved, applied, eval re-run, score delta logged in MLflow
Deliverables :
  - nexus-healer service
  - Slack webhook notification (optional but recommended for demo)
  - MLflow integration showing before/after eval scores
  - End-to-end test: test_full_loop.py passes
```

### 10.1 Healer Workflow

```
TRIGGER: PatchProposal with status == PENDING_REVIEW arrives (via Postgres poll or Redis pub/sub)

STEP 1 — NOTIFICATION
  If slack_webhook_url configured:
    POST to Slack with proposal summary, confidence, patch_content, and two action buttons:
    [✅ Approve & Apply] [❌ Reject]
  If no Slack configured OR autonomous_mode == True:
    Proceed directly to STEP 2 after auto_approve_delay_seconds (default: 0 in autonomous_mode)

STEP 2 — PATCH APPLICATION
  patch_type == PROMPT_PATCH:
    Write new prompt text to patch_store (Postgres patches table, applied_content column)
    Update agent's active_prompt_id via Config Store API (see 10.2)

  patch_type == TOOL_CONFIG_PATCH:
    Write new tool config to patch_store
    Notify agent runtime via Redis pub/sub channel: nexus:config:update:{agent_name}

  patch_type == MEMORY_PATCH:
    Execute memory clear / rule addition via agent's memory API endpoint

  patch_type == RETRY_POLICY_PATCH:
    Write new retry config to patch_store
    Notify agent runtime via Redis pub/sub

STEP 3 — EVAL RE-RUN
  Load the original trace's input (trace.root_input from Postgres)
  Re-run the agent with the same input (via agent's /run endpoint or function call)
  Instrument the re-run with nexus.trace (so the new trace is also captured)
  Run DeepEval evaluation harness on (new_output, original_input, reference_output if available)
  Metrics evaluated:
    - answer_relevancy (DeepEval built-in)
    - faithfulness (if RAG agent)
    - task_completion (custom G-Eval metric: did the agent complete the original task?)

STEP 4 — SCORE LOGGING
  Log to MLflow run:
    params: {patch_id, patch_type, failure_type, agent_name}
    metrics: {before_score, after_score, score_delta, eval_duration_ms}
    artifacts: {before_trace.json, after_trace.json, patch_content.txt}

STEP 5 — HEALTH DIFF EMISSION
  Publish HealthDiff event to Redis channel: nexus:health:{agent_name}
  Dashboard WebSocket consumers receive it and update in real time
```

### 10.2 Config Store Design

The Config Store is a simple abstraction layer over Postgres that stores the "active configuration" for each instrumented agent component:

```sql
-- In postgres_init.sql
CREATE TABLE agent_configs (
    config_id      TEXT PRIMARY KEY,
    agent_name     TEXT NOT NULL,
    component_name TEXT NOT NULL,          -- e.g., "planner_system_prompt", "search_tool"
    config_type    TEXT NOT NULL,          -- "prompt" | "tool_config" | "retry_policy"
    content        TEXT NOT NULL,          -- current active content
    version        INTEGER DEFAULT 1,
    applied_patch_id TEXT REFERENCES patches(proposal_id),
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at     TIMESTAMPTZ DEFAULT NOW()
);
```

The healer writes patched content here. The agent application can poll this table or subscribe via Redis to pick up config changes.

### 10.3 DeepEval Integration

```python
# services/healer/eval_runner.py

from deepeval import evaluate
from deepeval.metrics import AnswerRelevancyMetric, FaithfulnessMetric, GEval
from deepeval.test_case import LLMTestCase
from deepeval.models import GeminiModel

EVAL_MODEL = GeminiModel(model="gemini-2.0-flash")

TASK_COMPLETION_METRIC = GEval(
    name="TaskCompletion",
    criteria="""
    Did the AI agent successfully complete the task described in the input?
    Score 1.0 if task fully completed with correct output.
    Score 0.5 if task partially completed or output is partially correct.
    Score 0.0 if task was not completed or output is wrong.
    """,
    evaluation_params=["input", "actual_output"],
    model=EVAL_MODEL,
)

def run_eval(input_text: str, actual_output: str, retrieval_context: list[str] = None) -> EvalResult:
    test_case = LLMTestCase(
        input=input_text,
        actual_output=actual_output,
        retrieval_context=retrieval_context or [],
    )
    metrics = [
        AnswerRelevancyMetric(threshold=0.5, model=EVAL_MODEL),
        TASK_COMPLETION_METRIC,
    ]
    if retrieval_context:
        metrics.append(FaithfulnessMetric(threshold=0.5, model=EVAL_MODEL))

    results = evaluate([test_case], metrics)
    composite_score = sum(m.score for m in results[0].metrics) / len(results[0].metrics)
    return EvalResult(composite_score=composite_score, per_metric=results[0].metrics)
```

### 10.4 End-to-End Test Specification

This is the demo test. It must pass cleanly and produce the "WOW" sequence.

```python
# tests/e2e/test_full_loop.py

def test_full_loop_tool_misfire():
    """
    SCENARIO:
    A CrewAI agent is given a task. It calls a search tool with bad arguments
    (empty query string), gets an error, and retries with the same empty query.
    
    EXPECTED NEXUS BEHAVIOR:
    1. Classifier detects TOOL_MISFIRE within 30 seconds
    2. Alert fires on nexus.alerts topic
    3. Critic produces a TOOL_CONFIG_PATCH proposal with a query validation rule
    4. Healer applies patch (autonomous_mode=True in test)
    5. Healer re-runs agent with same input
    6. After-patch eval score > before-patch eval score by >= 0.2
    7. MLflow run logged with before/after metrics
    8. HealthDiff event emitted to Redis
    
    ASSERTIONS (in order):
    - alert.failure_type == FailureType.TOOL_MISFIRE
    - proposal.patch_type == PatchType.TOOL_CONFIG_PATCH
    - proposal.confidence in ("HIGH", "MEDIUM")
    - after_score - before_score >= 0.20
    - mlflow_run.metrics["score_delta"] > 0
    - redis_event["agent_name"] == "test_crewai_agent"
    """
    ...

def test_full_loop_hallucination():
    """Similar scenario for HALLUCINATION failure type."""
    ...
```

### 10.5 Phase 5 Exit Criteria

- [ ] `nexus-healer` service starts cleanly
- [ ] `test_full_loop_tool_misfire` passes (all assertions green)
- [ ] `test_full_loop_hallucination` passes
- [ ] MLflow UI shows at least 2 runs with before/after score metrics
- [ ] MTTR from alert fire to MLflow score logged ≤ 90 seconds (measured in test)
- [ ] Slack webhook notification sends correctly when `SLACK_WEBHOOK_URL` env var set

---

## 11. PHASE 6 — DASHBOARD & OSS RELEASE

```
Duration     : Weeks 10–11 (Weekends 10–11, ~24 hours)
Gate         : Dashboard live at localhost:3000, pip install nexus-agent works, GitHub release published
Deliverables :
  - React 18 dashboard (all 5 panels functional)
  - PyPI package published
  - docker-compose up --build starts all services in one command
  - README with quickstart, architecture diagram, and demo GIF
  - GitHub release v1.0.0
```

### 11.1 Dashboard Component Specifications

#### Component 1: `TraceStream.tsx`
- Real-time WebSocket feed of incoming spans
- Show last 50 spans in a scrolling table
- Columns: `time`, `agent_name`, `span_type`, `duration_ms`, `status` (normal/error)
- Color-code status: green = NORMAL, red = any failure type
- Auto-scroll to newest, with "pause" button

#### Component 2: `FailureTimeline.tsx`
- Time-series chart (Recharts `LineChart`) of failure events over last 24 hours
- X-axis: time (1-hour buckets)
- Y-axis: failure count
- One line per FailureType (5 lines, distinct colors)
- Click on a data point → opens TraceDetail modal

#### Component 3: `CriticPanel.tsx`
- Shows the most recent `PatchProposal` for each agent
- For each proposal: failure_type badge, target_component, explanation text, patch_content in a `<code>` block
- Approve / Reject buttons (POST to `/v1/patches/{id}/approve` or `/reject`)
- Confidence indicator (HIGH = green, MEDIUM = yellow, LOW = red)

#### Component 4: `PatchHistory.tsx`
- Table of all applied patches with before/after scores
- Columns: `time`, `agent`, `failure_type`, `patch_type`, `before_score`, `after_score`, `delta`
- Delta column: render as colored pill (green if positive, red if negative)
- Sort by delta descending by default

#### Component 5: `HealthScore.tsx`
- One card per instrumented agent
- Score = rolling 1-hour average of composite eval scores (0.0 – 1.0)
- Display as large number + color-coded ring (green ≥ 0.8, yellow 0.6–0.8, red < 0.6)
- Shows `last_failure_type` and `last_failure_time` below score
- Real-time updates via WebSocket `nexus:health:{agent_name}` Redis channel

#### WebSocket Protocol

```
// Client connects to: ws://localhost:8001/ws/traces

// Server sends messages of two types:
type NexusWSMessage =
  | { type: "span"; data: Span }
  | { type: "alert"; data: Alert }
  | { type: "patch_proposal"; data: PatchProposal }
  | { type: "health_diff"; data: HealthDiff }
  | { type: "ping" }  // sent every 30s for keepalive
```

### 11.2 PyPI Package Specification

```toml
# sdk/pyproject.toml

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "nexus-agent"
version = "1.0.0"
description = "Production AI health monitor and self-healing platform for multi-agent systems"
readme = "README.md"
license = {file = "LICENSE"}
authors = [{name = "Sankalp Rajeev", email = "srajeev@umich.edu"}]
keywords = ["llmops", "agents", "observability", "mlops", "ai", "langchain", "crewai"]
classifiers = [
    "Development Status :: 4 - Beta",
    "Intended Audience :: Developers",
    "Topic :: Software Development :: Libraries :: Python Modules",
    "Topic :: Scientific/Engineering :: Artificial Intelligence",
    "Programming Language :: Python :: 3.11",
]
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.27",
    "pydantic>=2.7",
    "opentelemetry-sdk>=1.24",
]

[project.optional-dependencies]
langchain = ["langchain>=0.2", "langchain-core>=0.2"]
crewai    = ["crewai>=0.51"]
all       = ["nexus-agent[langchain,crewai]"]
```

### 11.3 README Requirements

The README must contain, in this order:

1. **One-line description** — what Nexus does
2. **The loop diagram** — ASCII version of the OBSERVE→STREAM→DETECT→DIAGNOSE→PATCH→EVALUATE loop
3. **Demo GIF** — screen recording of the full loop running (capture with LICEcap or similar)
4. **Quickstart** (must work copy-paste):
   ```bash
   git clone https://github.com/sankalp-rajeev/nexus
   cd nexus
   cp .env.example .env  # add your GEMINI_API_KEY
   docker compose up --build
   # In a new terminal:
   pip install nexus-agent
   python examples/crewai_agent/run_demo.py
   # Open http://localhost:3000
   ```
5. **Architecture section** with the ASCII diagram from `docs/architecture.md`
6. **How it works** — one paragraph per module (Collector, Classifier, Critic, Healer, Dashboard)
7. **SDK usage examples** — the 4 patterns from Section 7.2
8. **Configuration reference** — table of all environment variables
9. **Contributing guide** — brief

### 11.4 Environment Variables Reference

```bash
# .env.example — all services read from this via docker-compose

# LLM credentials
GEMINI_API_KEY=your_gemini_api_key_here
OPENAI_API_KEY=your_openai_api_key_here  # optional fallback

# Kafka
KAFKA_BOOTSTRAP_SERVERS=kafka:9092

# Postgres
POSTGRES_USER=nexus
POSTGRES_PASSWORD=nexus_dev_password
POSTGRES_DB=nexus
POSTGRES_HOST=postgres
POSTGRES_PORT=5432

# Redis
REDIS_HOST=redis
REDIS_PORT=6379

# MLflow
MLFLOW_TRACKING_URI=http://mlflow:5000

# Critic configuration
CRITIC_LLM_PROVIDER=gemini           # gemini | openai
CRITIC_MODEL=gemini-2.0-flash
CRITIC_MAX_RETRIES=2

# Healer configuration
AUTONOMOUS_MODE=false                 # true = auto-apply without human approval
AUTO_APPROVE_DELAY_SECONDS=0         # only used in autonomous_mode
SLACK_WEBHOOK_URL=                   # optional

# Classifier configuration
PATCHCORE_THRESHOLD=0.45
PATCHCORE_MEMORY_SIZE=500
CALIBRATION_TRACES=50                # how many NORMAL traces to collect before classifier activates

# Collector
COLLECTOR_PORT=8000
COLLECTOR_KAFKA_TOPIC=nexus.spans.raw

# API / Dashboard
API_PORT=8001
DASHBOARD_PORT=3000
```

### 11.5 Phase 6 Exit Criteria

- [ ] `docker compose up --build` starts all 11 services cleanly with no errors
- [ ] Dashboard loads at `localhost:3000` with all 5 panels rendering
- [ ] TraceStream panel shows live spans from `examples/crewai_agent/run_demo.py`
- [ ] `pip install nexus-agent` works from PyPI (or TestPyPI for pre-release)
- [ ] README contains all 9 sections from Section 11.3
- [ ] Demo GIF recorded and embedded in README
- [ ] GitHub release `v1.0.0` tagged and published
- [ ] `.env.example` contains all variables from Section 11.4

---

## 12. PHASE 7 — TESTING & QA

```
Duration     : Parallel to Phases 2–6 (write tests as you build each module)
Gate         : All test suites pass; coverage ≥ 70% on core modules; e2e test passes cleanly
Deliverables :
  - Pytest test suites for all services
  - GitHub Actions CI pipeline (runs on every push to main)
  - Coverage report
```

### 12.1 Test Suite Inventory

| Test File | Type | Min Tests | What It Covers |
|---|---|---|---|
| `tests/unit/sdk/test_decorators.py` | Unit | 10 | `@nexus.trace` wrapping, timing, fail-silent |
| `tests/unit/sdk/test_client.py` | Unit | 8 | NexusClient init, config, flush |
| `tests/unit/sdk/test_models.py` | Unit | 5 | Span model validation, serialization |
| `tests/unit/classifier/test_rules.py` | Unit | 10 | Loop detector, tool misfire rule |
| `tests/unit/classifier/test_embedder.py` | Unit | 5 | Embedding shape, determinism |
| `tests/unit/classifier/test_patchcore.py` | Unit | 8 | Memory bank insertion, distance calc, threshold |
| `tests/unit/critic/test_validator.py` | Unit | 10 | Valid proposals pass, vague proposals rejected |
| `tests/unit/critic/test_prompts.py` | Unit | 5 | Prompt formatting with various trace shapes |
| `tests/unit/healer/test_eval_runner.py` | Unit | 6 | EvalResult schema, score computation |
| `tests/integration/test_collector_kafka.py` | Integration | 5 | Span POST → Kafka topic appears |
| `tests/integration/test_classifier_pipeline.py` | Integration | 5 | Kafka span → classification → alert |
| `tests/integration/test_critic_pipeline.py` | Integration | 5 | Alert → PatchProposal in Postgres |
| `tests/e2e/test_full_loop.py` | E2E | 2 | Full loop for TOOL_MISFIRE and HALLUCINATION |

**Total minimum test count: 84 tests**

### 12.2 GitHub Actions CI Pipeline

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      kafka:
        image: bitnami/kafka:3.6
        env:
          KAFKA_CFG_NODE_ID: 0
          KAFKA_CFG_PROCESS_ROLES: controller,broker
          KAFKA_CFG_LISTENERS: PLAINTEXT://:9092,CONTROLLER://:9093
          KAFKA_CFG_LISTENER_SECURITY_PROTOCOL_MAP: CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT
          KAFKA_CFG_CONTROLLER_QUORUM_VOTERS: 0@kafka:9093
          KAFKA_CFG_CONTROLLER_LISTENER_NAMES: CONTROLLER
        ports: ["9092:9092"]
      postgres:
        image: timescale/timescaledb:latest-pg15
        env:
          POSTGRES_USER: nexus
          POSTGRES_PASSWORD: nexus_test
          POSTGRES_DB: nexus_test
        ports: ["5432:5432"]
      redis:
        image: redis:7
        ports: ["6379:6379"]

    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.11"}
      - run: pip install -e "./sdk[all]" pytest pytest-asyncio pytest-cov ruff mypy
      - run: ruff check .
      - run: mypy sdk/nexus_agent/ --ignore-missing-imports
      - run: pytest tests/unit/ -v --cov=nexus_agent --cov=services --cov-report=xml
      - run: pytest tests/integration/ -v --timeout=60
      - uses: codecov/codecov-action@v4
```

### 12.3 Coverage Requirements

| Module | Minimum Coverage |
|---|---|
| `sdk/nexus_agent/` | 80% |
| `services/collector/` | 75% |
| `services/classifier/` | 75% |
| `services/critic/` | 70% |
| `services/healer/` | 70% |
| `services/api/` | 65% |

---

## 13. DATA MODELS & SCHEMAS

### 13.1 Span (Core SDK Model)

```python
class SpanType(str, Enum):
    LLM_CALL      = "llm_call"
    TOOL_CALL     = "tool_call"
    AGENT_STEP    = "agent_step"
    MEMORY_READ   = "memory_read"
    MEMORY_WRITE  = "memory_write"
    AGENT_HANDOFF = "agent_handoff"
    RETRIEVAL     = "retrieval"
    CUSTOM        = "custom"

class Span(BaseModel):
    span_id        : str = Field(default_factory=lambda: f"span_{uuid4().hex[:12]}")
    trace_id       : str                          # Groups all spans of one agent run
    parent_span_id : str | None = None            # For nested spans
    agent_name     : str                          # Top-level agent system name
    span_type      : SpanType
    input          : str                          # Serialized input, max 2000 chars
    output         : str | None = None            # Serialized output, max 2000 chars
    duration_ms    : float
    error_type     : str | None = None            # Exception class name if raised
    error_message  : str | None = None            # Exception message, max 500 chars
    metadata       : dict[str, Any] = {}          # Arbitrary: model, tokens, tool_name, etc.
    client_timestamp: datetime
    server_timestamp: datetime | None = None      # Set by collector on receipt
    environment    : str = "development"
    sdk_version    : str

class SpanBatch(BaseModel):
    spans          : list[Span] = Field(max_length=100)
    batch_id       : str = Field(default_factory=lambda: uuid4().hex)
```

### 13.2 Postgres Schema

```sql
-- infra/init/postgres_init.sql

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE traces (
    trace_id        TEXT PRIMARY KEY,
    agent_name      TEXT NOT NULL,
    environment     TEXT NOT NULL DEFAULT 'development',
    root_input      TEXT,                           -- Input to the first span
    final_output    TEXT,                           -- Output from the last span
    span_count      INTEGER DEFAULT 0,
    total_duration_ms FLOAT,
    started_at      TIMESTAMPTZ NOT NULL,
    completed_at    TIMESTAMPTZ,
    status          TEXT DEFAULT 'in_progress'      -- in_progress | completed | failed
);

CREATE TABLE spans (
    span_id         TEXT PRIMARY KEY,
    trace_id        TEXT NOT NULL REFERENCES traces(trace_id),
    parent_span_id  TEXT,
    agent_name      TEXT NOT NULL,
    span_type       TEXT NOT NULL,
    input           TEXT,
    output          TEXT,
    duration_ms     FLOAT,
    error_type      TEXT,
    error_message   TEXT,
    metadata        JSONB DEFAULT '{}',
    client_timestamp TIMESTAMPTZ NOT NULL,
    server_timestamp TIMESTAMPTZ NOT NULL
);

SELECT create_hypertable('spans', 'server_timestamp');  -- TimescaleDB time partitioning
CREATE INDEX ON spans (trace_id, server_timestamp DESC);
CREATE INDEX ON spans (agent_name, span_type, server_timestamp DESC);

CREATE TABLE classifications (
    classification_id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    trace_id        TEXT NOT NULL REFERENCES traces(trace_id),
    failure_type    TEXT NOT NULL,
    anomaly_score   FLOAT,                          -- PatchCore distance
    confidence      FLOAT,                          -- Classifier confidence 0-1
    triggered_rule  TEXT,                           -- If rule-based: rule name; if ML: 'patchcore'
    failure_span_id TEXT REFERENCES spans(span_id),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE alerts (
    alert_id        TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    trace_id        TEXT NOT NULL REFERENCES traces(trace_id),
    classification_id TEXT REFERENCES classifications(classification_id),
    agent_name      TEXT NOT NULL,
    failure_type    TEXT NOT NULL,
    severity        TEXT DEFAULT 'HIGH',            -- HIGH | MEDIUM | LOW
    status          TEXT DEFAULT 'OPEN',            -- OPEN | ACKNOWLEDGED | RESOLVED
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ
);

CREATE TABLE patches (
    proposal_id     TEXT PRIMARY KEY,
    alert_id        TEXT NOT NULL REFERENCES alerts(alert_id),
    trace_id        TEXT NOT NULL,
    failure_type    TEXT NOT NULL,
    patch_type      TEXT NOT NULL,
    target_component TEXT NOT NULL,
    explanation     TEXT NOT NULL,
    patch_content   TEXT NOT NULL,
    confidence      TEXT NOT NULL,
    estimated_impact TEXT,
    root_cause_analysis TEXT,
    status          TEXT DEFAULT 'PENDING_REVIEW',  -- PENDING_REVIEW | APPROVED | REJECTED | APPLIED
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    applied_at      TIMESTAMPTZ
);

CREATE TABLE eval_runs (
    run_id          TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    patch_id        TEXT REFERENCES patches(proposal_id),
    trace_id        TEXT NOT NULL,
    agent_name      TEXT NOT NULL,
    before_score    FLOAT,
    after_score     FLOAT,
    score_delta     FLOAT GENERATED ALWAYS AS (after_score - before_score) STORED,
    per_metric_scores JSONB DEFAULT '{}',
    eval_duration_ms FLOAT,
    mlflow_run_id   TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE agent_configs (
    config_id       TEXT PRIMARY KEY,
    agent_name      TEXT NOT NULL,
    component_name  TEXT NOT NULL,
    config_type     TEXT NOT NULL,
    content         TEXT NOT NULL,
    version         INTEGER DEFAULT 1,
    applied_patch_id TEXT REFERENCES patches(proposal_id),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 14. API CONTRACTS

### 14.1 Collector Service (port 8000)

```
POST /v1/spans
Request:
  Content-Type: application/json
  Body: SpanBatch

Response 202 Accepted:
  {"accepted": int, "rejected": int, "batch_id": str, "trace_ids": [str]}

Response 422 Unprocessable Entity:
  {"detail": [{"loc": [...], "msg": str, "type": str}]}

POST /v1/spans/single
Request:  Span
Response: {"span_id": str, "trace_id": str}

GET /health
Response: {"status": "ok|degraded", "kafka_connected": bool, "spans_received_total": int, "uptime_seconds": float}
```

### 14.2 API Service (port 8001)

```
GET /v1/traces
Query params: agent_name?, limit=50, offset=0, status?
Response: {"traces": [Trace], "total": int}

GET /v1/traces/{trace_id}
Response: {"trace": Trace, "spans": [Span], "classification": Classification | null, "alert": Alert | null}

GET /v1/alerts
Query params: agent_name?, status=OPEN, limit=20
Response: {"alerts": [Alert], "total": int}

GET /v1/patches
Query params: agent_name?, status?, limit=20
Response: {"patches": [PatchProposal], "total": int}

POST /v1/patches/{proposal_id}/approve
Response: {"proposal_id": str, "status": "APPROVED", "healer_triggered": bool}

POST /v1/patches/{proposal_id}/reject
Body: {"reason": str}
Response: {"proposal_id": str, "status": "REJECTED"}

GET /v1/agents/{agent_name}/health
Response: {"agent_name": str, "health_score": float, "last_failure_type": str | null, "last_failure_at": datetime | null, "open_alerts": int}

GET /v1/eval-runs
Query params: agent_name?, limit=20
Response: {"eval_runs": [EvalRun], "total": int}

WebSocket: ws://localhost:8001/ws/traces
Protocol: See Section 11.1
```

---

## 15. NON-FUNCTIONAL REQUIREMENTS

### 15.1 Performance

| Requirement | Target | Notes |
|---|---|---|
| SDK span emission overhead | < 5ms p99 | Measured against uninstrumented baseline |
| Kafka ingestion latency | < 500ms p95 | Collector POST to Kafka commit |
| Classification latency | < 10s per trace | From trace completion to classification published |
| Critic response time | < 60s | LLM API call + graph traversal |
| Dashboard WebSocket update | < 2s lag | From Kafka event to browser render |
| Docker Compose startup | < 120s | All services healthy |

### 15.2 Reliability

- SDK: fail-silent on all external calls; zero uncaught exceptions propagated to user code
- Collector: at-least-once delivery to Kafka (Kafka `acks=1`)
- Classifier: idempotent — processing the same trace twice produces the same classification
- Critic: retry up to 2 times on validator rejection before emitting fallback proposal
- Healer: eval re-run is independent of patch application — if re-run fails, patch is still applied

### 15.3 Scalability (OSS / Dev scale — single machine)

- Target: handle 10 concurrent instrumented agent systems
- Target: ingest 1,000 spans/minute without Kafka lag
- Not required: horizontal scaling, multi-node Kafka, sharded Postgres

### 15.4 Developer Experience

- `pip install nexus-agent` and `nexus.init()` must be the entire SDK onboarding
- `docker compose up` must start everything with zero manual steps beyond setting API keys in `.env`
- All services must log to stdout in structured JSON format (for easy Docker log inspection)
- Every service must have a `/health` endpoint returning 200 when ready

---

## 16. CONSTRAINTS & ASSUMPTIONS

### 16.1 Constraints

```
C1  Weekend-only development — approximately 12–16 hours per week.
C2  Single developer — no parallel workstreams.
C3  Hardware: RTX 4080 (16GB VRAM) available but not required.
    All ML components must run on CPU for portability.
    GPU acceleration is a performance bonus, not a requirement.
C4  External LLM API costs must stay under $10 total during development.
    Use Gemini Flash (free tier) as primary. GPT-4o-mini as fallback only.
C5  No proprietary Magna data may be used. All examples use synthetic traces
    or open-source agent examples.
C6  PyPI package must have zero mandatory dependencies beyond httpx and pydantic.
    All ML dependencies (sentence-transformers, torch) go in optional extras.
```

### 16.2 Assumptions

```
A1  User's agent application is Python 3.11+.
A2  Docker and Docker Compose v2 are available on the developer's machine.
A3  Gemini API free tier (1M tokens/day) is sufficient for Critic LLM calls during dev.
A4  sentence-transformers/all-MiniLM-L6-v2 can be downloaded from HuggingFace during build.
A5  The existing CodeMind and MeetingMind repos are available as testbed agents.
A6  Calibration period (50 normal traces) is achievable from example agent runs before
    the classifier activates — this is not a cold-start problem.
```

---

## 17. RISK REGISTER

| ID | Risk | Probability | Impact | Mitigation |
|---|---|---|---|---|
| R1 | PatchCore anomaly detection has high false positive rate on novel traces | Medium | High | Tune threshold τ on held-out set; provide `nexus calibrate` CLI command to re-calibrate; fallback to IsolationForest |
| R2 | LLM Critic produces vague or incorrect patch proposals | Medium | Medium | Validator node rejects vague output; 2 retries with more explicit prompt; fallback generic proposals for each failure type |
| R3 | Gemini API rate limits during e2e test runs | Low | Medium | Add exponential backoff in critic; cache test run responses in `tests/fixtures/critic_responses/` |
| R4 | Docker Compose resource usage exceeds developer machine capacity | Low | High | Profile early; TimescaleDB + Kafka are the heavy hitters; add resource limits in compose file |
| R5 | Classifier cold-start — not enough normal traces for memory bank | Medium | Medium | Ship 50 pre-generated normal trace embeddings in `data/normal_traces_seed.pkl` bundled with classifier image |
| R6 | Agent re-run for eval produces non-deterministic outputs | High | Low | This is expected; score improvement only needs to be positive on average across 3 re-runs |
| R7 | PyPI package name `nexus-agent` already taken | Low | Low | Check before Week 10; fallback names: `nexus-llmops`, `nexus-monitor` |

---

## 18. GLOSSARY

| Term | Definition |
|---|---|
| Span | A single instrumented event in an agent's execution. Has a type (llm_call, tool_call, etc.), input, output, and duration. |
| Trace | A collection of all spans belonging to one complete agent execution run, grouped by trace_id. |
| PatchCore | An anomaly detection algorithm that maintains a memory bank of normal feature embeddings and flags new inputs whose nearest-neighbor distance exceeds a threshold. Originally from "Towards Total Recall in Industrial Anomaly Detection" (Roth et al., 2022). |
| LLM Critic | The LangGraph agent within Nexus responsible for root cause analysis and patch proposal generation. |
| Patch Proposal | A structured artifact produced by the Critic containing: failure diagnosis, patch type, target component, and the exact patch content to apply. |
| Auto-Healer | The Nexus service that receives approved Patch Proposals, applies them to the agent's config, re-runs the eval harness, and logs the score delta. |
| MTTR | Mean Time To Recovery — measured from when an alert fires to when a positive score delta is logged in MLflow. Target: < 90 seconds. |
| Health Score | A rolling 1-hour composite eval score for an agent system (0.0 – 1.0). Aggregates task_completion, answer_relevancy, and optionally faithfulness. |
| Config Store | The Postgres `agent_configs` table that stores active prompt/tool configurations per agent component. The Healer writes here; agent apps can read here or subscribe via Redis. |
| Calibration Period | The initial phase when the classifier collects 50 NORMAL traces to populate its PatchCore memory bank before activating anomaly detection. |
| Fail-Silent | The SDK design principle that any error in the observability layer (network failure, timeout, schema error) is caught, logged as a warning, and dropped — never propagated to the user's agent code. |
| Autonomous Mode | Healer configuration where patch proposals are applied automatically without human approval (used in CI/test environments). Default: false. |

---

```
END OF DOCUMENT
Version 1.0.0 — Ready for Phase 1 implementation.
Feed this document to your agentic IDE and begin with Phase 1, Section 6.
```
