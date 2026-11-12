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

## Phase 2 — pre-registration  ·  branch `phase-2` (local only), tag `phase2-prereg`

- [x] Detector input contract `bench/detector_view.py`. Strips trace_id (→ opaque view_id), source, task_id, family, model/provider/cached, memory item_sessions/item_users; per-trace pseudonyms for canary tokens and the drift target. CI test over all 716 traces. ⚠️ Residual injection text kept (the agent really saw it): drift note in 150 views (46 PD / 104 NORMAL), loop message in 72, misfire 422 error in 150. Detector code may not hardcode these strings (CI).
- [x] `reports/phase2/preregistration.md`: label vs detector separation; LOOP and MISFIRE marked rule-defined, not headline. ⚠️ CONTEXT_BLEED's structural signal equals its label *by construction* on dev (30/30, 0 FP): no benign multi-record memory reads exist. Pre-registered a secondary headline over H+PD; option (c) (regenerate the benchmark with benign multi-note users) is open for your decision.
- [x] Pre-registered: OTHER_FAILURE rule, headline macro (H, CB, PD), per-model with single-model classes listed, target R ≥ 0.80 at P ≥ 0.90, dev-only operating point, Clopper-Pearson, test scored once (sealed in code). No natural failures and PD n=46 are noted.
- [x] Dev baseline (shipped SVM through the view): degenerate. It predicts HALLUCINATION for every non-rule trace. H R=0.93 at P=0.14; CB 0/30; PD 0/20; MISFIRE 27/27 (P 1.00); LOOP 33/33 (P 0.92). Headline macro 0.311, secondary 0.467.
- [x] Committed and tagged `phase2-prereg`. **Stopped.** The test split hasn't been touched.

## Phase 2 — Amendment 1 (CONTEXT_BLEED made non-trivial)  ·  branch `phase-2`, tag `phase2-prereg-v2`

- [x] Amendment written and committed before any code (`8207df3`).
- [x] Memory v2 (`bench/memory.py`): 1–4 own notes per user plus shared team notes; records carry no owner fields; bleed mixes 1–2 foreign records in; label comes from the ownership registry. Separate RNG stream, so tasks, gold answers and splits are unchanged.
- [x] Regenerated only the 257 memory-reading runs (459 lines byte-identical); CB still 60 effective; DeepSeek spend $0.089 (cap $1.00). Relabel check 0 diffs; leak and integrity tests pass (167 + RESULTS freshness).
- [x] New manifest `45c4040a…`; new tag `phase2-prereg-v2`; `phase2-prereg` untouched.
- [x] Separability gate (dev): **not tripped.** Record count > 1 gives P 0.435 / R 1.00. ⚠️ "≥ 2 Account-tier records" gives P 1.00 / R 0.50: registered as the trivial reference a CB detector must beat.
- [x] Dev baseline v2: still degenerate (headline 0.311, secondary 0.467).
- [x] ⚠️ Side effects: PLAN_DRIFT 46 → 55; TOOL_MISFIRE now 61 DeepSeek + 11 Qwen; NORMAL 256 → 247. **Stopped.**
- [x] `DECISIONS.md` started (interview-ready "why" log).

## Phase 2 — detectors  ·  branch `phase-2`, tags `phase2-detectors-frozen`, `phase2-test-scored`

- [x] Detectors in `services/detectors/` (view-only; CI injection-string ban passes): NLI claim grounding (DeBERTa-v3), profile-consistency bleed, id-provenance drift, call-window rules. Gemini judge kept as a separate variant.
- [x] Dev tuning (pre-registered rule + midpoint tie-break). Dev headline macro 0.922 (baseline 0.311), secondary 1.000. ⚠️ HALLUCINATION misses the P ≥ 0.90 floor on dev (0.857): 4 of 5 FPs are a label defect (±1.1% tolerance accepts years ±22 off). Logged as a deviation; labels unchanged; sensitivity criterion registered.
- [x] CONTEXT_BLEED dev R 0.767 at P 1.00, vs the reference rule's R 0.50.
- [x] Misfire Qwen gap fixed generally (window in tool calls): 6/6 on dev.
- [x] Frozen (`phase2-detectors-frozen`).
- [x] One-time test scoring at `d293ab6` (frozen) → D1, D2, D4, D5, D6. Headline macro recall **0.956** (SVM 0.289), secondary **1.000**.
  - CB P 1.00 R 0.867 (reference rule R 0.800 on test).
  - PD 31/31.
  - Rules 100%.
  - ⚠️ H R 1.00 at **P 0.811**: misses the 0.90 target; 6 of 7 FPs meet the registered year-tolerance label-defect criterion.
  - FA 56 per 1,000 NORMAL (SVM 1,000).
  - D4: HaluEval P 0.546 R 0.783 (v3: 1.0 / 0.033), ToolBench 1.0 / 1.0.
  - D6: p50 0.4 ms, p95 674 ms; SDK 0.01 ms/call.
  - Spend: Gemini judge $0.029. Tagged `phase2-test-scored`. **Stopped.**

## Phase 2 — follow-ups  ·  tag `bench-v1.1`

- [x] Judge–NLI independence audit. ⚠️ They share `retrieved_context()` and the no-documents gate, so they are not independent; the claim was removed (D41, D43). Dev: 0 disagreements in 96. Test per-trace predictions were never persisted (D45).
- [x] Entity-absence rule alone (dev): R 1.00, P 0.857, the same as the full NLI detector. Disclosure added to the Phase 2 reports (D44).
- [x] NexusBench v1.1 (announced first in `bench/REVISIONS.md`): per-field numeric checker; 11 labels changed; new manifest `0f664774…`. ⚠️ The kg rule was corrected before tagging (D47).
- [x] v1.1 sensitivity (exact from stored predictions): test H P 0.811 → 0.973, FA/1000 56 → 8.5, headline 0.956 unchanged.
- [x] `bench/llm.py` Gemini 3.x fix + tests + live check (D49).
- [x] `data/phase2/` untracked; `results/` is the only tracked output (D48).
- [x] Secret scan, then pushed `phase-2` + Phase 2 tags + `bench-v1.1`.

## Phases 3–6

- [ ] Phase 3 critic (Codex on `phase-3-critic`; not touched here)
- [ ] Phase 3: critic with real, applicable patches
- [x] Phase 4: healing promotion gate (test scored under A3, D76; `reports/phase4/test_scoring.md`)
- [ ] Phase 5: real latency, throughput, cost
- [ ] Phase 6: replay demo, lite mode, OTel, PyPI
  - [ ] **Docker validation (found 2026-11-11, not debugged):** after a Docker Desktop restart the
    `nexus-*` service containers auto-start (restart policy), and `nexus-nexus-critic-1` sits in a
    restart loop (`Restarting (1)`). Phase 4 test runs did not use the stack (`docker compose stop`
    before the test agent runs; the heal harness needs no container). Check the critic image's
    startup and the restart policy as part of Phase 6 Docker validation.

## Deferred bugs from the onboarding review (not in Phase 0/1 scope)

Heal loop ignores approve/reject · `psycopg2.extras` import missing in healer/db.py · no rollback in healer · patches mapped to the wrong agent · Redis channels with no publisher · `alerts`/`classifications` never written · WS snapshot datetime serialization · agent-health GROUP BY · trace sweep only runs when Kafka is idle · deprecated `google-generativeai`. Planned for Phases 3–4.
