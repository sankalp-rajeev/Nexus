# Nexus

**Production AI health monitor and self-healing platform for multi-agent systems.**

Nexus is the first open-source LLMOps platform to close the loop from production
observation to automated remediation. It instruments any LangChain, CrewAI,
LangGraph, or raw LLM app via a zero-config Python SDK, then detects, diagnoses,
and patches failures — and re-evaluates the fix.

```
OBSERVE (SDK) → STREAM (Kafka) → DETECT (Classifier) → DIAGNOSE (Critic) → PATCH (Healer) → EVALUATE (Eval Loop) → OBSERVE
```

No tool in 2026 closes this loop. LangSmith and Langfuse stop at tracing.
DeepEval stops at offline evaluation. Nexus connects production observation
directly to automated remediation.

## Status

🚧 Under active development (Waterfall, phase-gated). **Phase 1 — Requirements
& Design** complete: repo scaffolded, schemas locked, docker-compose skeleton,
docs.

See [`context.md`](./context.md) for live build progress.

## Quickstart (target, lands in Phase 6)

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

## Documentation

- [Architecture](./docs/architecture.md)
- [Schemas](./docs/schemas.md)
- [API Contracts](./docs/api_contracts.md)

## License

[MIT](./LICENSE)
