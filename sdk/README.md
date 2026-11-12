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
waiting for HTTP. An unreachable collector causes a throttled warning and drops
the failed batch; there is no retry, requeue or disk persistence. Synchronous
export, flush and shutdown can wait for HTTP attempts.

The default queue holds 10,000 spans and drops the incoming newest span when
full. This is a count limit, not a byte/memory limit: metadata is unrestricted,
and explicit spans awaiting end_span are held separately. A nonpositive
max_queue_size selects Python Queue's unbounded mode.

The client returned by `nexus.init(...)` exposes process-lifetime counters in
`client.stats`: `dropped` is queue-full loss, `export_failed` counts spans lost
from failed export batches (including unexpected exporter exceptions), and
`dropped_total` is their sum. `exported`, `queued` and `pending` are also exposed.
Counters are not durable delivery guarantees; failed events cannot be recovered
by restarting the collector.

A LangChain callback integration is planned but not implemented yet.

## Links

- [Platform & docs](https://github.com/sankalp-rajeev/Nexus)
- [Issues](https://github.com/sankalp-rajeev/Nexus/issues)
