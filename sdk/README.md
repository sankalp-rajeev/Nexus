# nexus-agent

Zero-config observability SDK for multi-agent AI systems. Part of the
[Nexus](../README.md) platform.

```python
import nexus_agent as nexus

nexus.init(agent_name="my-pipeline")

@nexus.trace(span_type="llm_call", model="gemini-2.0-flash")
def call_llm(prompt: str) -> str:
    ...
```

> Phase 1 scaffold — runtime API lands in Phase 2.
