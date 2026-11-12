# Phase 5 results

The overnight DEV run completed all 100 heals; median time was 421.641 seconds and p90 was 480.419 seconds.<br>
Mean provider usage-priced cost was $0.030760 per heal, 43.41% of the ledger estimate; input cache hits were 60.86%.<br>
Ingestion sustained 40.071 events/s without growing lag; 30.000 events/s passed every strict checkpoint.<br>
Recorded-response SDK replay added 0.033600 ms median and 0.212703 ms p99 per step with the collector up; failed HTTP batches are lost.<br>
The separate Gemini side row completed 20/20 heals; its results and spend are reported apart from the headline.

Headline sources: [L1/L2 JSON](../../results/phase5/heal_latency_cost.json), [L3 ingestion](../../results/phase5/ingestion_summary.json), [L3 heals](../../results/phase5/heal_concurrency.json), [L4 JSON](../../results/phase5/sdk_overhead.json), [Gemini JSON](../../results/phase5/gemini_side.json).

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

## Part C: L3 load and heal concurrency

### Ingestion, no provider calls

Machine: Intel(R) Core(TM) i9-14900HX, 24 physical cores / 32 logical processors, 31.65 GiB host RAM; Windows-10-10.0.26300-SP0. Docker has 32 CPUs and 9.71 GiB RAM.

Recorded first-20 DEV spans receive fresh synthetic IDs. Warm-up is one 20-trace pass; each measured offered-rate step lasts at least 180 seconds. All spans, accepted/rejected counts, late detections and missing detections are retained. Latency runs from a trace's first HTTP submission until its classification is committed to Postgres, not per-span HTTP response latency. Trace batching creates within-trace bursts, particularly at low rates.

The initial 1/5/20/80 events/s run and later 30/40/60 add-on are separate measurement windows. The add-on keeps the same warm-up, >=180-second holds, final-120-second lag-growth thresholds, acceptance/error checks and complete persistence requirements. All three requested add-on steps run, even if an earlier one saturates. Source JSON preserves both runs independently.

| Run | Offered events/s | Hold s | Accepted events/s | Detected/offered traces | Assembled at detection-drain | Detection p50/p99 ms | Assembler / classifier lag slope events/s | Strict pass |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| initial | 1 | 180.0 | 1.039 | 11/11 | 11/11 | 100.002/959.934 | -0.097 / -0.097 | True |
| initial | 5 | 180.0 | 5.033 | 56/56 | 56/56 | 173.417/1458.607 | -0.057 / 0.088 | True |
| initial | 20 | 180.0 | 20.122 | 224/224 | 224/224 | 772.287/2886.734 | -0.113 / 0.193 | True |
| add-on | 30 | 180.0 | 30.000 | 334/334 | 334/334 | 730.814/1953.184 | 0.006 / -0.033 | True |
| add-on | 40 | 180.0 | 40.071 | 446/446 | 445/446 | 1281.040/3191.750 | 0.186 / -0.358 | False |
| add-on | 60 | 180.0 | 60.039 | 668/668 | 668/668 | 5212.792/7976.710 | -0.012 / 2.514 | False |
| initial | 80 | 180.0 | 80.038 | 892/892 | 892/892 | 41133.417/82215.305 | -1.687 / 24.216 | False |

Highest rate passing all unchanged checks: **30.000 accepted events/s**. The bottleneck was the **classifier**, based on growing committed consumer lag while assembler lag remained stable, supported by service CPU samples. Sustainability requires no growing final-120-second committed consumer lag, >=98% accepted target rate, no HTTP/sink error, complete detections and assembled traces at the original detection-drain checkpoint. The exact lag thresholds, samples, persistence counts and sampled resource maxima are in the JSON; this is a stepped bound, not an interpolated maximum.

The highest step with no growing consumer lag was **40.071 accepted events/s**. The table retains the original stricter checkpoint verdict as well. If assembly lags the independent classification drain by a final write, that checkpoint can conservatively fail even though all traces persist later; this is not proof of event loss or a lower service-capacity ceiling. Subsequent counts and original flags are both retained in ingestion_summary.json.

At 40 offered events/s, assembly was 445/446 at the detection-drain checkpoint and 446/446 in the subsequent read-only check. The original strict flag remains unchanged.

The unmodified deployed classifier uses its rule detectors, PatchCore/SVM, MiniLM embeddings and configured NLI model. This is distinct from the frozen Phase 4 offline detector used by heals. The classifier publishes classifications to Kafka; a measurement-only sink persists them to a separate Postgres table. Assembler persistence runs in parallel. The original image lacked its NLI cache and silently used its existing zero-score fallback; that pilot was stopped, retained under ignored run state and excluded. A read-only mount of the already-cached exact NLI model restored full configured inference offline. No detector code or thresholds changed.

**Phase 4 detection used offline detector code, not the classifier container.** For DEV evidence, [phase4_handoff.py](../../services/critic/phase4_handoff.py#L177) reads saved predictions produced by [audit_dev.py](../../scripts/phase2_followup/audit_dev.py#L47) using the frozen services.detectors.pipeline. The scored Phase 4 path's [build_evidence()](../../bench/heal/test_phase.py#L79) directly calls detector_view, pipeline.compute_scores and pipeline.label in-process. Neither path depends on the deployed classifier container or its NLI cache. Its missing cache therefore did not affect Phase 4 detection. This confirmation inspected source only; sealed TEST data was neither loaded nor rerun.

Paid critic/healer consumers were stopped during synthetic ingestion; no repairs/notifications were initiated. They remain stopped to keep all paid calls inside the capped controllers. Automatic approval review rejected advancing Kafka offsets because a future consumer could skip alerts; no offsets were changed. The synthetic backlog remains in Kafka, so starting a paid consumer needs separate attention. This safe alternative does not affect the measurements.

### Paired heal concurrency, DeepSeek

Fixed seed 2026111203; 10 manifest occurrences drawn without replacement, exact IDs in followup_manifest.json and the result JSON. Concurrency 1 runs before 4. Fresh local response caches per heal; frozen seeds, prompts, gate and baseline reuse stay identical. No paid warm-up. Shared provider cap $1.50, including in-flight/unknown reservations.

| Concurrency | Completed / planned | Full gate n | Wall s | Completed heals/hour | Full-gate heal total p50 s | Gate execution p50 s | All-completed time p50 s |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 10/10 | 10 | 4513.467 | 7.976 | 440.582 | 416.873 | 440.582 |
| 4 | 10/10 | 10 | 1257.276 | 28.633 | 418.726 | 408.500 | 418.726 |

All statuses, not-started IDs, errors, timeouts, per-stage quantiles and decisions are retained in heal_concurrency.json. Throughput uses the full level wall clock, including worker startup and rejected/capped slots; completed throughput excludes unsuccessful slots. Full-gate quantiles require all three gate stages complete. Comparisons confound level order, provider/cache warming and stochastic critic patches, so they are descriptive and do not isolate a causal concurrency effect.

Part C retained **7093 API attempts**, with **1 transport error**, **0 timeouts** and all 20 terminal heal statuses OK. Known provider spend was **$0.43342957**; **$0.00195150** remains reserved for unknown usage. The RemoteProtocolError occurred at concurrency 4; the actor's unchanged retry policy recovered. Its unreported usage is not charged as zero or silently removed.

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


### Export-loss counter and buffer bounds (code/data follow-up)

Source: [`sdk_buffer_audit.json`](../../results/phase5/sdk_buffer_audit.json).
`NexusClient._run_export_loop()` drains spans, `_export_batch()` calls
`HttpExporter.export()`, and a false return (non-2xx or transport exception)
discards the drained batch. The HTTP exporter makes one attempt, with no retry,
requeue or persistence. That is why the recovery probe's 17 failed-export events
were permanently lost; restarting the collector cannot recover them.

The existing public `client.stats["dropped"]` counted queue-full losses only.
The SDK now additionally exposes `export_failed` (failed-export spans, including
unexpected exporter exceptions) and `dropped_total` (queue-full plus failed
exports). Counters are thread-safe process-lifetime counts, not durable metrics;
the existing `dropped` meaning is preserved. A test verifies a failed 17-span
batch is counted once and never retried, plus exception and newest-drop cases.
This SDK-only observability fix came after L4; its timings were not re-measured.

The default queue is bounded at **10,000 spans**, with **50 spans** per export
batch normally held outside it. A full queue drops the **newest incoming** span,
not the oldest. Configuration can opt out of a count bound: nonpositive
`max_queue_size` uses Python Queue's unbounded mode. There is **no finite
worst-case total memory bound**, even at defaults: metadata/identifiers and
caller-supplied Span fields are unrestricted, explicit pending spans are
unbounded, and serialization creates temporary copies. The default build_span
input/output/error text caps total 4,500 characters/span: 10,000 such spans alone
can hold up to 180,000,000 bytes (171.66 MiB) of Unicode character storage, before
all those other allocations. That is a partial text-storage estimate, not a RAM
limit. The **28.58 MiB added sampled peak RSS** was measured with the collector
**up**, on the registered replay workload; no outage/worst-case memory claim is
supported by that number.

## Gemini side row (Part D; separate from headline)

Exact model **gemini-3.5-flash-lite**, confirmed by account models.list; returned model versions are recorded in the JSON. Same first 20 manifest occurrences, in order; concurrency 2, same as baseline. Only critic requests go to Google; all gate agent re-runs remain DeepSeek. Frozen prompts/system text, temperature 0.2, schema and local validation are unchanged. Transport adapts the forced strict DeepSeek propose_patch function to Gemini responseMimeType=application/json and responseJsonSchema with the identical schema. Thinking uses Gemini's minimum supported level, not a promise of zero thought tokens; usage accounting includes any thinking. No additional formatting retries are added.

| Metric | DeepSeek baseline, same 20 | Gemini critic side row |
|---|---:|---:|
| Completed heals | 20 | 20 |
| Full-gate heals | 15 | 20 |
| Critic HTTP call p50 ms | 3789.016 | 1365.899 |
| All completed time-to-heal p50 s | 391.291 | 431.608 |
| Full-gate time-to-heal p50 s | 448.277 | 431.608 |
| Per-heal critic stage p50 s (all calls/validation) | 7.722 | 3.470 |
| Critic usage-priced $/completed heal | 0.00290869 | 0.00666850 |

Descriptive decisions: baseline **14 promoted / 6 rejected**; side row **13 promoted / 7 rejected**. These are **not a re-estimate of Phase 4 repair or promotion rates**. Per-occurrence comparisons, denominators, errors and any cap-stopped/not-started slots are in gemini_side.json. If a cap prevents completion, matched-completed baseline metrics are also provided; the original 20-item baseline is never silently reduced.

Gemini spend: **$0.13337010 / $2.00 cap**, across 40 calls. Gate DeepSeek spend: **$0.40511044 / $0.75 cap**, across 7322 attempts. All 20 completed; neither cap hit. There were 0 API errors and 0 timeouts; unknown Gemini calls: 0. All API retries/uncertain calls retain cost reservations. Provider actual here means API-reported usage times verified paid rates, including cache/thinking; neither API response is an invoice. [DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing/) and [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing#gemini-3.5-flash-lite) were verified 2026-11-12.

## Part E: spend, limitations and validation

New Parts C/D known DeepSeek provider spend: **$0.83854001**, plus **$0.00195150** retained for unknown usage; Gemini: **$0.13337010**. Tracked calendar-day known DeepSeek spend, including last night's requests after midnight America/New_York: **$3.63825137**. Source: spend_today.json; historical ledgers are not reset. Account balance is checked through the read-only API and reported in the handoff, outside the experiment artifacts.

Limits: one Windows machine, one overnight headline run, repeated source tasks/occurrences and small per-group L3/side-row samples. The recorded hourly provider latency drift is observational; order, cache, load and generated patch variation confound later comparisons. Gate counts are descriptive only. L4 is a deterministic stub-LLM replay using recorded DEV responses, excluding real provider/tool latency; sampled RSS has coarse realized intervals and no worst-case memory guarantee. Its historical source predates the subsequent SDK-only export-loss counters. Ingestion measures the deployed classifier's full configured path plus a measurement Postgres sink, not the Phase 4 offline detector implementation or paid repair throughput.

Deviations are explicit in amendment_1.md and amendment_2.md: recorded-response L4, separate controlled recovery barrier, smaller L3 sample/two concurrency levels, local NLI cache repair, Gemini wire-format/minimal-thinking adaptation, cap censoring if present and sealed-TEST-dependent validation skips. All frozen checks before/after each part remain mandatory. Full-suite outcome and exact skip reasons are in analysis_validation.md and validation.json.
