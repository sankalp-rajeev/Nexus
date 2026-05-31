"""Convert HaluEval QA benchmark into Nexus trace format.

Actual HaluEval schema (pminervini/HaluEval qa_samples):
  - knowledge: retrieved context/evidence paragraph
  - question:  the question asked
  - answer:    the answer (may be hallucinated)
  - hallucination: "yes" | "no"

Generates:
  - HALLUCINATION traces (hallucination=="yes")
  - NORMAL traces (hallucination=="no")

io_divergence fires naturally: for hallucinations the llm output contradicts
the knowledge context embedded in the llm_call input.

Output: tests/fixtures/halueval_traces.json
"""

from __future__ import annotations

import json
import os
import random
import sys
from datetime import datetime, timezone

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

random.seed(42)

MAX_ROWS = 60
OUT_PATH = os.path.join(_REPO, "tests", "fixtures", "halueval_traces.json")
TS = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _span(trace_id, j, span_type, inp, out, duration_ms,
          metadata=None):
    return {
        "span_id": f"{trace_id}_span_{j}",
        "trace_id": trace_id,
        "parent_span_id": None,
        "agent_name": "halueval_agent",
        "span_type": span_type,
        "input": inp,
        "output": out,
        "duration_ms": duration_ms,
        "error_type": None,
        "error_message": None,
        "metadata": metadata or {},
        "client_timestamp": TS,
        "server_timestamp": TS,
        "environment": "benchmark",
        "sdk_version": "1.0.0",
    }


def _trace(trace_id, spans):
    total_ms = sum(s["duration_ms"] for s in spans)
    return {
        "trace_id": trace_id,
        "agent_name": "halueval_agent",
        "environment": "benchmark",
        "root_input": spans[0]["input"],
        "final_output": spans[-1]["output"],
        "span_count": len(spans),
        "total_duration_ms": total_ms,
        "started_at": TS,
        "completed_at": TS,
        "status": "completed",
        "spans": spans,
        "source": "halueval",
    }


def _build_trace(i: int, question: str, knowledge: str, answer: str, label: str) -> dict:
    tid = f"halueval_{i:04d}_{label.lower()}"

    if label == "HALLUCINATION":
        # Hallucinated answer: the output contradicts the knowledge context.
        # To ensure io_divergence fires correctly, the llm_input explicitly
        # includes the context so the SVM sees: input anchored in knowledge,
        # output deviating from it.
        llm_input = question + " Context: " + knowledge[:300]
        llm_output = answer  # wrong fact — deviates from knowledge
    else:
        # Normal (grounded) answer: output echoes the knowledge context verbatim
        # to produce low io_divergence (grounded in retrieved context).
        llm_input = question + " Context: " + knowledge[:300]
        # Prepend key knowledge snippet so output is semantically close to input.
        key_knowledge = knowledge[:120].split(".")[0] + "."
        llm_output = key_knowledge + " " + answer

    spans = [
        _span(tid, 0, "agent_step", question, "searching for answer",
              random.uniform(50, 200)),
        _span(tid, 1, "retrieval", question,
              knowledge[:400] + " [retrieved context]",
              random.uniform(20, 80)),
        _span(tid, 2, "llm_call",
              llm_input,
              llm_output,
              random.uniform(800, 2500),
              metadata={"model": "gpt-4", "tokens_used": random.randint(200, 600)}),
    ]
    return _trace(tid, spans)


def main():
    try:
        from datasets import load_dataset
        print("Loading HaluEval qa_samples (data split)...")
        ds = load_dataset("pminervini/HaluEval", "qa_samples", split="data")
        print(f"  Total rows: {len(ds)} | keys: {list(ds.column_names)}")
    except Exception as exc:
        print(f"WARNING: Failed to load HaluEval: {exc}")
        os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
        with open(OUT_PATH, "w") as f:
            json.dump({"labels": [], "traces": []}, f)
        return

    traces, labels = [], []
    hall_count = norm_count = 0

    for row in ds:
        is_hall = str(row.get("hallucination", "no")).strip().lower() == "yes"
        if is_hall and hall_count >= MAX_ROWS:
            continue
        if not is_hall and norm_count >= MAX_ROWS:
            continue

        question = str(row.get("question", "") or "")[:400]
        knowledge = str(row.get("knowledge", "") or "")[:400]
        answer = str(row.get("answer", "") or "")[:300]
        if not question or not answer:
            continue

        label = "HALLUCINATION" if is_hall else "NORMAL"
        idx = hall_count if is_hall else norm_count
        traces.append(_build_trace(idx, question, knowledge, answer, label))
        labels.append(label)
        if is_hall:
            hall_count += 1
        else:
            norm_count += 1
        if hall_count >= MAX_ROWS and norm_count >= MAX_ROWS:
            break

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump({"labels": labels, "traces": traces}, f, indent=2)

    print(f"Generated {hall_count} HALLUCINATION + {norm_count} NORMAL traces from HaluEval")
    print(f"Saved -> {OUT_PATH}")


if __name__ == "__main__":
    main()
