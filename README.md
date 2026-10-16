# Nexus — AI Agent Monitor & Self-Healing Platform

End-to-end observability and autonomous self-healing for multi-agent AI pipelines. Nexus detects failures the moment they occur, diagnoses root causes with an LLM critic, and automatically patches the agent configuration — closing the loop in under 90 seconds.

## What Nexus Evaluates

Nexus targets five agent failure modes:

- Hallucination
- Context bleed
- Plan drift
- Tool misfire
- Repetitive loops

For each detected failure:

1. Capture the execution trace
2. Classify the failure
3. Diagnose the root cause
4. Propose a structured configuration patch
5. Re-run the same task
6. Compare before/after evaluation metrics
```
OBSERVE → STREAM → DETECT → DIAGNOSE → PATCH → EVALUATE → OBSERVE
  SDK       Kafka   Classifier  Critic    Healer   DeepEval    (loop)
```

---

## Quickstart

```bash
git clone https://github.com/sankalp-rajeev/Nexus
cd Nexus
cp .env.example .env        # add your GEMINI_API_KEY
docker compose up --build   # starts all 11 services

# In a new terminal:
pip install nexus-agent
python examples/crewai_agent/run_demo.py

# Open http://localhost:3000
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         NEXUS PLATFORM                               │
│                                                                       │
│  Your Agent                                                           │
│  ┌──────────┐    ┌───────────────┐    ┌─────────────────────────┐   │
│  │ nexus    │───▶│  Collector    │───▶│  Kafka                  │   │
│  │ .trace() │    │  (FastAPI)    │    │  nexus.spans.raw        │   │
│  └──────────┘    └───────────────┘    └──────────┬──────────────┘   │
│                                                   │                   │
│                  ┌───────────────┐    ┌───────────▼──────────────┐   │
│                  │  Assembler    │◀───│  nexus.spans.assembled   │   │
│                  │  (TraceBuffer)│    └──────────────────────────┘   │
│                  └──────┬────────┘                                   │
│                         │ CompleteTrace                               │
│                  ┌──────▼────────┐                                   │
│                  │  Classifier   │  Stage 1: rule-based (LOOP,TOOL)  │
│                  │  SVM + NLI    │  Stage 2: ML (HALLUCINATION, etc) │
│                  └──────┬────────┘                                   │
│                         │ Alert → nexus.alerts                        │
│                  ┌──────▼────────┐                                   │
│                  │  LLM Critic   │  LangGraph + Gemini 2.0 Flash     │
│                  │  (LangGraph)  │  root_cause → patch_proposer      │
│                  └──────┬────────┘                                   │
│                         │ PatchProposal → Postgres patches           │
│                  ┌──────▼────────┐                                   │
│                  │  Healer       │  5-step workflow:                  │
│                  │               │  Notify → Apply → Eval → MLflow   │
│                  └──────┬────────┘       → HealthDiff (Redis)        │
│                         │                                             │
│                  ┌──────▼────────┐                                   │
│                  │  Dashboard    │  React 18 + WebSocket              │
│                  │  (localhost:  │  TraceStream | Timeline | Critic   │
│                  │   3000)       │  PatchHistory | HealthScore        │
│                  └───────────────┘                                   │
│                                                                       │
│  Storage: TimescaleDB (spans) · Redis (pub/sub) · MLflow (metrics)   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## How It Works

**Collector** — Zero-config HTTP ingestion endpoint. Receives `SpanBatch` payloads from the `nexus-agent` SDK, validates them with Pydantic, and publishes to the `nexus.spans.raw` Kafka topic. Fail-silent: a downed collector never crashes your agent.

**Classifier** — Two-stage failure detection. Stage 1: rule-based detection of LOOP_DETECTED (identical consecutive steps) and TOOL_MISFIRE (error + identical retry). Stage 2: SVM trained on MiniLM embeddings (384-dim) + PatchCore anomaly score + io_divergence + NLI contradiction score (387 total features) to classify HALLUCINATION, CONTEXT_BLEED, and PLAN_DRIFT. Trained on synthetic traces, evaluated on real HaluEval and ToolBench traces with source-stratified splitting. Precision: 1.000 across all sources.

**LLM Critic** — LangGraph state machine using Gemini 2.0 Flash. Two nodes: `root_cause` (diagnoses the failure) and `patch_proposer` (writes a structured patch). Output is validated against a strict schema; retries up to 2 times on malformed output. Produces `PatchProposal` records written to Postgres.

**Healer** — Polls Postgres for `PENDING_REVIEW` patches and executes the 5-step workflow: (1) Slack notification or autonomous auto-approve, (2) write patch to `agent_configs` + Redis pub/sub notify, (3) re-run agent with same input and evaluate with DeepEval + Gemini, (4) log before/after/delta metrics to MLflow, (5) emit `HealthDiff` to Redis for real-time dashboard updates.

**Dashboard** — React 18 single-page app with WebSocket connection to the API. Five panels: TraceStream (live span feed), FailureTimeline (24h failure chart), CriticPanel (patch proposals with approve/reject), PatchHistory (before/after score table), HealthScore (per-agent rolling health ring).

---

## SDK Usage

Install:

```bash
pip install nexus-agent
```

### Pattern 1 — decorator (simplest)

```python
import nexus_agent as nexus

nexus.configure(collector_url="http://localhost:8000", agent_name="my_agent")

@nexus.trace
def run_task(prompt: str) -> str:
    return llm.generate(prompt)
```

### Pattern 2 — context manager

```python
with nexus.span("llm_call", input=prompt) as s:
    output = llm.generate(prompt)
    s.output = output
```

### Pattern 3 — manual instrumentation

```python
trace_id = nexus.start_trace()
nexus.record_span(
    trace_id=trace_id,
    span_type="tool_call",
    input=tool_args,
    output=tool_result,
    duration_ms=elapsed,
)
nexus.end_trace(trace_id)
```

### Pattern 4 — LangChain callback

```python
from nexus_agent.integrations.langchain import NexusCallbackHandler

chain = MyChain(callbacks=[NexusCallbackHandler()])
```

---

## Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `GEMINI_API_KEY` | — | Gemini API key (required for Critic + Eval) |
| `OPENAI_API_KEY` | — | Optional OpenAI fallback |
| `KAFKA_BOOTSTRAP_SERVERS` | `kafka:9092` | Kafka broker address |
| `POSTGRES_HOST` | `postgres` | TimescaleDB host |
| `POSTGRES_PORT` | `5432` | TimescaleDB port |
| `POSTGRES_USER` | `nexus` | DB user |
| `POSTGRES_PASSWORD` | `nexus_dev_password` | DB password |
| `POSTGRES_DB` | `nexus` | DB name |
| `REDIS_HOST` | `redis` | Redis host |
| `REDIS_PORT` | `6379` | Redis port |
| `MLFLOW_TRACKING_URI` | `http://mlflow:5000` | MLflow server |
| `CRITIC_LLM_PROVIDER` | `gemini` | `gemini` or `openai` |
| `CRITIC_MODEL` | `gemini-2.0-flash` | Model for critic |
| `CRITIC_MAX_RETRIES` | `2` | Critic retry limit |
| `AUTONOMOUS_MODE` | `false` | Skip human approval |
| `AUTO_APPROVE_DELAY_SECONDS` | `0` | Delay before auto-apply |
| `SLACK_WEBHOOK_URL` | — | Slack notifications |
| `PATCHCORE_THRESHOLD` | `0.45` | Anomaly detection threshold |
| `CALIBRATION_TRACES` | `50` | Normal traces for warm-up |
| `COLLECTOR_PORT` | `8000` | Collector HTTP port |
| `API_PORT` | `8001` | Dashboard API port |
| `DASHBOARD_PORT` | `3000` | Dashboard port |

---

## Contributing

```bash
# Set up dev environment
python -m venv .venv
.venv/Scripts/activate  # Windows
pip install -e sdk/
pip install pytest pytest-asyncio

# Run all tests
pytest tests/unit/ tests/e2e/ -v

# Run the demo
docker compose up --build
python examples/crewai_agent/run_demo.py
```

PRs welcome. Please add tests for new functionality and run the full suite before opening a PR.

---

## License

MIT © Sankalp Rajeev
