"""
Nexus Demo Agent — run_demo.py

Simulates a multi-agent pipeline that generates all 5 failure types so you
can watch the Nexus dashboard in action.

Usage:
    # Make sure the Nexus stack is running:
    docker compose up --build

    # In a separate terminal with nexus-agent installed:
    pip install nexus-agent
    python examples/crewai_agent/run_demo.py

The script:
  1. Runs a NORMAL trace (healthy baseline)
  2. Injects a TOOL_MISFIRE (empty query retry)
  3. Injects a HALLUCINATION (factually wrong output)
  4. Injects a LOOP_DETECTED (5 identical agent steps)
  5. Injects a PLAN_DRIFT (task scope switches mid-trace)
  6. Injects a CONTEXT_BLEED (agent from previous trace bleeds in)

Each trace is sent to the Nexus Collector at http://localhost:8000.
Watch http://localhost:3000 for live classification and patch proposals.
"""

from __future__ import annotations

import random
import time

import httpx

COLLECTOR_URL = "http://localhost:8000"
SDK_VERSION = "1.0.0"

random.seed(42)


def _span(
    trace_id: str,
    span_id: str,
    agent_name: str,
    span_type: str,
    input_text: str,
    output_text: str,
    duration_ms: float,
    error_type: str | None = None,
    error_message: str | None = None,
    metadata: dict | None = None,
) -> dict:
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).isoformat()
    return {
        "span_id": span_id,
        "trace_id": trace_id,
        "agent_name": agent_name,
        "span_type": span_type,
        "input": input_text,
        "output": output_text,
        "duration_ms": duration_ms,
        "error_type": error_type,
        "error_message": error_message,
        "metadata": metadata or {},
        "client_timestamp": ts,
        "sdk_version": SDK_VERSION,
        "environment": "demo",
    }


def send_trace(spans: list[dict]) -> None:
    try:
        resp = httpx.post(
            f"{COLLECTOR_URL}/v1/ingest",
            json={"spans": spans},
            timeout=5.0,
        )
        resp.raise_for_status()
        print(f"  → sent {len(spans)} spans to collector")
    except Exception as exc:
        print(f"  ! collector unreachable: {exc}")
        print("  → (demo running in offline mode — traces not sent)")


# ── Scenario builders ─────────────────────────────────────────────────────────

def scenario_normal(n: int) -> list[dict]:
    tid = f"demo_normal_{n:03d}"
    return [
        _span(tid, f"{tid}_s1", "demo_planner", "agent_step",
              "Summarize the paper on attention mechanisms",
              "Plan: retrieve paper → extract key points → summarize",
              random.uniform(50, 150)),
        _span(tid, f"{tid}_s2", "demo_planner", "retrieval",
              "attention is all you need 2017",
              "Retrieved: Vaswani et al. 2017 — Transformer architecture, multi-head self-attention...",
              random.uniform(80, 300)),
        _span(tid, f"{tid}_s3", "demo_planner", "llm_call",
              "Summarize this paper: Vaswani et al. 2017 Transformer...",
              "The Transformer model replaces RNNs with self-attention, enabling parallelism "
              "and state-of-the-art results on NLP tasks. Key innovation: multi-head attention.",
              random.uniform(600, 1500),
              metadata={"model": "gemini-2.0-flash", "tokens_used": random.randint(200, 500)}),
    ]


def scenario_tool_misfire(n: int) -> list[dict]:
    tid = f"demo_tool_misfire_{n:03d}"
    return [
        _span(tid, f"{tid}_s1", "demo_search_agent", "agent_step",
              "Find latest AI safety papers",
              "Dispatching search tool",
              random.uniform(30, 80)),
        _span(tid, f"{tid}_s2", "demo_search_agent", "tool_call",
              '{"tool": "web_search", "query": ""}',
              "Error: query must not be empty",
              random.uniform(100, 400),
              error_type="ToolExecutionError",
              error_message="query must not be empty",
              metadata={"tool_name": "web_search"}),
        _span(tid, f"{tid}_s3", "demo_search_agent", "tool_call",
              '{"tool": "web_search", "query": ""}',
              "retry failed: query must not be empty",
              random.uniform(100, 400),
              error_type="ToolExecutionError",
              error_message="retry: query must not be empty",
              metadata={"tool_name": "web_search"}),
    ]


def scenario_hallucination(n: int) -> list[dict]:
    tid = f"demo_hallucination_{n:03d}"
    return [
        _span(tid, f"{tid}_s1", "demo_qa_agent", "agent_step",
              "What year was Python first released?",
              "Searching for Python release history",
              random.uniform(40, 120)),
        _span(tid, f"{tid}_s2", "demo_qa_agent", "retrieval",
              "Python release history",
              "Python was created by Guido van Rossum. Python 1.0 released January 1994. "
              "Python 2.0 released 2000. Python 3.0 released 2008.",
              random.uniform(60, 200)),
        _span(tid, f"{tid}_s3", "demo_qa_agent", "llm_call",
              "When was Python first released? Context: Python 1.0 released January 1994",
              "Python was first released in 1989 by Guido van Rossum.",  # wrong — hallucinated
              random.uniform(800, 2000),
              metadata={"model": "gemini-2.0-flash", "tokens_used": random.randint(100, 300)}),
    ]


def scenario_loop_detected(n: int) -> list[dict]:
    tid = f"demo_loop_{n:03d}"
    spans = [
        _span(tid, f"{tid}_s1", "demo_loop_agent", "agent_step",
              "Solve: find the root cause of service degradation",
              "Plan: check metrics → analyze logs → identify cause",
              random.uniform(40, 100)),
    ]
    for i in range(5):  # identical steps = loop
        spans.append(_span(
            tid, f"{tid}_loop_{i}", "demo_loop_agent", "agent_step",
            "Check metrics for anomalies",
            "No anomalies found. Checking metrics again.",
            random.uniform(200, 600),
        ))
    return spans


def scenario_plan_drift(n: int) -> list[dict]:
    tid = f"demo_plan_drift_{n:03d}"
    return [
        _span(tid, f"{tid}_s1", "demo_planner_drift", "agent_step",
              "Write a blog post about transformer architecture",
              "Plan: research transformers → outline → write introduction → write body",
              random.uniform(50, 130)),
        _span(tid, f"{tid}_s2", "demo_planner_drift", "llm_call",
              "Write the introduction for a blog post about transformer architecture",
              "Introduction: Transformer architecture has revolutionized NLP...",
              random.uniform(600, 1200),
              metadata={"model": "gemini-2.0-flash"}),
        _span(tid, f"{tid}_s3", "demo_planner_drift", "agent_step",
              "Continue blog post",
              "Switching task to: analyze competitor pricing strategy instead",
              random.uniform(40, 100)),
        _span(tid, f"{tid}_s4", "demo_planner_drift", "llm_call",
              "Analyze competitor pricing for SaaS products",
              "Competitor analysis: Company A charges $99/mo, Company B charges $149/mo...",
              random.uniform(700, 1500),
              metadata={"model": "gemini-2.0-flash"}),
    ]


def scenario_context_bleed(n: int) -> list[dict]:
    tid = f"demo_context_bleed_{n:03d}"
    return [
        _span(tid, f"{tid}_s1", "demo_multi_agent", "agent_step",
              "Draft email to customer about refund policy",
              "Plan: load customer context → draft professional email",
              random.uniform(40, 100)),
        _span(tid, f"{tid}_s2", "demo_multi_agent", "llm_call",
              "Draft a professional email about refund policy",
              "Dear Alice, regarding your order #12345: we can offer a full refund "
              "as discussed in our previous conversation about your medical claim.",
              random.uniform(600, 1500),
              metadata={"model": "gemini-2.0-flash",
                        "session_id": "session_prev_medical_claim"}),
    ]


# ── Main ──────────────────────────────────────────────────────────────────────

SCENARIOS = [
    ("NORMAL",         scenario_normal),
    ("TOOL_MISFIRE",   scenario_tool_misfire),
    ("HALLUCINATION",  scenario_hallucination),
    ("LOOP_DETECTED",  scenario_loop_detected),
    ("PLAN_DRIFT",     scenario_plan_drift),
    ("CONTEXT_BLEED",  scenario_context_bleed),
]


def main(repeat: int = 1, delay_s: float = 2.0) -> None:
    print("=" * 60)
    print("  Nexus Demo Agent")
    print(f"  Collector: {COLLECTOR_URL}")
    print(f"  Dashboard: http://localhost:3000")
    print("=" * 60)

    for run in range(repeat):
        if repeat > 1:
            print(f"\n── Round {run + 1}/{repeat} ──")
        for name, builder in SCENARIOS:
            print(f"\n[{name}]")
            spans = builder(run)
            send_trace(spans)
            time.sleep(delay_s)

    print("\nDemo complete. Check http://localhost:3000")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Nexus demo agent")
    p.add_argument("--repeat", type=int, default=1,
                   help="Number of rounds (default 1)")
    p.add_argument("--delay", type=float, default=2.0,
                   help="Seconds between scenarios (default 2)")
    args = p.parse_args()
    main(repeat=args.repeat, delay_s=args.delay)
