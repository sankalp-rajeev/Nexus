# nexus-selfheal

[![PyPI](https://img.shields.io/pypi/v/nexus-selfheal)](https://pypi.org/project/nexus-selfheal/)
[![Python](https://img.shields.io/pypi/pyversions/nexus-selfheal)](https://pypi.org/project/nexus-selfheal/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Zero-config observability and autonomous self-healing SDK for multi-agent AI pipelines.
Part of the [Nexus](https://github.com/sankalp-rajeev/Nexus) platform.

> **Note:** The PyPI distribution is named `nexus-selfheal`, but the Python import
> name is `nexus_agent` (unchanged). Install with `pip install nexus-selfheal`,
> then `import nexus_agent as nexus`.

## Install

```bash
pip install nexus-selfheal
```

With LangChain integration:

```bash
pip install "nexus-selfheal[langchain]"
```

## Quickstart

```python
import nexus_agent as nexus

nexus.configure(
    collector_url="http://localhost:8000",
    agent_name="my-pipeline",
)

# Pattern 1 — decorator
@nexus.trace(span_type="llm_call", model="gemini-2.0-flash")
def call_llm(prompt: str) -> str:
    return llm.generate(prompt)

# Pattern 2 — context manager
with nexus.span("tool_call") as s:
    result = search_tool.run(query)
    s.set_output(result)

# Pattern 3 — manual
trace_id = nexus.start_trace()
nexus.record_span(trace_id=trace_id, span_type="agent_step", ...)
nexus.end_trace(trace_id)
```

## Links

- [Full documentation & platform](https://github.com/sankalp-rajeev/Nexus)
- [Bug reports](https://github.com/sankalp-rajeev/Nexus/issues)
