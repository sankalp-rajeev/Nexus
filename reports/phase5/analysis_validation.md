# Phase 5 validation

At the Parts A/B checkpoint, both parts completed without additional API spend. The read-only
provider ledger had 29,785 attempts, $7.24443270 ledger and $3.158843631 provider
usage-priced cost before and after L4. It was not reset or modified.

Part A reads only the 100 registered DEV occurrence records and their local
actor/critic ledgers. All 100 reconcile to SQLite; smoke is separated from the
100-heal mean/median endpoints. Three analysis tests cover deterministic bootstrap
quantiles, stage-based grouping and skipped-stage denominators. The hourly chart
was rendered and visually checked.

Part B was not started until amendment 1 was committed. The user's recorded-
response clarification was committed as `ce858c7`, and the recovery-only barrier
clarification as `bf38665`, before measurements. The exact first 20 manifest
occurrences were used, with 113 planner/actor steps per pass, two discarded warm-up
passes, 18 measured passes (2,034 steps per arm), and 360 balanced task pairs.

Both healthy and stopped-collector conditions finished every step with zero
replay mismatches or agent exceptions. The predeclared stopped-collector latency
bound passed. Memory used three fresh subprocess trials per arm, measured
separately from latency. Actual RSS sampling intervals are reported because
Windows/GIL scheduling was coarser than the requested 1 ms. The recovery-only
barrier was outside timing/memory measurements and did not retry failed events.

Recovery accounting balances: 5,814 outage events = 17 failed/lost + 5,797
delivered after restart; queue-full drops 0; failed-event resends 0; fresh events
323/323 received; final queue 0; duplicate events 0. Failed HTTP exports are
fail-silent drops, not durable buffering. Export warnings in the raw log are
expected outage evidence; there were no Python tracebacks or agent exceptions.
PowerShell formats native stderr warnings as NativeCommandError when redirected;
the benchmark completed all phases and wrote its aggregate outputs.

Validation: 59 SDK/Phase 5 unit tests passed with `pytest -p no:deepeval`.
Lint passed. Frozen checks before/after Part A and before/after Part B all passed:
empty Git diff and matching CRLF-normalized frozen content. SDK source was also
unchanged at that checkpoint (`git diff -- sdk/nexus_agent` empty). The later
SDK-only loss counters are described below. No TEST payloads were loaded.

Only scripts, tests, amendment, aggregate JSON/report and the aggregate chart
were staged for that checkpoint. Raw timing vectors, memory trials, logs and event identifiers remain
ignored under `data/phase5/runs/`. No tag was moved, no force-push, PR, external
notification was performed at that checkpoint; Parts C–E followed later.

## Parts C–E

Amendment 2 and the fixed follow-up manifest were committed before paid
execution. All 20 L3 heals completed: 10 per concurrency level, all full-gate.
The durable ledger retains 7,093 attempts, including one RemoteProtocolError
recovered by the unchanged actor retry policy. Known cost is $0.433429569;
$0.0019515 remains reserved for the attempt whose usage was not reported.
No reservation was erased or reconciled to zero. Ingestion replay used no APIs;
its first missing-NLI-cache pilot was excluded, and the configured model was
mounted read-only from the existing cache for the measured run.

All 20 Gemini-side heals completed at concurrency 2. The exact critic model is
gemini-3.5-flash-lite (account metadata version 3.5-flash-lite-07-2026; generation
responses report gemini-3.5-flash-lite). Its 40 calls cost $0.13337010 at the
published paid usage rates. The gate's 7,322 DeepSeek attempts cost $0.405110436.
There were no API errors/timeouts in this side row and neither cap was hit.
No additional provider calls were made during write-up or tests; the balance
endpoint is read-only and its account response stays in ignored local state.

Full-suite command (no test/directory subset):

```powershell
.venv/Scripts/python.exe -m scripts.phase5.pytest_dev_only -p no:deepeval -q -ra --basetemp=data/phase5/runs/pytest-full-final --junitxml=data/phase5/runs/full_suite.xml
```

**459 collected; 450 passed; 9 skipped; 0 failures/errors**, in 37.82 seconds.
The suite collected 440 unit, 12 integration and 7 e2e cases. All integration and
e2e cases passed against the isolated Phase 5 Kafka/Postgres stack. Eight skips
protect sealed TEST artifacts (three A3 tests, five result-provenance cases);
one existing check skips an auxiliary result file. Exact skip cases/reasons are
in `results/phase5/validation.json`. Three warnings concern already-imported
pytest plugins and an unavailable pytest cache write; execution passed.
The wrapper blocks external Python test connections and retains the existing
DEV adapter substitution; no detector/gate code changes. The integration test
availability probe now honors its configured endpoint, allowing the isolated
55433 database to be exercised. This PR's CI uses the full guarded suite too.

`ruff check .` passed. Frozen checks before/after C, D and E passed, as did the
earlier A/B checks. The only SDK behavior change is loss accounting:
`export_failed` and `dropped_total`, with queue-full-only `dropped` preserved;
tests cover failed batches, exporter exceptions and newest-drop queue behavior.
L4 historical timing numbers were not re-measured after this SDK-only fix.

RESULTS.md is generated from the JSON-backed Phase 5 headline; during this
phase its already-published earlier table is preserved without opening sealed
TEST result files. DECISIONS.md records the method and observability decisions.
Every new result is aggregate-only; raw logs, timing vectors, per-heal records,
API ledgers, patches and account balance stay out of Git.

Automatic approval review rejected advancing Kafka critic offsets because it
could skip alerts for a future consumer. No offset mutation was performed.
The paid critic/healer consumers remain stopped so the synthetic alert backlog
cannot initiate uncapped work. No ntfy, other external notification, tag move,
force-push or merge is authorized/performed. The PR target is phase-5-perf -> main.

## L3 ingestion add-on

The requested 30, 40 and 60 events/s steps each held for at least 180 seconds,
with the same warm-up, lag thresholds and original persistence checkpoint.
At 30 the strict check passed. At 40 both consumer lags were stable and all 446
detections persisted, but assembly was 445/446 at the independent detection-drain
checkpoint; a subsequent read-only query confirmed 446/446. The original strict
failure flag is retained. At 60 classifier lag grew (2.514 events/s OLS slope).
All 334/446/668 traces respectively were assembled by the post-run check.
Thus 40.071 accepted events/s is the highest tested no-growing-lag rate, while
30.000 passes every original strict checkpoint. This distinction is reported
without rewriting the 40-step verdict or claiming 30 is a capacity ceiling.

The initial run remains byte-for-byte unchanged. Independent add-on JSON and a
combined ingestion_summary.json retain both windows, criteria and checkpoint
exceptions. Before/after fingerprints of all three DeepSeek ledgers and the
Gemini ledger match exactly: no additional provider attempts or spend. Paid
critic/healer containers remained stopped; no Kafka offsets were changed.
Frozen checks before/after the add-on passed. Phase 4's offline detector path
was confirmed from source only, with code links in results.md; no sealed data
was loaded or rerun.

The entire guarded suite was rerun after the add-on/report changes:
**460 collected, 451 passed, 9 skipped, 0 failures/errors**, in 25.20 seconds.
All 12 integration and 7 e2e tests passed. The new summary test verifies separate
run preservation, highest-rate selection and the persistence-checkpoint caveat.
The same eight sealed-TEST skips and one auxiliary skip remain; validation.json
records the latest command and points to the prior c656d22 checkpoint. Lint and
staged secret scan pass; raw add-on logs/vectors remain outside Git.
