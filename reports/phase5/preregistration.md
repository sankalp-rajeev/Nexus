# Phase 5 pre-registration: latency and cost

Registered at 2026-11-12T04:11:46.469770+00:00, before the 100-heal run. Branch:
`phase-5-perf`; frozen reference: `phase4-test-scored`. DEV only; the TEST split
remains sealed. No notifications. Benchmark request payloads go only to HTTPS
`api.deepseek.com` chat-completion endpoints. Credentials are excluded from
request bodies; cached models run offline and framework tracing is disabled.

Phase 5 measures latency and cost. Gate decisions are recorded and reported descriptively only. They are not a re-estimate of Phase 4 repair or promotion rates.

## Smoke test

| DEV task | Failure class, Phase 4 / fresh | Gate, Phase 4 / fresh | A1 own-task repair, Phase 4 / fresh | Seconds |
|---|---|---|---|---:|
| qa-003 | HALLUCINATION / HALLUCINATION | promoted / promoted | true / true | 433.938 |
| tool-020 | TOOL_MISFIRE / TOOL_MISFIRE | rejected / promoted | true / true | 441.998 |

The user accepted the tool-020 difference as critic generation variability at
temperature 0.2. The regenerated patch went from **7 regression breaks to 0**.
Offline replay with the frozen scorer reproduces both Phase 4 gate decisions
from saved Phase 4 runs, and both fresh decisions from the fresh runs. Detector
views, evidence, baseline config, prompt hashes and the reported model fingerprint
match; all 344 provenance/hash comparisons pass. The original stop and its
diagnosis are preserved in `smoke_comparison.json` and `smoke_diagnosis.*`; this
pre-registration records the user's subsequent acceptance and authorization.

Both items' original and regenerated patches plus gate records are saved as four
JSON artifacts under `reports/phase5/smoke/`. No raw run records or JSONL files
are committed. Smoke spend is **$0.15867720 ledger** and
**$0.082887528 provider-reported usage-priced cost**; both
figures count toward the main run's caps. There were 693 settled API attempts,
zero API errors and no missing usage in the smoke pair.

## L1: time to terminal heal decision

Report p50 and p90 in seconds for total elapsed time and each stage: detect,
classify, critic call, gate repair check, gate held-out check, and gate regression
check. Use a monotonic clock; ISO wall-clock start/end values carry timezone
offsets. Quantiles use linear interpolation (NumPy `quantile`, method `linear`).
Total includes input/config loading and final gate bookkeeping; each gate stage
includes its task executions and existing per-task scoring. Interpreter startup
is outside the per-heal timer. Local detector model loading is included when needed.

The primary descriptive latency view includes every terminal record, including
rejections and explicit errors, with counts by status. Also report completed
pipeline records separately from interrupted/error records. A whole-heal timeout
is recorded at its elapsed deadline as right-censored; do not present it as a
successful heal. Stage quantiles use stages that actually ran; report skipped,
interrupted/unavailable and failed-stage counts alongside every denominator.

## L2: cost and tokens per heal

Report dollars and input/output tokens per heal, ledger versus provider usage,
and their ledger/provider dollar ratio. Preserve cache-hit and cache-miss input
tokens, the raw usage object, model ID, temperature and reported fingerprint for
each actual API attempt. Ratios with zero/unknown denominators remain undefined
and are counted explicitly. Critic temperature remains 0.2; actor temperature 0.

Ledger accounting conservatively prices all input at the peak cache-miss rate
($0.30/M) and output at $1.20/M. The provider-reported actual-cost view prices the
API response's cache-hit/miss input and output tokens at the published time-of-day
rates: peak $0.006/$0.30/$1.20 per million, off-peak $0.003/$0.15/$0.60.
DeepSeek reports token usage rather than a dollar invoice; the dollar figure is
computed from that reported usage and the published schedule, not claimed as an
invoice. Preserve that distinction in the results.

Pricing source: https://api-docs.deepseek.com/quick_start/pricing/, verified
2026-11-11. Peak windows are 01:00-04:00 and 06:00-10:00 UTC on weekdays outside
Chinese public holidays; this overnight window is not a Chinese public holiday.
Use response `created` time when present, otherwise request-start UTC. Record
time of day because provider load changes latency. Start/end wall clocks are
also recorded in America/New_York.

## Sample and fixed execution policy

100 heals are uniform draws **with replacement** from 91 eligible DEV DeepSeek
failures, sorted by trace ID before drawing. Seed: **202611115**.
Eligibility is provider=deepseek, non-NORMAL label equal to the injected fault.
Each draw has a unique occurrence ID (`heal-001` through `heal-100`); repeated
source items still receive a fresh patched evaluation and an individual record.
The complete IDs and task sets are in `sample_manifest.json`.

ID-list SHA-256: `7e5a41b5f59fa0ef50fe327c64c0a4ffeb6e8342356a4465349f363a16657916`.
Hash the UTF-8 bytes of `json.dumps(id_list, sort_keys=True,
separators=(',', ':'))`, with no trailing newline. Held-out and A2 regression
sets use the unchanged Phase 4 set derivation. No patch execution is reused from
Phase 4. Fixed seed-0..2 no-patch references are reused where available; missing
references are executed and timed. Each heal has a fresh local response cache;
provider-side cache hits are measured rather than disabled.

## Concurrency

**Concurrency 2, fixed for the entire run. Latency is measured under concurrency 2.**
The smoke mean predicts 12.166 hours for 100 heals at concurrency 1, exceeding
the nine-hour limit; concurrency 2 predicts 6.083 hours and is the smallest
integer concurrency meeting that limit. L3 tomorrow covers the concurrency
effect. Heals run in separate processes to isolate SDK/global state. This is an
estimate; errors, caps, crashes and provider load may alter completion time.

## Caps, timeouts, errors and restart policy

Hard caps, **including the smoke spend**: **ledger $9.00 and provider-reported
usage-priced actual cost $4.00, whichever comes first**. Before every actual
HTTP attempt, a shared SQLite transaction reserves a conservative byte-bounded,
peak-priced amount against both caps, including in-flight calls from both
workers. Stop before sending a call whose worst case would exceed either cap;
this can stop slightly below a limit. Settlements replace reservations with
known ledger/provider cost. Unknown or interrupted attempts retain their full
reservation against the provider cap; report that reserve separately from known
provider actual spend. No unaccounted retry or silently discarded cost is allowed.
Write `stopped: cap reached` and retain which cap triggered the stop.

Critic HTTP timeout is 120 seconds; actor HTTP timeout is 90 seconds. Existing
frozen critic validation/retry and actor transport/retry rules are unchanged,
and every actual attempt is included in the shared budget. Whole-heal timeout:
7200 seconds. Count and preserve API errors, timeouts, unknown usage, agent-run
errors and terminal heal errors; no failed sample slot is replaced or dropped.

Each terminal heal record is written atomically to its own JSON file. A single
controller lock and per-occurrence locks prevent duplicate processing. Restart
skips complete occurrence IDs; an incomplete heal restarts in a new attempt
directory, retaining all previous API spend and unknown reservations. Progress
is journaled atomically and rebuilt into `data/phase5/runs/heals.log` with one
line per complete heal, including ID, decision, seconds and both running spends.
The controller is detached from the terminal/Windows job to survive VS Code
closing. A restart uses the same manifest, registration commit and budgets.

## Tomorrow: defined now, not run tonight

- **L3 load:** the first 20 manifest occurrences, same frozen tasks/model settings,
  at fixed concurrency 1, 2, 4 and 8. Report throughput (heals/hour) and total/stage
  p50/p90 by level, with errors/cost and warm-up policy reported. Keep task order
  fixed within each level and rotate level order with seed 202611116.
- **L4 SDK overhead:** paired instrumented-agent versus bare-agent runs on the
  same first 20 occurrences, same prompts/model parameters and task seeds. Verify
  wire-request equivalence first; randomize pair order with seed 202611117.
  Report process/CPU overhead separately from API wait and end-to-end latency.
- **Gemini fast critic side row:** 20 heals on those same occurrences with the
  repository-pinned `gemini-3.5-flash-lite` critic and unchanged DeepSeek actor/gate.
  Report separately from the DeepSeek headline, with its own model/version,
  latency/cost and errors. Do not mix it into L1/L2 or run it tonight.

These future experiments require their own execution authorization/budgets;
tonight launches only the registered 100-heal DeepSeek DEV sample. Observe the
first three completed heals, then end monitoring without analyzing run results.
