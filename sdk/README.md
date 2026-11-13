# nexus-selfheal (`nexus_agent`)

Zero-config, fail-silent tracing SDK for multi-agent AI pipelines.
Part of the [Nexus](https://github.com/sankalp-rajeev/Nexus) platform.

> **Not yet published to PyPI.** The distribution will be named
> `nexus-selfheal`; the import name is `nexus_agent`. For now install from the
> repo: `pip install -e sdk/`.

## Quickstart

```python
import nexus_agent as nexus

nexus.init(agent_name="my-pipeline", collector_url="http://localhost:8000")

# Pattern 1 — decorator (bare or with arguments; sync and async)
@nexus.trace
def plan(task: str) -> list[str]: ...

@nexus.trace(span_type="llm_call", model="gemini-3.5-flash-lite")
def call_llm(prompt: str) -> str:
    return llm.generate(prompt)

# Pattern 2 — context manager
with nexus.span("tool_call", input=query, tool="search") as s:
    s.set_output(search_tool.run(query))

# Pattern 3 — explicit start/end
span_id = nexus.start_span("agent_step", step="retrieve")
nexus.end_span(span_id, output=result)

nexus.flush()  # before a short-lived script exits
```

Spans nest automatically (trace and parent IDs propagate via `contextvars`).
With default asynchronous export, foreground capture enqueues spans without
waiting for HTTP. Each failed export batch is retried **once** on the background
thread after a jittered 100-300 ms backoff, then dropped and counted. That covers
brief transient failures only: during a sustained outage batches are dropped (with
a throttled warning), memory stays capped and the counters are exact. There is no
requeue or disk persistence, so this is not a zero-loss guarantee. A retried batch
is delivered at least once, so a collector may see a span twice; span IDs are
stable. Synchronous export and `flush()` can wait for HTTP attempts and never retry.

The queue is bounded two ways, both dropping the incoming newest span when
exceeded: `max_queue_size` (default 10,000 spans) and `max_queue_bytes` (default
32 MiB). The byte size is an **estimate** (string lengths plus 2 KiB per span), not
exact process memory. Zero or negative limits raise `ValueError`; unbounded queues
are not allowed. Explicit spans awaiting `end_span` are held separately.

`nexus.shutdown(timeout=None)` (default `shutdown_timeout_ms`, 5000) drains for at
most that long. After the deadline it stops, discards what is still queued and
counts it as `dropped_shutdown`. It returns within the deadline plus about one
in-flight HTTP attempt. `flush()` has no deadline.

The client returned by `nexus.init(...)` exposes process-lifetime counters in
`client.stats`: `produced`, `exported`, `queued`, `pending`, `export_retried` (retry
attempts), and the losses `dropped_queue_full`, `dropped_bytes_cap`, `export_failed`
(spans lost after a failed export and its retry) and `dropped_shutdown`, whose sum is
`dropped_total`. `dropped` is kept for compatibility and means spans refused at
enqueue (queue-full plus byte-cap). When idle, `produced == exported + dropped_total
+ queued`. Counters are not durable delivery guarantees; failed events cannot be
recovered by restarting the collector.

A LangChain callback integration is planned but not implemented yet.

## Links

- [Platform & docs](https://github.com/sankalp-rajeev/Nexus)
- [Issues](https://github.com/sankalp-rajeev/Nexus/issues)
