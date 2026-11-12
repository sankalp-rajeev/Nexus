# Phase 5 results

## Part A: L1 latency and L2 cost

DEV only; fixed concurrency 2. All 100 registered occurrences are retained. Smoke is excluded from per-heal endpoints and reconciled separately below.

Run: 2026-11-11T23:17:29.900941-05:00 to 2026-11-12T04:22:27.349839-05:00.

Fast exit means rejected with all three gate stages recorded as skipped. Full gate means all three completed. No duration threshold is used; partial/interrupted cases have their own retained group.

### L1: seconds, point estimate [bootstrap 95% CI]

| Recorded-stage group | n | p50 seconds [95% CI] | p90 seconds [95% CI] |
|---|---:|---:|---:|
| all_heals | 100 | 421.641 [411.732, 447.714] | 480.419 [474.185, 489.092] |
| fast_exit | 18 | 7.619 [6.522, 8.475] | 13.940 [8.151, 15.945] |
| full_gate | 82 | 446.178 [422.422, 454.524] | 483.234 [477.542, 489.798] |
| partial_or_interrupted | 0 | n/a | n/a |

Percentile bootstrap: 10,000 resamples, fixed seed 2026111201, occurrence-level sampling; linear quantiles. CIs are conditional on this run and do not eliminate time correlation or repeated-source-task dependence.

### Per-stage latency and aggregate share of total time

| Stage | Ran | Skipped | p50 seconds [95% CI] | p90 seconds [95% CI] | Share of all-heal total |
|---|---:|---:|---:|---:|---:|
| detect | 100 | 0 | 0.000863 [0.000675, 0.000993] | 7.542 [7.467, 7.876] | 0.9203% |
| classify | 100 | 0 | 0.000302 [0.000290, 0.000342] | 0.001172 [0.001140, 0.001312] | 0.0002% |
| critic_call | 100 | 0 | 8.155 [7.922, 8.259] | 13.798 [9.150, 14.891] | 2.3354% |
| gate_repair | 82 | 18 | 15.296 [13.474, 16.633] | 20.440 [19.453, 21.249] | 3.4234% |
| gate_heldout | 82 | 18 | 74.275 [63.618, 79.485] | 91.531 [88.705, 99.040] | 16.3627% |
| gate_regression | 82 | 18 | 337.714 [332.137, 346.589] | 366.289 [358.094, 372.843] | 76.8886% |

Unattributed loading/configuration/final bookkeeping: 0.07% of total. Stage quantiles exclude explicitly skipped stages, whose counts remain visible. The JSON also includes stage distributions/shares separately for fast exits and full-gate heals.

### L2: main-run cost and tokens per heal

| Metric | Mean | Median | Total |
|---|---:|---:|---:|
| ledger_usd | 0.07085755 | 0.08101335 | 7.08575550 |
| provider_usd | 0.03075956 | 0.03774435 | 3.07595610 |
| input_tokens | 187493.93 | 214206.00 | 18749393.00 |
| cache_hit_input_tokens | 114103.16 | 133348.50 | 11410316.00 |
| cache_miss_input_tokens | 73390.77 | 84306.50 | 7339077.00 |
| output_tokens | 12174.48 | 13299.50 | 1217448.00 |

Provider/ledger ratio of totals: **0.434104**. Token-weighted input cache-hit rate: **60.86%**. The cost gap includes both cache discounts and time-of-day pricing; it is not a cache-only effect. Provider dollars price API-reported usage at the registered schedule, not an invoice.

### Latency by elapsed hour

Heals are bucketed by start time; API attempts by their own request start. Final partial hours are retained. Full-gate-only and per-request views help expose fast-exit mix effects. These observational differences do not isolate provider load.

| Run hour | Start (local offset) | Heals (fast/full) | All p50/p90 s | Full gate p50/p90 s | API p50/p90 s | API attempts |
|---|---|---:|---:|---:|---:|---:|
| 1 | 2026-11-11T23:17:29.900941-05:00 | 26 (8/18) | 389.089/470.149 | 447.731/481.409 | 1.089/1.402 | 5899 |
| 2 | 2026-11-12T00:17:29.900941-05:00 | 17 (1/16) | 456.625/480.770 | 459.394/481.226 | 1.147/1.445 | 5701 |
| 3 | 2026-11-12T01:17:29.900941-05:00 | 19 (3/16) | 411.732/478.309 | 419.437/479.034 | 1.158/1.454 | 5675 |
| 4 | 2026-11-12T02:17:29.900941-05:00 | 18 (2/16) | 446.467/490.209 | 462.025/490.484 | 1.169/1.470 | 5651 |
| 5 | 2026-11-12T03:17:29.900941-05:00 | 20 (4/16) | 420.729/474.168 | 432.416/476.929 | 1.121/1.466 | 5774 |
| 6 | 2026-11-12T04:17:29.900941-05:00 | 0 (0/0) | n/a/n/a | n/a/n/a | 1.152/1.452 | 392 |

API-attempt p50 was 1.089s in hour 1, peaked at 1.169s in hour 4, and was 1.121s in hour 5. The full-gate hourly medians are non-monotonic. This shows modest request-time drift, not evidence that provider load alone caused the variation.

![Latency over the run](figures/heal_latency_by_hour.png)

### Errors, timeouts and retries

- `terminal_heal_status`: {"ok": 100}
- `api_attempts`: 29092
- `api_error_total`: 0
- `api_error_counts`: {}
- `http_status_counts`: {"200": 29092}
- `unknown_or_unsettled_api_attempts`: 0
- `missing_provider_usage`: 0
- `heal_timeout_count`: 0
- `recorded_api_timeout_count`: 0
- `api_transport_retries_after_failed_request`: 0
- `critic_validation_retry_rounds`: 10
- `heals_without_critic_api_calls`: 4
- `critic_heals_by_retry_round_count`: {"0": 86, "1": 10}
- `critic_paid_requests_on_retry_rounds`: 20
- `agent_run_records`: 8610
- `agent_run_error_count`: 0
- `agent_run_retry_attempts`: 0
- `actor_invalid_json_responses`: 0
- `orphan_attempt_directories`: 0

Transport retries count failed API attempts; critic validation retries are separate generated proposals. Actor invalid JSON responses are model protocol errors/corrective turns, not transport retries. Four NORMAL detector outcomes made no paid critic request; their recorded critic-stage timer covers the no-op branch. All paid attempts, including retries, reconcile to the durable ledger; no heal or attempt was silently dropped.

### Gate decisions: descriptive only, not a re-estimate of Phase 4 rates

| Detector failure class | Promoted | Rejected | Other |
|---|---:|---:|---:|
| CONTEXT_BLEED | 0 | 11 | 0 |
| HALLUCINATION | 38 | 0 | 0 |
| LOOP_DETECTED | 23 | 0 | 0 |
| NORMAL | 0 | 4 | 0 |
| TOOL_MISFIRE | 11 | 13 | 0 |

### Budget reconciliation

Main 100: ledger $7.08575550, provider $3.075956103. Smoke: ledger $0.15867720, provider $0.082887528. Shared totals: ledger **$7.24443270**, provider **$3.158843631**. Caps: $9.00/$4.00; cap hit: False.

Source: registered DEV occurrence JSON plus the read-only SQLite API ledger and local actor/critic retry ledgers. Only aggregate results are committed; raw records remain ignored under `data/phase5/runs/`.

## Part B: L4 SDK overhead with recorded DEV response replay

Amendment 1 was committed before execution, including the user's 20-task recorded-response clarification. The exact first 20 manifest occurrences (20 DEV traces, 18 unique task IDs) are retained. Recorded LLM responses, tool/memory outputs and expected errors are replayed on identical scripted paths; this does not re-run agent/gate decisions. There are no live provider calls or API spend.

Two complete warm-up passes (226 steps/arm) are discarded. Eighteen measured full-task passes give 2,034 steps/arm and 360 task pairs in each collector condition. SDK-off/on task order is balanced AB/BA with seed 202611117. SDK off has no active client/exporter; SDK on uses the unchanged SDK and actual recorded span density. A separate loopback-only collector fixture excludes Kafka/backend work.

### Per-step latency (milliseconds)

| Collector | SDK off p50 / p99 | SDK on p50 / p99 | Paired added p50 / p99 | Paired added maximum |
|---|---:|---:|---:|---:|
| healthy | 0.003300 / 0.031434 | 0.037800 / 0.227169 | 0.033600 / 0.212703 | 1.150400 |
| stopped | 0.007000 / 0.046267 | 0.042600 / 0.250704 | 0.034050 / 0.232200 | 0.605600 |

Paired additions are on-minus-off for the same recorded step; negative scheduling differences are retained. Client setup, flush and shutdown are outside the per-step timer; task-root capture is included in separately reported paired task duration in the JSON. Memory tracing is run separately from these latency measurements.

Across all 400 SDK-on task lifecycles per condition (including warm-ups), flush/shutdown took 5.222s healthy versus 83.468s stopped. Those waits are outside per-step timing: the fail-open bound concerns foreground capture/replay, not zero-cost client shutdown or draining. Failed HTTP batches in the timed outage phase were dropped; the event-level recovery counts below come from a separate observed probe.

### Added memory

Three fresh-process trials per arm replay the same 20 tasks, with two warm-up passes and 2,034 measured steps/trial. RSS is agent-process-only, sampled at a requested 1 ms interval; Python heap uses tracemalloc. The collector runs in a separate process and its memory is excluded.

| Metric | SDK off median MiB | SDK on median MiB | Added median MiB |
|---|---:|---:|---:|
| sampled peak RSS | 52.398 | 80.977 | 28.578 |
| Python traced-heap peak | 0.024 | 9.256 | 9.232 |

The JSON also reports baseline/post-cleanup RSS, incremental peak RSS, realized sampler intervals and trial min/max. Although 1 ms was requested, realized mean RSS sample intervals had medians 22.78 ms off and 17.55 ms on under Windows scheduling/GIL contention. Sampled RSS peaks can miss short spikes; Python traced-heap peaks are separately tracked. These are workload-specific process/heap measurements, not a long-run leak bound.

### Fail-open and recovery

Collector listener closed: 2034/2034 SDK-on steps finished with 0 exceptions and 0 replay mismatches. The predeclared paired-added latency bound (p99 <=5 ms, max <=100 ms) **passed**.

- `outage_steps`: 2034
- `generated_outage_events`: 5814
- `queued_events_at_restart`: 5747
- `held_unattempted_batch_events`: 50
- `recovery_only_scheduling_barrier`: True
- `queue_full_drops_at_restart`: 0
- `failed_events_before_restart`: 17
- `failed_export_batches`: 1
- `failed_export_events`: 17
- `old_events_received_after_restart`: 5797
- `old_events_received_final`: 5797
- `failed_event_ids_seen_after_restart`: 0
- `lost_outage_events`: 17
- `fresh_recovery_steps`: 113
- `expected_fresh_events`: 323
- `fresh_recovery_events_received`: 323
- `final_queue_size`: 0
- `final_queue_full_dropped`: 0
- `accounted_loss_matches`: True

The recovery-only scheduling barrier held one unattempted batch after a real failed export; the listener then restarted and the held/queued events were released. This was outside latency and memory measurements; the retained queue depth is controlled test setup, not a natural-outage backlog estimate.

Failed HTTP batches are dropped without retry/persistence; events still queued when service returns can export, but previously failed batches are not replayed.
The queue-full drop counter alone excludes failed HTTP batches; the observer explicitly counted those losses. Fresh recovery events and retained pending events are distinguished from previously failed batches. The collector fixture was closed in cleanup; the user's Nexus stack and SDK source were not changed.

Limits: local Windows host, recorded SDK-visible payloads, asynchronous default SDK settings and loopback collector. This is not provider latency, real tool execution or production backend throughput. Only aggregate results are committed; raw vectors/event identifiers stay ignored under `data/phase5/runs/l4/`.
