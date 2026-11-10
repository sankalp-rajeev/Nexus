# Nexus — Improvement Plan Status

Tracks `Nexus Improvement Plan.md`. Legend: `[x]` done · `[ ]` pending · `[~]` in progress · ⚠️ issue/comment.
Scope agreed 2026-11-10: Phases 0 + 1, then stop for review. Spend cap Phase 1: $5 total (≤ $2 Gemini, ≤ $2 DeepSeek).

⚠️ **Gemini key is on the free tier: 20 requests/day per model** (429 `generate_content_free_tier_requests`, limit 20). The $4 credit isn't attached to this key's project. NexusBench was therefore generated with **DeepSeek (`deepseek-flash`, V4.1) + local Qwen (`qwen2.5:7b-instruct` via Ollama, RTX 4080)**. Gemini is reserved for the critic once billing is linked.

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

- [x] Provider layer `bench/llm.py`: Gemini / DeepSeek / Ollama over a JSON protocol; append-only response cache (`llm_cache.jsonl`, makes regeneration free + reproducible); cost ledger + hard per-provider caps checked before every call (worst case = max_tokens). Prices checked 2026-11-10; DeepSeek priced at peak rate (conservative); DeepSeek thinking disabled.
- [x] LangGraph planner→actor agent (`bench/agent.py`), instrumented with the Nexus SDK → genuine `CompleteTrace`s (planner span carries `plan_steps`; memory reads carry session/user IDs). Four families: qa 40, tool 30, plan 30, memory 40 (140 tasks) over a seeded **fictional** world (`bench/world.py`), so answers can't come from parametric memory.
- [x] Deterministic checkers (`bench/tasks.py`): numeric ±1.1% (min 0.02), normalised text match, and every required tool must have run successfully.
- [x] Fault injectors (`bench/tools.py`) + rule-based labeler (`bench/labeler.py`); plus `OTHER_FAILURE` (failed, none of the 5 types) and `RUN_ERROR`. Labels are recomputable from traces alone (`bench/relabel.py`, CI-checked). ⚠️ Pilot caught two labeler bugs, both fixed: borrowed facts from another company's doc counted as "supported"; abstention regex missed "does not mention".
- [x] Dev/test split by task (memory tasks grouped by user); `manifest.sha256` (digest `fa191c6d7630d01f…`, 357 test traces) committed with the data before any tuning; CI test fails if it changes.
- [x] Generated 716 traces: NORMAL 256, HALLUCINATION 60, CONTEXT_BLEED 60, LOOP 61, MISFIRE 59, PLAN_DRIFT 46, OTHER_FAILURE 174. ⚠️ PLAN_DRIFT hit the 150-attempt cap at 46 (DeepSeek ignores the injection 75/75). ⚠️ No natural failures: all 140 uninjected runs passed. ⚠️ Classes are mostly single-model (hallucination + misfire = DeepSeek, drift = Qwen), so Phase 2 must report per model. Spend: $0.283 DeepSeek, $0.002 Gemini.
- [x] Datasheet `bench/DATASHEET.md` (mechanisms, label rules, splits, stats, limitations).
- [x] Tests (25): world/task/split/attempt-order determinism, scripted-LLM agent determinism, checkers, every fault, every label rule, relabel-from-trace equality, manifest + labels integrity on the committed data. Full suite 151 passed.
- [~] B1: blind 72-run stratified sample ready in `bench/spotcheck/` (`sample.md` + `sheet.csv`). ⚠️ **Needs you:** fill `human_label` in sheet.csv without opening key.json, then `python -m bench.spotcheck --score`.
- [x] Committed on `phase-1-nexusbench`; **stopped for review**.

## Phases 2–6

- [ ] Phase 2: detection on real traces (not started — waits for review)
- [ ] Phase 3: critic with real, applicable patches
- [ ] Phase 4: healing promotion gate
- [ ] Phase 5: real latency, throughput, cost
- [ ] Phase 6: replay demo, lite mode, OTel, PyPI

## Deferred bugs from the onboarding review (not in Phase 0/1 scope)

Heal loop ignores approve/reject · `psycopg2.extras` import missing in healer/db.py · no rollback in healer · patches mapped to the wrong agent · Redis channels with no publisher · `alerts`/`classifications` never written · WS snapshot datetime serialization · agent-health GROUP BY · trace sweep only runs when Kafka is idle · deprecated `google-generativeai`. Planned for Phases 3–4.
