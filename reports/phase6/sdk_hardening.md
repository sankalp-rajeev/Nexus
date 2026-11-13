# Phase 6 step 6.2: SDK hardening and L4 re-run

Pre-registration: `reports/phase6/l4_rerun_prereg.md`, committed (`08403ef`) before
any SDK change. The re-run used the unmodified Phase 5 harness
(`scripts/phase5/sdk_overhead.py`, git blob identical to the prereg commit) through
`scripts/phase6/sdk_overhead_rerun.py`, which only redirects output locations.
Raw result: `results/phase6/l4_rerun.json`. These Phase 6 numbers replace the
Phase 5 SDK numbers in the README and resume; both are shown below.

## What changed in the SDK (`sdk/nexus_agent/` only)

| Area | Behaviour now |
|---|---|
| Retry | One retry per failed export batch, on the background thread only, after a uniformly jittered backoff of **100 to 300 ms** (private RNG, so the application's `random` stream is untouched). The retry reuses the same batch (same `batch_id` and span IDs). Then the batch is dropped and counted in `export_failed`. |
| Never retried | `flush()`, synchronous mode (`async_export=False`), and anything after `shutdown()` has begun. |
| Byte cap | `max_queue_bytes`, default **32 MiB**, on top of `max_queue_size`. Covers queued plus in-flight spans. Over the cap the newest span is dropped, fail-silent, counted in `dropped_bytes_cap`. |
| Size estimate | **2,048-byte fixed per-span constant + length in characters** of the string fields and of strings/bytes found in `metadata`. Metadata is walked up to 256 nodes (other leaves cost 16 bytes each, as does each unvisited node). No JSON serialisation; runs on the caller thread; never raises. It is an **estimate**: it under-counts non-ASCII text (up to 4x per character) and the tail of very large metadata. The 2,048 constant came from a throwaway tracemalloc measurement of an empty-text pydantic `Span` (about 1.6 to 1.7 KiB), not from L4. |
| Validation | `max_queue_size <= 0`, `max_queue_bytes <= 0` (and non-integers or bools) raise `ValueError` naming the field. Unbounded queues are no longer possible. Backoff must satisfy `0 <= min <= max`. |
| Counters | `dropped` (kept for compatibility, now "refused at enqueue" = queue-full + byte-cap drops), plus `produced`, `dropped_queue_full`, `dropped_bytes_cap`, `export_retried` (batch retry attempts), `export_failed`, `dropped_shutdown` (6.2b), `dropped_total`, `queued_bytes_estimate`. Invariant at quiescence: `produced == exported + dropped_total + queued`. |
| Shutdown (6.2b) | `shutdown(timeout=None)`, default `shutdown_timeout_ms = 5000`: stops draining at the deadline and counts what is left as `dropped_shutdown` (part of `dropped_total`). `flush()` is unchanged. See "Step 6.2b". |
| Logging | Drop warnings are throttled (1st, then every 1,000th), so an outage cannot flood logs. |

### Worst-case added shutdown time

- `flush()`: **0 ms** added; it never retries.
- `shutdown()`: the worker's backoff wait is the stop event, so setting it wakes
  the worker at once and the retry is skipped. The only extra wait is a retry
  attempt that was **already in flight** when `shutdown()` was called: at most one
  HTTP attempt, about the export timeout (200 ms by default; httpx applies the
  timeout per phase, so a theoretical ceiling is a few hundred milliseconds
  more). It is inside the existing 2.0 s worker-join cap. A unit test sets a 5 s
  backoff and shows shutdown returns in under 1 s with no retry made.
- Measured: total flush/shutdown time across 400 SDK-on lifecycles was
  5.69 s healthy (Phase 5: 5.22 s) and 83.15 s collector-down (Phase 5: 83.47 s).
  No retries happened in the timed collector-down phase (`export_retried = 0`),
  because each short-lived client began shutdown before its first failed attempt
  finished, so those totals do not exercise the retry path.
- At the time of step 6.2 a long outage could still make `shutdown()` drain the
  queue serially (up to about 200 batches, roughly 40 s). **Step 6.2b fixed that
  with a shutdown deadline; see "Step 6.2b" below.**

## Phase 5 vs Phase 6 (L4, 2,034 steps/arm per condition, same host and seed)

Single run each, no repeats; run-to-run noise was not measured (see notes).

| Metric | Phase 5 SDK | Phase 6 hardened SDK | Change |
|---|---:|---:|---:|
| Paired added per step, collector up, p50 | 0.0336 ms | **0.0419 ms** | +0.0083 ms (+25%) |
| Paired added per step, collector up, p99 | 0.2127 ms | **0.1414 ms** | -0.0713 ms (-34%) |
| Paired added per step, collector down, p50 | 0.0341 ms | **0.0424 ms** | +0.0083 ms (+24%) |
| Paired added per step, collector down, p99 | 0.2322 ms | **0.2746 ms** | +0.0424 ms (+18%) |
| Paired added maximum, up / down | 1.1504 / 0.6056 ms | 0.4478 / 0.7317 ms | up lower, down higher |
| Paired added per task, up, p50 / p99 | 0.2265 / 1.7716 ms | 0.2627 / 0.7184 ms | |
| Paired added per task, down, p50 / p99 | 0.2574 / 1.7982 ms | 0.2729 / 2.1883 ms | |
| SDK-on sampled peak RSS (median of 3) | 80.98 MiB | 82.91 MiB | +1.93 MiB |
| SDK-off sampled peak RSS (median of 3) | 52.40 MiB | 53.52 MiB | +1.12 MiB |
| **Peak RSS delta (on minus off)** | **28.58 MiB** | **29.39 MiB** | **+0.81 MiB (+2.8%)** |
| Traced-heap peak delta | 9.23 MiB | 9.60 MiB | +0.37 MiB |
| **Outage-probe span loss** | **17** | **0** | -17, **a probe artifact, not zero loss** (see below) |
| Fail-open bound (p99 <= 5 ms, max <= 100 ms) | passed | passed | |
| Exceptions / replay mismatches | 0 / 0 | 0 / 0 | |
| Flush/shutdown total, up / down | 5.22 / 83.47 s | 5.69 / 83.15 s | |

### New counters in the re-run

| Phase (SDK-on clients) | produced | exported | export_failed | dropped_queue_full | dropped_bytes_cap | export_retried | dropped_total | invariant violations |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Collector up (400 clients) | 6,460 | 6,460 | 0 | 0 | 0 | 0 | 0 | 0 |
| Collector down (400 clients) | 6,460 | 0 | 6,460 | 0 | 0 | 0 | 6,460 | 0 |
| Recovery probe (1 client) | 6,137 | 6,137 | 0 | 0 | 0 | **1** | 0 | 0 |

The invariant held for every client. The byte cap never triggered in L4 (the
replay's spans are small); it is exercised by the unit tests below.

## Notes in plain language

**Latency: a small median cost, p99 mixed.** The median added time per step rose
by about 8 microseconds in both conditions. That is what I would expect from the
new per-span bookkeeping on the caller thread (a size estimate and one lock
acquisition; roughly 2.9 spans per step, so about 3 microseconds per span). Both
medians are tiny next to a typical provider call (not measured here). p99 fell
with the collector up and rose 18% with it down. Phase 5 was one run and I did
not measure run-to-run noise, so I cannot say the p99 moves are real; the p50
shift is consistent across both conditions, which makes it more likely real. I
am reporting the numbers as measured, not reinterpreting them.

**Memory: about 0.8 MiB more.** The delta is within the drift of the SDK-off
baseline between runs (+1.12 MiB), so it is not distinguishable from noise. This
is the same workload-specific, coarse-interval RSS sample as Phase 5, not a bound.

**Outage loss 17 to 0 is a probe artifact. The SDK does not offer zero loss.**
As pre-registered, the probe holds the next exporter call after the first failure
until the collector restarts. With the hardened SDK that next call is the retry of
the failed 17-span batch (`held_unattempted_batch_events` is now 17, not 50), so it
was delivered after the restart (`failed_event_ids_seen_after_restart` = 17). A
100 to 300 ms retry does not cover a multi-second outage. The probe's own
`accounted_loss_matches` reads `false` because its observer counts failed
*attempts* (17) while the true loss in that probe is 0; the SDK counters agree with
the collector (`export_failed` 0, `export_retried` 1, 6,137 of 6,137 exported).

**What the SDK actually guarantees about outages.** Retry covers brief transient
failures only. During a sustained outage the SDK drops batches: memory stays
capped, every span is counted exactly (`produced = exported + dropped_total +
queued`), foreground capture never blocks or raises, and shutdown returns by its
deadline. Spans dropped during an outage are not recovered when the collector
returns. The long-outage unit test below shows the real behaviour: of 1,500 spans
produced against a dead collector, 1,157 were dropped at the byte cap, 343 failed
after a retry, none were exported, and heap stayed at 34.4 MiB against about
188 MiB produced. README and resume wording should say exactly that, not "zero loss".

## Tests (`tests/unit/sdk/test_hardening.py`, `tests/unit/sdk/test_client.py`)

- Retry: success on the second attempt with the same batch object; exhaustion
  after exactly one retry is dropped and counted; an exporter that raises is
  retried then counted; sync mode and `flush()` never retry; `shutdown()`
  interrupts a 5 s backoff and skips the retry (returns in under 1 s); retry
  jitter does not consume the application's `random` stream.
- Byte cap: enforced with 100 KB spans while the worker is stuck (newest dropped,
  earliest kept, estimate never above the cap, accounting returns to 0); a single
  span larger than the cap is dropped, not raised; count cap still applies and is
  counted separately; estimator is cheap, ignores repr/serialisation, terminates
  on cyclic and very wide metadata, never raises.
- Config: 0, negative, bool, float, string and None for both queue limits raise
  `ValueError` naming the field; `nexus.init(max_queue_size=0)` raises and starts
  nothing; bad backoff rejected; documented defaults.
- Counters: `assert_invariant` (produced = exported + dropped_total + queued;
  `dropped` = queue-full + byte-cap; `dropped_total` = `dropped` + `export_failed`)
  runs in every retry, cap and outage test.
- Never blocks or raises: slow (blocked) and raising exporters, 300 spans recorded
  in under 1 s; an internal enqueue failure is counted, releases its byte
  reservation and does not raise.
- Long outage: real HTTP exporter pointed at a closed loopback port, 32 MiB cap,
  1,500 distinct 128 KiB spans (about 188 MiB) produced. Observed over 4 runs:
  1,157 dropped at the byte cap, 343 failed after the outage, 10 to 11 retries,
  0 exported, invariant held, queued bytes back to 0, **Python heap peak 34.4 MiB,
  RSS growth about 36 MiB** (versus about 188 MiB produced), slowest `record()`
  call 1.2 ms or less, shutdown about 1.6 s. Assertions are heap <= 1.25 x cap
  and RSS growth <= 2 x cap. Note that exporting a batch transiently adds about
  2x that batch for JSON encoding, so with unusually large spans a smaller
  `max_batch_size` keeps the peak nearer the cap (the test uses 10).
- Existing `test_client.py` tests that reached into the private queue or compared
  the exact `stats` dict were updated for the new queue item shape (span, size)
  and new counter keys. `tests/unit/phase6/test_sdk_overhead_rerun.py` checks that
  the re-run wrapper redirects only the result and ledger paths, refuses any
  other `results/phase5` or `reports/phase5` path, and contains no measurement code.

## Integrity and limits

- Harness integrity: `scripts/phase5/` and `results/phase5/`, `reports/phase5/`
  were clean before and after the run (recorded in the result JSON).
- The wrapper reads SDK counters after each client is shut down, outside the timed
  regions. It does not change `timing`, `memory_trials` or `recovery_probe`.
- Memory trials run in child processes, so their counters are not in the table.
- Retried batches are delivered at least once: if the collector received a batch
  but the response timed out, the retry can send it twice. Span IDs are stable
  so duplicates can be removed downstream; I did not verify collector-side
  de-duplication. L4 recorded 0 duplicate events.
- Scope: this Windows host, the registered 20-task replay, a loopback collector,
  default SDK settings. Not provider latency or production backend throughput.
- README/resume/`RESULTS.md` still quote the Phase 5 SDK figures
  (0.0336 / 0.2127 ms) until they are updated in a later step.

## Step 6.2b: duplicate-span protection and a shutdown deadline

### 1. Duplicate spans from retries (`services/common/trace_buffer.py`)

A retry can deliver a batch the collector already accepted. `TraceBuffer` used to
append every span, so the assembled trace and the classifier saw each duplicate.
Postgres span inserts ignore duplicates, but the trace row is an upsert on
`trace_id`, so a late duplicate that started a new one-span partial trace could also
overwrite the stored `span_count`. Reproduced before the fix: the same trace with two
legitimate identical tool calls (below the 3x loop threshold), with its first batch
delivered twice, was classified `LOOP_DETECTED` and raised an alert (4 identical
calls), which would trigger a paid critic call.

- **Dedupe by `span_id` within a trace.** A replayed span is not counted toward the
  500-span cap and does not extend the idle timeout.
- **Recently completed traces are remembered**, bounded by size (10,000 trace IDs,
  roughly 1 to 2 MB) and by time (300 s: 10x the 30 s inactivity timeout and far
  beyond the 100 to 300 ms retry backoff plus normal consumer lag). Completion by
  final span, span cap or idle timeout is remembered. Spans for those traces are
  dropped instead of starting a new partial trace. Both kinds are counted in
  `duplicate_spans_dropped` (breakdown: `duplicate_spans_in_trace`,
  `late_spans_after_completion`), logged throttled (1st, then every 100th), and
  exposed in the classifier's `/health` as `duplicate_spans_dropped`.
- **Trade-off, stated plainly:** a genuinely new span that arrives late for a trace
  completed within the last 300 s (for example after an idle-timeout completion) is
  now dropped too, because the memory is keyed by trace_id as specified. It is
  counted, not silent.
- **Frozen paths:** `services/common/` is not in the frozen path list
  (`scripts/phase5/check_frozen.py`). A grep of every frozen path finds no
  `TraceBuffer`/`trace_buffer`, and importing all 56 frozen modules (detectors,
  critic, `healer/gate`, `bench/heal`, `bench/detector_view`, agent/tools/world/
  labeler) does not load `services.common.trace_buffer`. `check_frozen.py` passes.
- Only the assembler and classifier consumers use `TraceBuffer`.

### 2. SDK shutdown deadline

`shutdown(timeout=None)` and `nexus.shutdown(timeout=None)`; config
`shutdown_timeout_ms` (positive integer, default **5000**). After the deadline the
SDK stops draining, discards what is still queued, counts it as `dropped_shutdown`
(part of `dropped_total`; the invariant still holds) and returns. If the background
thread is stuck in an export past the deadline, its in-flight batch is also counted
as `dropped_shutdown` exactly once. `flush()` is unchanged and has no deadline.

**Why 5 s.** In the L4 re-run a normal client lifecycle spent about 14 ms in
flush/shutdown on average, so 5 s is more than 300x the healthy cost and only a
stalled or very slow collector reaches it. In an outage each failed attempt costs
about the 200 ms export timeout, so 5 s still lets about 25 batches (about 1,250
spans) get a chance before the rest are dropped, instead of up to about 200 batches
(about 40 s). It also sits inside Docker's default 10 s stop grace period, so a
container that exits through `atexit` is not killed mid-drain. It is configurable.

**Worst-case shutdown time** is the deadline plus one in-flight HTTP attempt
(about the 200 ms export timeout) plus a join grace of twice the export timeout when
the worker is stuck. Measured with a full 10,000-span queue and a collector that
fails each attempt in 50 ms:

| Deadline | Shutdown returned after | Failed attempts counted | `dropped_shutdown` | Queue left |
|---:|---:|---:|---:|---:|
| 0.3 s | 0.318 s | 350 | 9,650 | 0 |
| 1.0 s | 1.024 s | 1,050 | 8,950 | 0 |
| 5.0 s | 5.021 s | 5,000 | 5,000 | 0 |

### 3. Outage/recovery re-run (collector-stopped timing and recovery probe only)

Run through `scripts/phase6/sdk_overhead_rerun.py --outage-only` (the same unmodified
Phase 5 harness; raw vectors under ignored `data/phase6/runs/l4_6_2b/`). The result is
appended under `step_6_2b_outage_rerun` in `results/phase6/l4_rerun.json`; the file's
measured L4 keys are unchanged (the diff is 132 added lines, 0 removed). The healthy
condition and memory trials were not re-run.

| Metric | Phase 5 | Step 6.2 run | **Step 6.2b run** |
|---|---:|---:|---:|
| Flush/shutdown total, collector down (400 SDK-on lifecycles) | 83.47 s | 83.15 s | **83.35 s** |
| Flush/shutdown total, collector up | 5.22 s | 5.69 s | 5.69 s (not re-measured) |
| Paired added per step, down, p50 / p99 | 0.0341 / 0.2322 ms | 0.0424 / 0.2746 ms | 0.0431 / 0.2724 ms |
| Outage-probe loss (probe artifact, see above) | 17 | 0 | 0 |
| Probe counters | n/a | retried 1, exported 6,137 / 6,137 | identical |
| `dropped_shutdown` | n/a | n/a | 0 in every client |

The new down total (83.35 s) matches the 6.2 run (83.15 s): the deadline did not
trigger anywhere, because each short-lived client in L4 holds only a few spans. The
deadline's effect is shown by the unit tests and the table above, not by L4. The
repeated collector-down condition also gives one sample of run-to-run variation:
p50 0.0424 to 0.0431 ms and p99 0.2746 to 0.2724 ms, so, for the collector-down
condition on this host, the 6.2 latency shift relative to Phase 5 reproduced.

### 4. Tests added in 6.2b

- `tests/unit/common/test_trace_buffer.py`:
  - (a) a batch delivered twice before completion yields a `CompleteTrace` equal to
    single delivery;
  - duplicates do not count toward the span cap or extend the idle timeout;
  - (b) duplicates after completion, including a lone final span, are dropped with no
    new trace and no partial trace;
  - timeout and cap completions are remembered; the memory expires so a reused
    trace_id eventually starts a new trace; the memory can be disabled;
  - (c) memory is size-limited (100 and the 10,000 default), time-limited (also on
    the idle sweep), and per-trace state stays bounded under a 20,000-duplicate
    storm and is released on completion;
  - the assembler writes once and ignores a redelivered batch.
- `tests/unit/classifier/test_duplicate_spans.py`: with the tracked trained model, a
  retried batch and a late full redelivery give an identical classification
  (`failure_type`, scores, rule, failing span), exactly one classification, no
  extra alert, and `/health` reports the dropped count; a regression guard shows a
  naive buffer would have produced `LOOP_DETECTED`.
- `tests/unit/sdk/test_hardening.py` (shutdown): bad `shutdown_timeout_ms`
  rejected; a long outage with a full queue returns within deadline plus margin with
  exact counts (every attempted batch counted once, the rest `dropped_shutdown`,
  invariant holds, second shutdown changes nothing); the config default is used;
  a healthy drain drops nothing; a stuck in-flight export is abandoned at the
  deadline and not double counted when it finishes later; `flush()` has no deadline;
  module-level `nexus.shutdown(timeout=...)` passes the timeout through.
- Full suite locally, including the 12 integration tests against a fresh
  Kafka/PostgreSQL/Redis from the `nexus-phase6` project: **559 passed, 9 skipped**
  (3 + 5 tests that would open sealed TEST artifacts and 1 auxiliary-file case). The
  stack was stopped afterwards with `stop` (no `down`, no volume changes).
