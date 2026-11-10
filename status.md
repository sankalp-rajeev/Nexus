# Nexus — Improvement Plan Status

Tracks `Nexus Improvement Plan.md`. Legend: `[x]` done · `[ ]` pending · `[~]` in progress · ⚠️ issue/comment.
Scope agreed 2026-11-10: Phases 0 + 1, then stop for review. Spend cap Phase 1: $5 total (≤ $2 Gemini, ≤ $2 DeepSeek).

---

## Phase 0 — Credibility fixes  ·  branch `phase-0-credibility`

- [x] Explicit mock flag `NEXUS_LLM=mock`; missing key raises instead of silently mocking — `services/common/llm_config.py`. Healer no longer invents 0.5 scores (mock score labelled `{"mock": 0.5}`).
- [x] Pin current model — ⚠️ `gemini-2.0-flash` is no longer served (models.list, 2026-11-10); pinned `gemini-3.5-flash-lite`. Also updated `CRITIC_MODEL` in local `.env` (keys untouched).
- [x] CI + tests select the mock explicitly (`NEXUS_LLM: mock` in ci.yml, `tests/conftest.py`); 9 new tests in `tests/unit/common/test_llm_config.py`.
- [x] SDK: bare `@nexus.trace` fixed (used to return a wrapper instead of the result); `span(..., input=...)` now records input. 4 regression tests.
- [x] README + SDK README match the real API (`init`, `trace`, `span`, `start_span/end_span`, `flush`); dropped nonexistent `configure`/`record_span`/`start_trace`/LangChain integration and the empty `[langchain]`/`[crewai]` extras. Deleted the stale `sdk/dist/` build (gitignored) whose README advertised those APIs.
- [x] Quickstart + demo docstring → `pip install -e sdk/` (dist name stays `nexus-selfheal`, free on PyPI, not published).
- [x] Removed "under 90 seconds" from README / TECHNICAL_SUMMARY; README Healer section states its known limitations. ⚠️ TECHNICAL_SUMMARY.md is untracked (yours) — edited but not committed.
- [x] Classifier report regenerated from a real run (numbers reproduced exactly: P=1.000, R=0.473) with per-class counts + 95% Wilson CIs; CB/PD/LOOP marked "not yet evaluated on real traces".
- [x] Critic report → `docs/critic_smoke_test_report.md` "Pipeline Smoke Test (mock LLM)". ⚠️ Confirms the audit: 20/20 proposals were the generic fallback template (0/20 from the LLM path).
- [x] Every `docs/*report*.md` has a provider/model/mock header; enforced by `tests/unit/test_reporting_hygiene.py` (also checks result-file provenance and that RESULTS.md is fresh).
- [x] `RESULTS.md` generated from `results/*.json` by `scripts/build_results_md.py` (`services/common/results.py` stamps date, commit, dirty flag, provider, model, mock, seed; Wilson CIs).
- [x] Compose boot fixes: api Dockerfile CMD, Kafka/Postgres/Redis healthchecks + `service_healthy` deps + `restart: unless-stopped`, `.dockerignore`, critic image copies `services/common`. Verified: `docker compose up --build` brings up all 11 containers; collector /health ok (Kafka connected), API 200, dashboard 200.
- [x] Interim resume bullets written into TECHNICAL_SUMMARY.md (replacing the unbacked ones).
- [x] Full test suite (126) + ruff green; committed on `phase-0-credibility`.

## Phase 1 — NexusBench  ·  branch `phase-1-nexusbench`

- [ ] Provider layer: Gemini / DeepSeek / Ollama, with a cost ledger and hard per-provider caps.
- [ ] LangGraph agent with three task families: grounded QA, tool use, multi-step plan.
- [ ] Deterministic task checkers (exact or fuzzy answer, numeric tolerance, plan steps).
- [ ] Fault injectors + deterministic labels for 5 failure types + NORMAL.
- [ ] Dev/test split by task; SHA-256 manifest of the test set committed before any tuning.
- [ ] Generate about 60 traces per class (about 360) plus natural failures.
- [ ] Datasheet (`bench/DATASHEET.md`).
- [ ] Tests: generator determinism, manifest check in CI, checker unit tests.
- [ ] B1: 10% label spot check. ⚠️ Needs human hand-labels; I'll prepare the sample sheet, and you fill in agreement.
- [ ] Commit; stop for review.

## Phases 2–6

- [ ] Phase 2: detection on real traces (not started — waits for review)
- [ ] Phase 3: critic with real, applicable patches
- [ ] Phase 4: healing promotion gate
- [ ] Phase 5: real latency, throughput, cost
- [ ] Phase 6: replay demo, lite mode, OTel, PyPI

## Deferred bugs from the onboarding review (not in Phase 0/1 scope)

Heal loop ignores approve/reject · `psycopg2.extras` import missing in healer/db.py · no rollback in healer · patches mapped to the wrong agent · Redis channels with no publisher · `alerts`/`classifications` never written · WS snapshot datetime serialization · agent-health GROUP BY · trace sweep only runs when Kafka is idle · deprecated `google-generativeai`. Planned for Phases 3–4.
