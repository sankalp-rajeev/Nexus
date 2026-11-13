# Changelog

The Python SDK is `nexus-llmops` (import `nexus_llmops`); the service is the rest of this repository.

## 0.1.0 (2026-11-13)

First stable release of the SDK. Same code as 0.1.0rc1 apart from the version number; the entries
below describe what 0.1.0 contains.

### SDK (`nexus-llmops`)

- **Fail-open tracing.** Spans are queued and exported on a background thread; an unreachable
  collector never raises into the agent, and drops are counted instead.
- **Retry.** One retry per failed export batch, on the background thread, after a jittered
  100 to 300 ms backoff; the retry reuses the batch and its span IDs. `flush()`, synchronous mode and
  anything after `shutdown()` begins are never retried.
- **Byte cap.** `max_queue_bytes` (default 32 MiB) on top of `max_queue_size`, using a cheap size
  estimate on the caller thread; over the cap the newest span is dropped.
- **Shutdown deadline.** `shutdown(timeout=None)` with `shutdown_timeout_ms` (default 5000) stops
  draining at the deadline and counts the rest as `dropped_shutdown`.
- **Counters.** `produced`, `dropped_queue_full`, `dropped_bytes_cap`, `export_retried`,
  `export_failed`, `dropped_shutdown`, `dropped_total` and `queued_bytes_estimate`, with the
  invariant `produced == exported + dropped_total + queued` at quiescence. Drop warnings are
  throttled.
- **Root-span `final` flag.** The root span of a trace carries `metadata.final = True`, so the
  service completes the trace on arrival instead of waiting for the idle timeout.
- **`nexus_agent` alias.** The old import name still works and points at the same module objects.
- Invalid queue settings (zero, negative, non-integer) raise `ValueError` naming the field.

### Service

- **Scored detectors on the live path.** The classifier runs the frozen Phase 2 detectors by default
  (`NEXUS_CLASSIFIER=legacy` keeps the old pipeline); it reproduces the scored DEV predictions on all
  359 DEV traces.
- **OTLP GenAI ingestion.** `POST /v1/traces` accepts OTLP/HTTP (protobuf or JSON) with the current
  GenAI semantic conventions, plus legacy aliases (`gen_ai.system`, `gen_ai.usage.prompt_tokens`,
  per-message events and others), recorded in `metadata["otel.legacy_aliases"]`. A parentless span
  is marked `final` like the SDK's root span.
- **Synthetic-traffic isolation.** Spans flagged with the boolean `nexus.synthetic` are classified
  but never published to `nexus.alerts`, so load tests cannot trigger paid critic calls; counted as
  `synthetic_suppressed`.
- **Duplicate-span handling.** The trace buffer drops replayed spans by `span_id` and ignores late
  spans for recently completed traces (`duplicate_spans_dropped`), so a retried batch cannot fake a
  loop.

## 0.1.0rc1 (2026-11-13, TestPyPI only)

Release candidate published to TestPyPI only (https://test.pypi.org/project/nexus-llmops/0.1.0rc1/),
never to PyPI. Same features as 0.1.0. Install was verified from TestPyPI in a clean environment
(`scripts/phase6/smoke_install.ps1 -Source testpypi`).
