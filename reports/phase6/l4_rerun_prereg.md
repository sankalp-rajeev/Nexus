# Phase 6 step 6.2: pre-registration of the L4 re-run with the hardened SDK

Date: 2026-11-12. This file is committed **before** any SDK change and before any
L4 re-run. Nothing below was chosen after seeing a Phase 6 measurement.

## What is re-run

The re-run is **identical** to `reports/phase5/amendment_1.md` and uses the same
harness, `scripts/phase5/sdk_overhead.py`, unmodified:

- Workload: `heal-001` through `heal-020` (20 DEV traces, 18 task IDs, 113
  planner/actor steps per pass), recorded-response replay, zero provider calls.
- Two discarded warm-up passes (226 steps/arm), then 18 measured passes:
  **2,034 steps per arm** per collector condition.
- Seed **202611117**, balanced random AB/BA pairing of SDK-off/SDK-on.
- SDK settings are the defaults (`async_export=True`, `export_timeout_ms=200`,
  `flush_interval_ms=100`, `max_batch_size=50`, `max_queue_size=10000`). The new
  defaults introduced by the hardened SDK apply (below); no L4-specific tuning.
- Separate-process loopback `/v1/spans` collector fixture; collector up
  (healthy) and down (listener closed); three fresh-process memory trials per arm;
  outage/recovery probe with its recovery-only scheduling barrier.
- Loopback-only network (audit hook), DEV-only data, no provider calls.

**The only change is the hardened SDK** (`sdk/nexus_agent/` only). Test split
stays sealed. No measurement logic is edited. If the harness hard-codes Phase 5
output or raw locations, a thin wrapper (`scripts/phase6/sdk_overhead_rerun.py`)
imports it and overrides only the output/raw locations
(`results/phase6/`, `data/phase6/runs/l4/`). It may additionally read (not alter)
SDK counters after each client is shut down. No `results/phase5/` or
`reports/phase5/` file is overwritten.

## SDK changes under test (fixed in advance)

1. One retry per failed export batch, on the background export thread only, after
   a uniformly jittered backoff of **100 to 300 ms**. The retry reuses the same
   batch (same `batch_id` and span IDs). No retry once shutdown has begun, and
   never in `flush()` or synchronous mode. After the retry fails the batch is
   dropped and counted.
2. `max_queue_bytes`, default **32 MiB**, on top of `max_queue_size`. Same policy
   as the count cap: drop the newest span, fail-silent. Size is an estimate: the
   sum of string/byte field lengths (including metadata) plus a fixed per-span
   constant of **2,048 bytes**, computed on the caller thread with no JSON
   serialisation. The constant comes from a throwaway tracemalloc measurement of
   a pydantic `Span` (about 1.6 to 1.7 KiB of non-text overhead), not from L4.
3. `max_queue_size <= 0` and `max_queue_bytes <= 0` raise `ValueError`.
4. Counters: `dropped` (kept), plus `dropped_queue_full`, `dropped_bytes_cap`,
   `export_retried`, `export_failed`, `dropped_total`. Invariant at quiescence:
   `produced == exported + dropped_total + queued`.

## Primary metrics (reported whatever they are)

1. Paired added per-step latency **p50 and p99**, collector up and collector down
   (Phase 5: up 0.0336 / 0.2127 ms, down 0.0341 / 0.2322 ms).
2. **Peak RSS delta**, SDK-on minus SDK-off median sampled peak RSS over the
   three memory trials (Phase 5: +29,966,336 bytes, 28.58 MiB).
3. **Outage-probe span loss**, `lost_outage_events` from the unchanged recovery
   probe (Phase 5: **17**).

Secondary, reported but not primary: paired maximum added latency and the
Phase 5 fail-open bound (p99 <= 5 ms, max <= 100 ms), SDK-on/off absolute
p50/p99, task-level paired durations, client setup and flush/shutdown totals,
and the new counters per condition.

## Known interaction to state before measuring

The recovery probe arms its scheduling barrier on the first failed export call
and holds the **next** call to `exporter.export` until the collector restarts.
With the hardened SDK the next call is the **retry of the failed batch**, so that
batch is held and then delivered after the restart. I therefore expect
`lost_outage_events` to fall from 17 to about 0 **because of how the probe is
built**, not because a 100 to 300 ms retry survives a multi-second outage; it
does not. The probe's own observer counts failed *attempts*, so
`failed_export_events` may exceed the true loss and its `accounted_loss_matches`
flag may read `false`. I will report these fields unchanged, add SDK-counter
based loss next to them, and describe the real long-outage behaviour (retry
fails, batch dropped and counted, memory capped) from the unit tests.

## Reporting rules

- One run. If it fails for an infrastructure reason before completing, I will
  record the failure and rerun the same configuration; I will not rerun to get
  a better number.
- The re-run numbers **replace** the Phase 5 SDK numbers in the README and
  resume. `reports/phase6/sdk_hardening.md` shows both Phase 5 and Phase 6
  side by side, with plain-language notes on any regression.
- Results go to `results/phase6/l4_rerun.json`; raw vectors stay under ignored
  `data/phase6/runs/l4/`.
- Results apply to this Windows host, the registered replay workload and the
  loopback collector, not provider latency or production backend throughput.
