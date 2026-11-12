# Parts A and B validation

Both parts are complete without additional provider API spend. The read-only
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
unchanged (`git diff -- sdk/nexus_agent` empty). No TEST payloads were loaded.

Only scripts, tests, amendment, aggregate JSON/report and the aggregate chart
are staged. Raw timing vectors, memory trials, logs and event identifiers remain
ignored under `data/phase5/runs/`. No tag was moved, no force-push, PR, external
notification, L3 or Gemini experiment was performed.
