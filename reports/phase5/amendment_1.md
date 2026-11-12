# Phase 5 amendment 1: offline L4 SDK microbenchmark

Date: 2026-11-12. Written and committed before executing L4, then updated and
recommitted before execution for the user's recorded-response clarification.
No measurement ran under the earlier synthetic-workload wording. No frozen
logic changes.

## Difference from the pre-registration

The original L4 definition pairs instrumented and bare agents on the first 20
manifest occurrences with the same provider prompts/model parameters and task
seeds, randomized pair order (seed 202611117), and CPU/process overhead separated
from API wait. The clarification retains those exact first 20 manifest occurrences
and the paired design, substituting replay of their recorded DEV LLM responses
for live model calls. It adds at least 2,000 steps per arm, two discarded warm-up
passes, per-step p50/p99 latency/memory and outage/recovery testing. This is a
**zero-provider-spend recorded-response SDK microbenchmark**. It does not
reinterpret the 100-heal measurements or run L3/Gemini.

## Fixed workload and comparison

- Select exactly `heal-001` through `heal-020`: 20 distinct DEV traces representing
  18 distinct task IDs. Retain the registered repeated task occurrences. Whitelist
  IDs with the existing DEV-only adapter before deserialization; never open TEST.
- Replay recorded planner/actor steps in order. A deterministic replay LLM returns
  each saved response for its recorded prompt, without sleep or provider access.
  Tool/memory outputs and expected errors are also replayed verbatim so scripted
  paths remain identical. This isolates SDK capture/export overhead; it does not
  rerun decision/gate or tool-backend logic. Payload sizes are those observed in
  SDK traces (possibly already truncated), not unseen provider wire prompts.
- SDK off executes the bare replay driver with no active Nexus client. SDK on
  records matching agent-step and child LLM/tool/memory spans plus a task-root
  span using the unchanged SDK. Span density follows each recorded task.
- A complete 20-occurrence pass has **113 planner/actor steps per arm**. Discard
  two full warm-up passes (226 steps per arm), then run **18 full measured passes:
  2,034 steps per arm**. Pair off/on at each task, with balanced randomized AB/BA
  order, seed **202611117**. Match step indices within each task for paired added
  durations. Flush/shutdown between task arms so SDK off has no exporter running.
  Client setup/drain/shutdown are outside per-step latency. Root-span overhead is
  included in separately reported paired task durations.
- Keep garbage collection enabled. Measure with `perf_counter_ns`; report raw
  arm p50/p99/max and paired added-latency p50/p99/max (linear quantiles). Preserve
  negative paired differences from scheduling noise rather than clipping them.

## Collector and network isolation

Use a separate-process loopback HTTP collector fixture implementing the actual
`/v1/spans` request/202-response contract. It counts events but performs no Kafka,
classifier, critic, healer or provider work. This measures SDK capture/enqueue/
HTTP-export overhead without downstream services or accidental API spend.
The collector is actually stopped (listener closed) for the outage test, then
restarted on the same loopback port. This does not stop the user's stack.
Only loopback connections are allowed; no external network or notification is
used. Collector RSS is excluded from the measured agent process.

SDK settings are its defaults: asynchronous export, 200 ms export timeout,
100 ms flush interval, maximum batch size 50, maximum queue size 10,000.

## Memory endpoint

Measure memory separately from latency so allocation tracing does not inflate
the latency headline. Run three fresh subprocess trials per arm, interleaved,
with two discarded complete 20-occurrence warm-up passes and then 18 full passes
(2,034 measured steps), using a long-lived SDK-on client. Report median/min/max
peak RSS and Python traced-heap peaks, plus on-minus-
off median differences. RSS is sampled every 1 ms in the agent process; memory
setup, buffering, export and drain are included. Also report warmed baseline and
post-cleanup RSS. This is process/heap memory, not a leak or long-run guarantee.
Raw timing vectors and event IDs stay under ignored `data/phase5/runs/`.

## Fail-open and recovery endpoint

Repeat the same interleaved timing design with the loopback collector stopped:
2,034 measured steps per arm after two discarded warm-up passes. Every step must
finish and match the deterministic result. Predefine the bounded-latency check
as paired added p99 <= **5 ms** and paired added maximum <= **100 ms**. Report
both the numbers and pass/fail; do not modify the SDK to achieve the bound.

Separately use one long-lived SDK client for an 18-pass, 2,034-step recovery probe.
Record queued events and queue-full drops at outage end, failed-export batches/
events, and events received after the collector restarts. Then replay a fresh
20-occurrence pass (113 steps) and drain. An exporter observer counts results without
changing export success/failure or retry behavior. Check whether failed batches
are resent, which queued events survive, and whether fresh events export again.
Report lost events explicitly: the SDK queue-full drop counter does not itself
count failed HTTP batches. Restore/shut down the test fixture in `finally`.

## Reporting and limits

Write aggregate L4 results to `results/phase5/sdk_overhead.json` and append Part B
to `reports/phase5/results.md`. Include SDK source hashes, runtime/platform,
counts, arm order, settings, workload definition and all errors. Results apply
to this Windows host, the registered 20-task replay workload and loopback collector, not paid
provider latency or production collector/backend throughput. No raw run data is
staged, no tags move, and no force-push is performed. Run the frozen check before
and after Part B.
