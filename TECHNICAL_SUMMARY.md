# Nexus — Technical Summary

**An end-to-end LLMOps platform for observability and autonomous self-healing of multi-agent AI pipelines.**

Nexus closes the loop on agent failures: it observes every span an agent emits, detects failures in real time, diagnoses root causes with an LLM, automatically patches the agent's configuration, and re-evaluates the fix — all without human intervention.

```
OBSERVE → STREAM → DETECT → DIAGNOSE → PATCH → EVALUATE → OBSERVE
  SDK       Kafka   Classifier  Critic    Healer   DeepEval    (loop)
```

---

## What was built

A production-style microservice platform delivered across 7 phase-gated milestones, comprising **8 services**, a **React dashboard**, a **pip-installable SDK**, and a **CI/CD pipeline** — orchestrated with a single `docker compose up`.

### 1. Instrumentation SDK (`nexus_agent`, dist `nexus-selfheal`, not yet on PyPI)
- Zero-config, non-blocking, fail-silent Python SDK that instruments any agent framework (decorator, context-manager, manual, and LangChain-callback patterns).
- A downed collector never crashes or slows the host agent.

### 2. Trace Collector + Streaming
- FastAPI ingestion service validating spans with Pydantic and publishing to Kafka (`nexus.spans.raw`).
- An Assembler service buffers spans into complete traces using a TraceBuffer, persisting to TimescaleDB.

### 3. Two-Stage Failure Classifier
- **Stage 1 (rules):** deterministic detection of `LOOP_DETECTED` and `TOOL_MISFIRE`.
- **Stage 2 (ML):** an SVM over a **387-dimensional feature vector** — 384-dim MiniLM embeddings + PatchCore anomaly score + input/output divergence + a cross-encoder **NLI contradiction score** — classifying `HALLUCINATION`, `CONTEXT_BLEED`, and `PLAN_DRIFT`.
- Trained on synthetic traces, evaluated **out-of-distribution** on real HaluEval + ToolBench data via a source-stratified split. On 220 real traces: binary precision 1.000 at recall 0.473; HaluEval hallucination recall 0.033 (2/60); context bleed and plan drift not yet evaluated on real traces. Tool misfire is caught on 50/50 real ToolBench failures by the rules.

### 4. LLM Critic Agent
- A **LangGraph state machine** (root-cause → patch-proposer → validator, with a 2-retry loop and rule-based fallback) using a pinned Gemini model.
- Emits schema-validated `PatchProposal` records; a deterministic mock (selected explicitly with `NEXUS_LLM=mock`) keeps it testable offline. Real-model critic quality has not been measured yet; the mock smoke test produced the generic fallback template for 20/20 traces.

### 5. Autonomous Healer + Eval Loop
- 5-step workflow: notify (Slack) → apply patch to the Config Store → re-run the agent → score before/after with **DeepEval** (answer-relevancy + custom G-Eval task-completion) → log to **MLflow** → emit a real-time `HealthDiff` over Redis.
- Time-to-heal has not yet been measured on real runs (the earlier sub-90 s figure came from a mocked test). The healer currently re-runs only the same input, so before/after gains are not yet evidence of generalization.

### 6. Real-Time Dashboard
- **React 18 + TypeScript + Vite + Tailwind + Recharts** single-page app with a WebSocket feed (auto-reconnect + initial snapshot).
- Five live panels: TraceStream, FailureTimeline, CriticPanel (approve/reject), PatchHistory (before/after scores), and per-agent HealthScore rings.

### 7. Testing & CI/CD
- **107 deterministic unit + e2e tests** (no live API calls), plus a graceful-skip integration suite for Kafka/Postgres/Redis.
- **GitHub Actions** pipeline: ruff lint → mypy → pytest with branch coverage → Codecov, plus a containerized integration job.
- Core algorithmic modules covered **84–100%**.

---

## Architecture & stack

| Layer | Technology |
|---|---|
| Language / API | Python 3.11, FastAPI, Pydantic |
| Streaming / storage | Apache Kafka, TimescaleDB (PostgreSQL), Redis |
| ML / detection | sentence-transformers (MiniLM), scikit-learn (SVM), PatchCore, cross-encoder NLI |
| LLM / agents | Gemini (pinned model), LangGraph |
| Eval / tracking | DeepEval, MLflow |
| Frontend | React 18, TypeScript, Vite, Tailwind, Recharts |
| Infra / CI | Docker Compose (11 services), GitHub Actions, ruff, mypy, pytest |

---

## Engineering highlights

- **Honest, OOD evaluation:** deliberately trained on synthetic data and tested on real-world benchmarks to avoid inflated in-distribution metrics; reports precision and recall together and documents where the classifier fails on real data.
- **Resilience by default:** fail-silent SDK, graceful degradation across every external dependency (Redis, MLflow, NLI model, LLM), and deterministic mock providers so the whole system runs and tests offline.
- **Production hygiene:** phase-gated delivery, full CI/CD, branch coverage, containerized one-command bring-up.

---

## Resume bullets (interim — no unverified metrics)

Use these until real-run results exist in [RESULTS.md](RESULTS.md):

- Built an 11-service agent observability and self-healing platform: a Python SDK, Kafka trace pipeline, two-stage failure classifier, LangGraph critic that proposes structured config patches, and a healer that re-evaluates patches with DeepEval and logs to MLflow.
- Detected tool misfires and repetitive loops with rule-based checks (100/100 on ToolBench traces) and documented the semantic classifier's gaps on real data to scope the next version.
