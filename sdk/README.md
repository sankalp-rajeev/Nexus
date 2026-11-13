# nexus-llmops

Python SDK for [Nexus](https://github.com/sankalp-rajeev/Nexus): fail-open agent tracing for
the Nexus failure-detection and fix-verification service.

The SDK records what your agent pipeline does (LLM calls, tool calls, retrieval, memory reads
and writes, agent steps) as spans and sends them to a Nexus collector. It does no analysis
itself: failure detection (loops, tool misfires, context bleed, plan drift, hallucination) runs
in the Nexus service, which you run separately. See the main repository for how.

> **Status: alpha, `0.1.0`.** The API can still change in later `0.x` releases.

- Distribution: `nexus-llmops`. Import name: `nexus_llmops`.
- Python 3.11+. Dependencies: `httpx` and `pydantic` only (no OpenTelemetry, no protobuf).

## Install

```bash
pip install nexus-llmops
```

## Minimal example

```python
import nexus_llmops as nexus

nexus.init(agent_name="my-pipeline", collector_url="http://localhost:8000")

@nexus.trace(span_type="tool_call")
def search(query: str) -> str:
    return "results for " + query

@nexus.trace(span_type="agent_step")
def run(task: str) -> str:
    return search(task)

run("find the order")
nexus.flush()  # before a short-lived script exits
```

`collector_url` is the collector's address: `http://localhost:8000` for the full stack
(`docker-compose.yml`), `http://127.0.0.1:18000` for lite mode (`docker-compose.lite.yml`).

Spans nest automatically (trace and parent IDs propagate via `contextvars`). Three ways to
instrument:

```python
# 1. decorator (bare or with arguments; sync and async)
@nexus.trace
def plan(task: str) -> list[str]: ...

@nexus.trace(span_type="llm_call", model="my-model")
def call_llm(prompt: str) -> str: ...

# 2. context manager
with nexus.span("tool_call", input=query, tool="search") as s:
    s.set_output(search_tool.run(query))

# 3. explicit start/end
span_id = nexus.start_span("agent_step", step="retrieve")
nexus.end_span(span_id, output=result)
```

## Fail-open: your agent is never in Nexus's way

- Nexus only wraps your call to capture timing, output and exceptions. Exceptions from your code
  always propagate, after being recorded. Nexus's own failures never do.
- If the collector is down or slow, your program keeps running and finishes normally. Spans that
  cannot be delivered are dropped and **counted**, not retried forever.
- With default asynchronous export, capturing a span only enqueues it; it does not wait for HTTP.
  Each failed export batch is retried **once** on the background thread after a jittered
  100-300 ms backoff, then dropped and counted. That covers brief transient failures. During a
  sustained outage batches are dropped (with a throttled warning) and memory stays capped. There
  is no requeue and no disk persistence, so this is **not a zero-loss guarantee**. A retried batch
  is delivered at least once, so a collector can see a span twice; span IDs are stable.
- The queue is bounded two ways, dropping the incoming newest span when exceeded:
  `max_queue_size` (default 10,000 spans) and `max_queue_bytes` (default 32 MiB; the byte size is
  an estimate, not exact process memory). Zero or negative limits raise `ValueError`; unbounded
  queues are not allowed.
- `nexus.shutdown(timeout=None)` (default `shutdown_timeout_ms`, 5000) drains for at most that
  long, then discards what is still queued and counts it as `dropped_shutdown`. `flush()` has no
  deadline; synchronous export and `flush()` can wait for HTTP attempts and never retry.

The client returned by `nexus.init(...)` exposes process-lifetime counters in `client.stats`:
`produced`, `exported`, `queued`, `pending`, `export_retried` (retry attempts), and the losses
`dropped_queue_full`, `dropped_bytes_cap`, `export_failed` (spans lost after a failed export and
its retry) and `dropped_shutdown`, whose sum is `dropped_total`. When idle,
`produced == exported + dropped_total + queued`. Counters report what happened; they are not
durable delivery guarantees.

## Trace completion

When the outermost (root) span of a trace ends, the SDK sets `metadata.final = True` on it, so
the Nexus service can finish and classify the trace right away instead of waiting for an idle
timeout. Child spans are unchanged. A child span that is delivered after its root has already
arrived (for example a retried batch) is dropped by the service and counted there.

## Compatibility alias

`nexus_agent` is an alias for `nexus_llmops`: the same module objects under the old name (the
Nexus research code uses it). New code should import `nexus_llmops`.

## Not included

- No LangChain or other framework callbacks yet (planned, not implemented).
- No OpenTelemetry exporter here: an application that already uses OpenTelemetry can send OTLP
  directly to the Nexus collector's `/v1/traces` endpoint; that converter is server-side.

## Links

- [Platform and docs](https://github.com/sankalp-rajeev/Nexus)
- [Issues](https://github.com/sankalp-rajeev/Nexus/issues)
- License: MIT (see `LICENSE` in the distribution)
