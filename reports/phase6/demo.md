# Phase 6, step 6.5a-local: the DEV replay demo

Status: built and checked locally; **not deployed**. No Vercel command was run, no tag was created, nothing was
published, no provider was called (`provenance.llm_calls = 0`), and the critic and healer stayed stopped. The run
was unattended, so every judgement call is listed under "Decisions made unattended".

The replay is a static page (`dashboard/public/replay.json` plus the Vite replay build). It shows recorded DEV
evidence only: detector verdicts, the critic's real patch text, each gate check and the gate's decision, plus a
headline panel in which every number links to the file it was parsed from. There is no backend, no key and no
model call behind it.

## 1. Images rebuilt from HEAD

All images were rebuilt with `docker compose build` (nexus-phase6) and `docker compose -f docker-compose.lite.yml build`
(nexus-lite) from `a759311061cf337621e2a4fa71dd70b18c841d49` (branch `phase-6-demo`). The classifier image bakes its
NLI model at build time, which is why that build downloads. The images carry no revision label, so the commit is
recorded here and in the scratch `build_commit.txt`, not inside the images.

| Image | ID |
|---|---|
| `nexus-phase6-nexus-collector:latest` | `sha256:c3a54433bcbdda42c81190130d565f03d5783b8e890d1d8e2cd897e496c77de3` |
| `nexus-phase6-nexus-assembler:latest` | `sha256:cda2a9ef26307861af476b48b962a461acdc485af18be085593db881b2092eea` |
| `nexus-phase6-nexus-classifier:latest` | `sha256:0099075328fb2f0e3128467f5809b0eebd93e6957b2dad505c645c46ef5868fc` |
| `nexus-phase6-nexus-critic:latest` | `sha256:05e249550df0065efbf5213f743a6630b1c4b9f64d0cad182b7e2f545df4a79e` |
| `nexus-phase6-nexus-healer:latest` | `sha256:194d2297ede730e34e1d4427bb3611ee7a0628e656999727800e84bfebc3e0b4` |
| `nexus-phase6-nexus-api:latest` | `sha256:e9296d7224dc7297dcd3141105e9e94be8d024a2ee5c0f01ad86fd57b7e26e01` |
| `nexus-phase6-nexus-dashboard:latest` | `sha256:9868ad9b928b94b2200ce0a67fdc1923ef6729b829a6149f0f16343fb900c506` |
| `nexus-lite-nexus-lite:latest` | `sha256:a4e1d6456c54254da1bbbd1c5ae8c29a1345a2c8f7d90f2fec59265ca2aa678f` |

Notes: the collector build was a full cache hit (every layer, including `COPY services/collector`, matched the HEAD
sources), so that image is content-identical to a fresh build even though its creation time is earlier. The
dashboard image was rebuilt a second time after the replay UI changes, from the working tree on top of
`a759311`; it is the only image whose context differs from the commit. Older `61d-5779aac` tags are untouched.

## 2. Quick re-validation on the rebuilt images

Scratch scripts (not committed): `data/phase6/runs/scratch/overnight/validate_stack.py`, results in `stack-validation.json`
and `lite/lite-result.json`.

- **Full stack:** kafka, postgres, redis, mlflow, collector, assembler, classifier, api and dashboard started with
  `--no-build`, provider keys blanked by the compose override, critic and healer not started. All containers running, all
  health checks healthy, zero restarts. Cold start 38.5 s (first run) and 47.2 s (re-run with the final dashboard image).
- **Synthetic trace:** the fictional loop fixture, with the boolean `nexus.synthetic` on every span and a fresh trace id,
  was accepted (4 spans) and classified `LOOP_DETECTED` (confidence 1.0). No record for it appeared on `nexus.alerts`,
  and the classifier `/health` reported `synthetic_suppressed` rising by exactly 1.
- **Detector default:** classifier `/health` shows `classifier: detectors`, `frozen_tag: phase2-detectors-frozen`,
  variant `pipeline (no LLM judge)`, thresholds from `services/detectors/thresholds.json` (HALLUCINATION 0.5034,
  CONTEXT_BLEED 1.0, PLAN_DRIFT `ungrounded_any_source`).
- **Running containers use the rebuilt images:** the running container image ids equal the ids above for collector,
  assembler, classifier, api and dashboard.
- **Lite:** `scripts/phase6/check_lite_host_ingress.py --image nexus-lite-nexus-lite:latest --hold-seconds 15`: PASS. Cold
  start to healthy host HTTP on port 18000 in 13.95 s, a 15 s idle hold with zero restarts, then the fictional trace
  produced one alert (`LOOP_DETECTED`) and one `generic_fallback_no_llm` proposal.
- **Stopped, not removed:** both stacks were stopped with `stop`; nothing was deleted (the lite check, as designed,
  creates a new uniquely named container and volume per run, and these were left in place with the earlier ones).

The idle hold was shortened from the script's 300 s default to 15 s because this was a "quick" re-validation.

## 3. Replay data sources: read-only inventory

**Heals** (`C:\Umich\Projects\nexus-phase5\data\phase5\runs\`, read only; nothing raw is copied into git):

- Main run: 100 DEV heals (`records/heal-NNN.json`, `items/heal-NNN.json`), DeepSeek critic, concurrency 2. Their
  concatenated sha256 equals `methodology.source_records_sha256` in `results/phase5/heal_latency_cost.json`, and the
  per-class gate decisions equal that file's `gate_decisions.by_detector_failure_class` (72 promoted, 28 rejected).
- Side run `gemini_side/`: 20 heals with a Gemini critic; each decision equals `results/phase5/gemini_side.json#paired_decisions`.
- Each record holds the critic's real proposal (explanation, root-cause analysis, patch type, target, full replacement
  text, notes, provenance and cost), the gate result (`check1_own_task`, `check2_heldout` with both rates and n,
  `check3_no_regression` with the broken task list), the per-stage timings and the decision. Fast-exit heals
  (`no_patch`, or a detector `NORMAL`) have their gate stages marked `skipped`.
- Not in the records: a unified diff. The exporter computes one from the recorded patch and the benchmark agent's
  system prompt it replaced, and labels it as derived.
- Outcome inventory, main run: promoted HALLUCINATION 38, LOOP 23, TOOL_MISFIRE 11; fixed its own task but blocked at
  the held-out check 4; blocked by the regression check 6; no usable patch 14 (TOOL_MISFIRE 7, CONTEXT_BLEED 7);
  detector said NORMAL on a real fault 4. **No PLAN_DRIFT heal exists** and **none failed the repair check**; the
  repair-check examples are in the Gemini side run (5).

**Traces:** DEV only, through `services/critic/dev_adapter.py` (`dev_labels`, `dev_traces`) and the detector view
(`bench/detector_view.py`), with verdicts from `results/phase2_dev_predictions.json`. The live classifier reproduces
those predictions on all 359 DEV traces (`results/phase6/live_detectors_equivalence_with_final.json`).

**Headline numbers:** parsed from committed `RESULTS.md` rows and `results/phase5/*.json`, `results/phase6/*.json`.
No `*_test*` results file or `reports/phase4/test/` is opened. The TEST rows in `RESULTS.md` (D1, A3) are read as text
and labelled "TEST, as reported in RESULTS.md".

## 4. Selection rule

The rule lives in `dashboard/scripts/export_replay.py` (`HEAL_RULES`, `rule_selected_trace_ids`) and is copied into
`replay.json` at `provenance.selection_rule`. It was fixed in code from the inventory above before the first export, and
selection uses ids and outcome categories only, never the quality of a patch or the look of a trace.

- **Heals:** for each outcome rule below, in this order, the lowest-numbered heal of the named run that matches. 9 heals.
- **Traces:** for each predicted class (NORMAL, HALLUCINATION, TOOL_MISFIRE, CONTEXT_BLEED, PLAN_DRIFT, LOOP_DETECTED),
  the first 2 DEV trace ids in ascending order among the detector's DEV predictions (12), plus the trace of every
  selected heal (9 more, none overlapping the first 12: 21 DEV traces in all).

| Rule | Run | Matches | Selected | Task | Gate (repair / held-out / regression) | Decision |
|---|---|---|---|---|---|---|
| promoted_hallucination | main | 38 | heal-002 | qa-013 | pass / pass / pass | promoted |
| promoted_loop | main | 23 | heal-001 | plan-001 | pass / pass / pass | promoted |
| promoted_tool_misfire | main | 11 | heal-003 | mem-033 | pass / pass / pass | promoted |
| blocked_at_heldout (fixed its own task, blocked) | main | 4 | heal-010 | mem-016 | pass / **fail** / pass | rejected |
| blocked_by_regression (fixed its own task, broke a passing task) | main | 6 | heal-043 | mem-003 | pass / pass / **fail** | rejected |
| rejected_at_repair_check | gemini side row | 5 | heal-005 | qa-021 | **fail** / fail / pass | rejected |
| no_patch_tool_misfire | main | 7 | heal-007 | plan-023 | skipped | rejected before the gate |
| no_patch_context_bleed | main | 7 | heal-020 | mem-027 | skipped | rejected before the gate |
| detector_missed (NORMAL on a real fault, no critic call) | main | 4 | heal-022 | mem-031 | skipped | rejected, no critic call |

Failure classes covered by heals: HALLUCINATION, LOOP_DETECTED, TOOL_MISFIRE, CONTEXT_BLEED and a detector miss.
PLAN_DRIFT has no heal in the Phase 5 DEV runs; it appears only in the trace list.

Traces shown (all DEV): `nb-006eabeeb08527bf`, `nb-03ae6899fd6c6a8e` (NORMAL; the second is a DEV `OTHER_FAILURE`
the detectors do not score), `nb-00df3914aa55a84b`, `nb-1a77c36c02eae22b` (LOOP_DETECTED), `nb-028d21f755673a0b`,
`nb-13f328949ad89635` (HALLUCINATION), `nb-02d9c47d716be568`, `nb-150f303f104518d6` (TOOL_MISFIRE),
`nb-07e4c8d981075429`, `nb-1906cb9e17860106` (CONTEXT_BLEED), `nb-067ba8aa61527287`, `nb-0ad135977c018288`
(PLAN_DRIFT), plus the nine heal traces (`nb-9990dbe1533e57cd`, `nb-e23b5527665ae3b1`, `nb-31dac53a3505bcf7`,
`nb-d718182cfb24a4e7`, `nb-7eb8a1e6858b0c7a`, `nb-429f92c0ad1bc6bb`, `nb-d504c2945ab3cedf`, `nb-e8c06c96e7319cb3`,
`nb-bf15edea32672fd8`). One shown trace (`nb-bf15edea32672fd8`) is a real miss: the detector said NORMAL, the DEV label is
CONTEXT_BLEED. It is shown as it is.

## 5. What is shown

`dashboard/public/replay.json`: schema version 2, **383,183 bytes** (about 374 KiB; 9 heals, 21 traces).

- **Heals tab:** a picker for the 9 heals and, for the chosen one, a six-step timeline: Detect, Propose, Repair
  check, Held-out check, Regression check, Decision (each with its recorded outcome and stage time). Under it: the
  decision box with the reason; the detector verdict with the evidence span; the critic's patch (explanation, root
  cause, derived diff, full patched prompt, the critic's own estimated impact marked as a claim, validation notes, tokens,
  latency and cost); each gate check with its rule and recorded facts; and the trace itself, with the evidence span and
  the span the critic cited marked.
- **Traces tab:** the 21 DEV traces with verdict beside the DEV label, and the spans.
- **Headline numbers tab:** 14 numbers in three groups (detection, healing, speed and cost). Each shows a scope pill
  (DEV or TEST) and a link to its source file at the exported commit, with the row or JSON path.
- **Provenance tab:** the data statement "DEV data; TEST numbers shown only as already reported in RESULTS.md", the commit,
  the selection rule and table, and the git blob id of every source file.
- **Guard:** `assert_publishable` fails the export on any `placeholder`, `mock`, `illustrative` or `excerpt_only` marker in a
  key or value; `vite.config.ts` re-checks the file at build time (Node, no Python) and refuses a missing file, a non-DEV
  file or marker text.

## 6. Build and tests

- `npm ci` (done), `npm run build` (tsc + Vite, passes) and `npm run build:replay` (passes; the replay build no longer runs
  Python, it only verifies `replay.json`). `npm run export:replay` is the manual step that regenerates the file.
- `npm run test:replay`: 7 of 7 pass (loader accepts schema 2 and rejects TEST/old/404; six stages in order with the
  recorded outcomes for all 9 heals; heal view contents; every headline number has a source link; provenance and
  traces render; the shipped file has no `mock`/`placeholder`; read-only critic panel has no controls).
- Python: `tests/unit/collector/test_replay_export.py` (rewritten, 27 tests) calls `verify_committed`.

## 7. Local check and screenshots

The replay build was served with `vite preview` on `127.0.0.1:4173` and driven with headless Edge over CDP
(`data/phase6/runs/scratch/overnight/shoot.mjs`). Result in `data/phase6/runs/scratch/demo/console-check.json`: **no console
errors or warnings, no failed or non-200 requests, no request leaving localhost, no horizontal overflow at 390 px**. (A
favicon 404 appeared in the first pass; `dashboard/index.html` now has an inline `data:` icon.)

Saved under `data/phase6/runs/scratch/demo/` (not committed; 1440 px desktop and 390 px mobile, full page):

- `desktop-heals-promoted.png`, `mobile-heals-promoted.png` (heal-002)
- `desktop-heals-regression-blocked.png`, `mobile-heals-regression-blocked.png` (heal-043)
- `desktop-heals-no-patch-detector-normal.png`, `mobile-heals-no-patch-detector-normal.png` (heal-022)
- `desktop-traces.png`, `mobile-traces.png`
- `desktop-headline-numbers.png`, `mobile-headline-numbers.png`
- `desktop-provenance.png`, `mobile-provenance.png`

## 8. CI check

`verify_committed` (in the exporter, also `python dashboard/scripts/export_replay.py --verify`) and the tests in
`tests/unit/collector/test_replay_export.py` fail if `replay.json`:

- is missing;
- contains placeholder or mock content (guard, including keys);
- is not a read-only DEV schema-2 replay;
- is stale: any of the 15 source files has a different git blob id from `provenance.sources`; the rule-selected trace ids,
  the trace blocks, or the headline numbers no longer re-derive from the DEV adapter, the predictions and the committed
  results; the heal provenance (record hash, per-class decisions) differs from `heal_latency_cost.json`; or a Gemini heal's
  decision differs from `gemini_side.json`;
- has a heal whose decision disagrees with its three check outcomes.

`provenance.generated_from_commit` cannot equal HEAD (the file is committed after the commit it was built from). It is
checked to exist when history is available (skipped on shallow CI clones); staleness is judged by the blob ids.

## 9. Known limits

- The raw Phase 5 runs are outside the repository, so CI cannot re-derive the heal bodies (critic text, check
  numbers). CI verifies everything else and the heal bookkeeping against committed results; the full check is
  `export_replay.py --check` on a machine that has `nexus-phase5` (it passed here).
- Evidence location is a deterministic heuristic over the verdict, not a detector attribution (said on the page).
- The page shows the detector view of each trace (what the detectors and critic were given: canary pseudonyms, stripped
  fields), not the raw benchmark trace. Long texts are clipped (1,500 characters; the page says so).
- The repair-check example is a Gemini side-row heal, because no heal in the 100-heal main run failed the repair check.
- No PLAN_DRIFT heal exists in the DEV runs.
- The critic's "estimated impact" is its own claim, marked as such. The unified diff is derived, not recorded.
- Frozen `scripts/phase5/sdk_overhead*.py` reference pre-rename paths; reproduce them at commit `75771ab` (unchanged from before).
- The dashboard node tests are not in CI (CI has no Node job and `.github/` was left alone); the Python guard is.
- The compose services without a Docker health check (mlflow, collector, assembler, api, dashboard) were verified through
  running state plus HTTP probes (collector, api, classifier via `docker exec`, dashboard, mlflow).
- The classifier has no published host port; its health was read through `docker exec`.

## 10. Decisions made unattended

1. The 100-heal main run has no repair-check failure, so I took that category from the Gemini side run and labelled it
   everywhere ("separate Gemini critic side row"). The alternative, omitting the category, would have hidden a gate outcome.
2. Used 9 heals (inside the 8-12 range) rather than padding to 12 with near-duplicate categories.
3. Showed the detector view (not the raw trace) and clipped long strings, to keep the file small and avoid exposing fields
   the detectors never see.
4. Included the two TEST numbers that `RESULTS.md` already reports (D1, A3), parsed as text and scoped "TEST", as the task
   allowed. No TEST file or trace was opened.
5. Shortened the lite idle hold to 15 s.
6. The collector image was not rebuilt with `--no-cache`: all its layers were cache hits keyed on content, so it equals a
   fresh build of HEAD. The other images likewise reuse cached dependency layers (as the original builds did).
7. Rebuilt the dashboard image from the working tree after the UI changes (needed so the image matches the committed UI),
   then re-ran the stack validation on it.
8. The replay build now verifies instead of regenerating `replay.json`: the exporter needs the outside-the-repo Phase 5 runs,
   and Vercel's build machine does not have them. Regeneration is a manual, reviewed step.
9. Added only a Python CI test, not a Node or workflow step (leaves `.github/` untouched). Because tests changed, I wait for CI.
10. Kept `CriticPanel`'s read-only mode (the live dashboard uses the component) and only changed its caption; the replay no
    longer uses it.
11. Added a `data:` favicon to `dashboard/index.html` to remove the only console error (a favicon 404 on the preview server).

## 11. Next steps for the morning

1. Review the screenshots in `data/phase6/runs/scratch/demo/` and click through `npm run build:replay` then `npx vite preview` in `dashboard/`.
2. This step pushes `phase-6-demo` once at the end; check the CI result in the report, then merge as usual.
3. Vercel (needs you, not run here): from `dashboard/`, `vercel link` (new project, root directory `dashboard`), confirm the
   project uses `vercel.json` (install `npm ci`, build `npm run build:replay`, output `dist`; Git deployment is disabled).
4. Preview deploy only: `vercel deploy` (no `--prod`), open the preview URL and re-run the screenshot script against it
   (change `URL` in `shoot.mjs`).
5. Production deploy and the PyPI `pypi` environment fixes stay separate steps that need your go-ahead.
