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
If the collector is unreachable, spans are dropped with a throttled warning;
your agent never raises or blocks because of Nexus.

A LangChain callback integration is planned but not implemented yet.

## Links

- [Platform & docs](https://github.com/sankalp-rajeev/Nexus)
- [Issues](https://github.com/sankalp-rajeev/Nexus/issues)
