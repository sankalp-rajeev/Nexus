"""Phase 2 demo: a raw instrumented "LLM" pipeline that emits 10 spans.

Run the collector + Kafka first (docker compose up kafka nexus-collector), then:

    python examples/raw_llm_call/run_demo.py

Verify spans land in Kafka:

    kafka-console-consumer --bootstrap-server localhost:9092 \
        --topic nexus.spans.raw --from-beginning
"""

from __future__ import annotations

import os
import random
import time

import nexus_agent as nexus

COLLECTOR_URL = os.getenv("NEXUS_COLLECTOR_URL", "http://localhost:8000")


@nexus.trace(span_type="agent_step", agent_name="demo-agent")
def plan(task: str) -> str:
    time.sleep(random.uniform(0.005, 0.02))
    return f"plan for: {task}"


@nexus.trace(span_type="retrieval")
def retrieve(query: str) -> list[str]:
    time.sleep(random.uniform(0.005, 0.02))
    return [f"doc::{query}::{i}" for i in range(3)]


@nexus.trace(span_type="llm_call", model="gemini-2.0-flash")
def call_llm(prompt: str) -> str:
    time.sleep(random.uniform(0.01, 0.03))
    return f"answer({len(prompt)} chars)"


def main() -> None:
    nexus.init(
        agent_name="raw-llm-demo",
        collector_url=COLLECTOR_URL,
        environment="development",
    )

    # 10 spans total: 1 plan + 3 retrievals + 3 llm calls + 3 memory ops.
    p = plan("summarize the quarterly report")

    for q in ("revenue", "headcount", "risks"):
        docs = retrieve(q)
        call_llm(p + " | " + " ".join(docs))

    for i in range(3):
        with nexus.span(span_type="memory_write", key=f"summary_{i}") as s:
            s.set_output({"stored": True, "idx": i})

    nexus.flush()
    stats = nexus.get_client().stats
    print(f"[demo] emitted spans -> exported={stats['exported']} dropped={stats['dropped']}")
    nexus.shutdown()


if __name__ == "__main__":
    main()
