# Phase 5 amendment 1: offline L4 SDK microbenchmark

Date: 2026-11-12. Written and committed before executing L4. The user's new
instruction supersedes the original L4 execution design; no frozen logic changes.

## Difference from the pre-registration

The original L4 definition pairs instrumented and bare agents on the first 20
manifest occurrences with the same provider prompts/model parameters and task
seeds, randomized pair order (seed 202611117), and CPU/process overhead separated
from API wait. The requested new test instead uses a deterministic stub LLM and
scripted steps, at least 2,000 steps per arm, interleaving, two discarded warm-up
passes, added per-step p50/p99 latency and memory, and collector-outage/recovery
testing. This amendment replaces the provider/task experiment with an explicitly
**zero-provider-spend SDK microbenchmark**, and adds the outage/recovery endpoint.
It does not reinterpret the 100-heal measurements or run L3/Gemini.

## Fixed workload and comparison

- Deterministic scripted agent step: stub planner response, local tool operation,
  stub actor response. Both arms receive identical step inputs and must return
  exactly the same result. No model API, DEV/TEST task, environment secret or
  real user data is used in the microbenchmark.
- SDK off calls the bare scripted function with no active Nexus client. SDK on
  captures one agent-step span plus two LLM-call spans and one tool-call span:
  **four spans per agent step**. Use the existing SDK unchanged.
- Use two 512-step-per-arm warm-up passes, discard all their timings, then eight
  512-step-per-arm measured passes: **4,096 measured steps per arm**. Interleave
  256-step blocks in balanced ABBA/BAAB order, randomized with seed **202611117**.
  Matching step indices provide paired on-minus-off durations. Flush/shutdown
  between blocks so the SDK-off arm has no SDK worker running. Client setup,
  draining and shutdown are timed separately, outside per-step latency.
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
with two discarded 256-step warm-up passes and then 2,048 measured steps per
trial. Report median/min/max peak RSS and Python traced-heap peaks, plus on-minus-
off median differences. RSS is sampled every 1 ms in the agent process; memory
setup, buffering, export and drain are included. Also report warmed baseline and
post-cleanup RSS. This is process/heap memory, not a leak or long-run guarantee.
Raw timing vectors and event IDs stay under ignored `data/phase5/runs/`.

## Fail-open and recovery endpoint

Repeat the same interleaved timing design with the loopback collector stopped:
4,096 measured steps per arm after two discarded warm-up passes. Every step must
finish and match the deterministic result. Predefine the bounded-latency check
as paired added p99 <= **5 ms** and paired added maximum <= **100 ms**. Report
both the numbers and pass/fail; do not modify the SDK to achieve the bound.

Separately use one long-lived SDK client for a 2,048-step outage/recovery probe.
Record queued events and queue-full drops at outage end, failed-export batches/
events, and events received after the collector restarts. Then run 256 fresh
recovery steps and drain. A minimal exporter observer counts results without
changing export success/failure or retry behavior. Check whether failed batches
are resent, which queued events survive, and whether fresh events export again.
Report lost events explicitly: the SDK queue-full drop counter does not itself
count failed HTTP batches. Restore/shut down the test fixture in `finally`.

## Reporting and limits

Write aggregate L4 results to `results/phase5/sdk_overhead.json` and append Part B
to `reports/phase5/results.md`. Include SDK source hashes, runtime/platform,
counts, arm order, settings, workload definition and all errors. Results apply
to this Windows host, four-span stub workload and loopback collector, not paid
provider latency or production collector/backend throughput. No raw run data is
staged, no tags move, and no force-push is performed. Run the frozen check before
and after Part B.
