# NEXUS — Build Context Log

> Single source of truth for build progress. Phrase-based. Updated per task/subtask.
> Legend: ✅ done · ☐ pending · 🔄 in progress · ⚠️ issue/needs change · ❌ failed

Repo: `c:\Umich\Projects\Nexus` · SDLC: Waterfall (phase-gated) · Mode: pause for approval at each gate

---

## PHASE 1 — Requirements & Design

Gate: architecture finalized · schemas locked · repo scaffolded · pause for approval

### Setup
- ✅ git init — empty repo initialized
- ✅ Python venv — `.venv`, Python 3.11.14
- ✅ context.md created

### Tasks
- ✅ Scaffold repo dir tree (Section 6.1) — 26 dirs; .gitkeep in empties
- ✅ Pydantic schemas → `sdk/nexus_agent/models.py` (Section 13.1 + locked shared models)
- ✅ `infra/init/postgres_init.sql` — all 7 CREATE TABLEs (Section 13.2, verbatim)
- ✅ `docker-compose.yml` — all 11 services declared (app Dockerfiles = TODO per gate)
- ✅ `docs/architecture.md` — ASCII diagram + service inventory + Kafka topics
- ✅ `docs/schemas.md` — all Pydantic models documented
- ✅ `docs/api_contracts.md` — all FastAPI route specs (Section 14)
- ✅ README stub · MIT LICENSE · .gitignore · .env.example · sdk/pyproject.toml

### Phase 1 Exit Criteria (Section 6.2)
- ✅ public repo + stub README + MIT LICENSE — pushed to github.com:sankalp-rajeev/Nexus (origin via github-personal alias)
- ✅ all Section 13 schemas in `models.py` (import-verified in venv)
- ✅ docker-compose declares 11 services (kafka, postgres, redis, mlflow real; 7 app services build-context declared)
- ✅ postgres_init.sql has all CREATE TABLEs
- ✅ architecture ASCII diagram committed (staged)
- ✅ API contracts committed (staged)

### Logs
- env: Windows PowerShell, no `py` launcher (use `python` / `.venv\Scripts\python.exe`)
- venv create took ~20s — normal
- pydantic 2.x installed in venv; `import nexus_agent` + all 8 key models OK
- git: LF→CRLF warnings on add (cosmetic, Windows checkout) — consider `.gitattributes` later
- NOT committed yet — awaiting instruction (commit only when asked)
- pyproject sdk license switched `file`→`text="MIT"` to avoid needing sdk/LICENSE at build

### Phase 1 = COMPLETE (pending gate approval + manual GitHub push)

---

## PHASE 2 — Trace Collector SDK

Gate: SDK pip-installable · collector running · spans flowing into Kafka

### Tasks
- ✅ SDK `config.py` — NexusConfig dataclass (validation, capture limits, exporter tuning)
- ✅ SDK `exporters/http.py` — HttpExporter (fail-silent + throttled failure warnings)
- ✅ SDK `exporters/stdout.py` — debug exporter
- ✅ SDK `client.py` — bg queue+worker thread, contextvar trace propagation, build/record/flush/shutdown
- ✅ SDK `decorators.py` — @trace (sync+async), span() ctx mgr, start/end_span; user exceptions recorded + re-raised
- ✅ SDK `__init__.py` — public API: init/get_client/trace/span/start_span/end_span/flush/shutdown
- ✅ Collector `main.py` + `routes/spans.py` + `kafka_producer.py` + Dockerfile (context=repo root)
- ✅ Unit tests: 31 (models 9, client 10, decorators 12) — exceeds min 23
- ✅ `examples/raw_llm_call/run_demo.py` — emits 10 spans/run
- ✅ `examples/raw_llm_call/benchmark_overhead.py`
- ✅ Integration test `tests/integration/test_collector_kafka.py` — 5 tests, auto-skips w/o broker

### Phase 2 Exit Criteria (7.6)
- ✅ `pip install -e ./sdk` clean (exit 0)
- ✅ `@nexus.trace` non-blocking, overhead **0.008 ms/call** (target <5ms) via timeit
- ✅ collector starts, `GET /health` → `{"status":"ok","kafka_connected":true}` w/ live Kafka (degraded w/o)
- ✅ demo emits 10 spans → confirmed in topic `nexus.spans.raw` (consumed & counted)
- ✅ fail-silent when collector unreachable (unit + manual: ConnectTimeout drops, no raise)
- ✅ `pytest tests/unit/sdk/` passes (31)

### Test Results
- unit: 31 passed (0.58s)
- integration: 5 passed (vs live Apache Kafka on localhost:29092)
- full suite: 36 passed
- benchmark: baseline 0.04us, instrumented 8.50us, overhead 0.008ms → PASS

### Logs — what worked / failed / changed
- ⚠️ DEVIATION: `bitnami/kafka:3.6` discontinued (Bitnami pulled free public tags 2025) → switched to `apache/kafka:3.7.0` KRaft. Updated docker-compose kafka service env (KAFKA_* not KAFKA_CFG_*).
- ⚠️ Added dual Kafka listeners: PLAINTEXT `kafka:9092` (containers) + EXTERNAL `localhost:29092` (host tools/tests). Host integration runs with KAFKA_BOOTSTRAP_SERVERS=localhost:29092.
- ⚠️ collector Dockerfile build context = repo root (to bundle SDK); updated compose `nexus-collector.build`
- ❌→✅ demo crashed on Unicode arrow `→` print (Windows cp1252 console) → changed to `->`
- ⚠️ fail-silent flooded logs (1 warn/dropped batch) → added throttle in HttpExporter (warn 1st + every 100th, reset on success)
- Docker Desktop was off; started it, daemon ready in ~35s
- env: set KAFKA_BOOTSTRAP_SERVERS=localhost:29092 in shell for host-side collector + tests
- kafka container left running (nexus-kafka-1) for further use

### Phase 2 = COMPLETE (all exit criteria green, verified against live Kafka)

## PHASE 3 — Failure Classifier
- ☐ not started

## PHASE 4 — LLM Critic Agent
- ☐ not started

## PHASE 5 — Auto-Healer & Eval Loop
- ☐ not started

## PHASE 6 — Dashboard & OSS Release
- ☐ not started

## PHASE 7 — Testing & QA (parallel to 2–6)
- ☐ not started

---

## Test Results Log
- (none yet)

## Decisions / Deviations
- models.py: locking ALL Pydantic models (Span, SpanBatch, FailureType, PatchType, PatchProposal, Alert, Classification, CompleteTrace, HealthDiff, EvalResult) in one file per Phase 1 "all schemas locked" gate, not just Section 13.1
