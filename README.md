# Nexus — AI Agent Monitor & Self-Healing Platform

End-to-end observability and autonomous self-healing for multi-agent AI pipelines. Nexus detects failures the moment they occur, diagnoses root causes with an LLM critic, and automatically proposes and applies configuration patches.

> **Status:** results are being rebuilt on real runs. Every number Nexus claims lives in [RESULTS.md](RESULTS.md) with a committed result file; anything not listed there is unmeasured. Progress: [status.md](status.md).

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
cp .env.example .env        # add your GEMINI_API_KEY (or set NEXUS_LLM=mock)
docker compose up --build   # starts all 11 services

# In a new terminal (SDK is not on PyPI yet):
pip install -e sdk/
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
│                  │  LLM Critic   │  LangGraph + Gemini (pinned)      │
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

**Collector** — Zero-config HTTP ingestion endpoint. Receives `SpanBatch` payloads from the `nexus_llmops` SDK, validates them with Pydantic, and publishes to the `nexus.spans.raw` Kafka topic. Fail-silent: a downed collector never crashes your agent.

**Classifier** — Two-stage failure detection. Stage 1: rule-based detection of LOOP_DETECTED (identical consecutive steps) and TOOL_MISFIRE (error + identical retry). Stage 2: SVM trained on MiniLM embeddings (384-dim) + PatchCore anomaly score + io_divergence + NLI contradiction score (387 total features) to classify HALLUCINATION, CONTEXT_BLEED, and PLAN_DRIFT. Trained on 212 synthetic traces and evaluated on 220 real HaluEval/ToolBench traces: binary precision 1.000 at recall 0.473; hallucination recall 0.033 (2/60); CONTEXT_BLEED and PLAN_DRIFT have not yet been evaluated on real traces. See [docs/classifier_report.md](docs/classifier_report.md).

**LLM Critic** — LangGraph state machine using a pinned Gemini model (`CRITIC_MODEL`; the deterministic mock is used only with `NEXUS_LLM=mock`). Two nodes: `root_cause` (diagnoses the failure) and `patch_proposer` (writes a structured patch). Output is validated against a strict schema; retries up to 2 times on malformed output. Produces `PatchProposal` records written to Postgres.

**Healer** — Polls Postgres for `PENDING_REVIEW` patches and executes the 5-step workflow: (1) Slack notification or autonomous auto-approve, (2) write patch to `agent_configs` + Redis pub/sub notify, (3) re-run agent with same input and evaluate with DeepEval + Gemini, (4) log before/after/delta metrics to MLflow, (5) emit `HealthDiff` to Redis for real-time dashboard updates. *Known limitations:* it re-runs only the same input and grades with the same model family that wrote the patch, so a "before/after" improvement is not yet evidence that a fix generalizes; the dashboard's approve/reject is not yet enforced by the healer. A held-out promotion gate is planned (see the improvement plan).

**Dashboard** — React 18 single-page app with WebSocket connection to the API. Five panels: TraceStream (live span feed), FailureTimeline (24h failure chart), CriticPanel (patch proposals with approve/reject), PatchHistory (before/after score table), HealthScore (per-agent rolling health ring).

---

## SDK Usage

Install from the repo (not yet published to PyPI; the distribution is `nexus-llmops`, import name `nexus_llmops`; the old import name `nexus_agent` still works as an alias):

```bash
pip install -e sdk/
```

```python
import nexus_llmops as nexus

nexus.init(agent_name="my_agent", collector_url="http://localhost:8000")
```

### Pattern 1 — decorator

```python
@nexus.trace                      # bare: span_type="custom"
def plan(task: str) -> list[str]: ...

@nexus.trace(span_type="llm_call", model="gemini-3.5-flash-lite")
def call_llm(prompt: str) -> str:
    return llm.generate(prompt)
```

Works on sync and async functions. Arguments are captured as the span input and the return value as its output; exceptions are recorded and re-raised.

### Pattern 2 — context manager

```python
with nexus.span("tool_call", input=query, tool="search") as s:
    result = search_tool.run(query)
    s.set_output(result)          # or: s.output = result
```

### Pattern 3 — explicit start/end

```python
span_id = nexus.start_span("agent_step", step="retrieve")
result = do_work()
nexus.end_span(span_id, output=result)
```

Spans nest automatically (parent/trace IDs propagate through `contextvars`). Call `nexus.flush()` before a short-lived script exits.

> A LangChain callback integration is planned but not implemented yet.

---

## Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `GEMINI_API_KEY` | — | Gemini API key (required for Critic + Eval) |
| `NEXUS_LLM` | `gemini` | `gemini` or `mock`. The mock is only used when set explicitly; a missing key is an error |
| `DEEPSEEK_API_KEY` | — | Optional; independent model family for judging/benchmarks |
| `KAFKA_BOOTSTRAP_SERVERS` | `kafka:9092` | Kafka broker address |
| `POSTGRES_HOST` | `postgres` | TimescaleDB host |
| `POSTGRES_PORT` | `5432` | TimescaleDB port (host-side: `55432`) |
| `POSTGRES_USER` | `nexus` | DB user |
| `POSTGRES_PASSWORD` | `nexus_dev_password` | DB password |
| `POSTGRES_DB` | `nexus` | DB name |
| `REDIS_HOST` | `redis` | Redis host |
| `REDIS_PORT` | `6379` | Redis port |
| `MLFLOW_TRACKING_URI` | `http://mlflow:5000` | MLflow server |
| `CRITIC_MODEL` | `gemini-3.5-flash-lite` | Pinned Gemini model for critic + eval |
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
pip install -r requirements-dev.txt

# Run all tests (tests select the mock LLM explicitly via NEXUS_LLM=mock)
pytest tests/unit/ tests/e2e/ -v

# Run the demo
docker compose up --build
python examples/crewai_agent/run_demo.py
```

PRs welcome. Please add tests for new functionality and run the full suite before opening a PR.

---

## License

MIT © Sankalp Rajeev
