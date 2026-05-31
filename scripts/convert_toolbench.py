"""Convert NousResearch/hermes-function-calling-v1 into Nexus trace format.

Uses real-world tool call conversations (IoT, finance, etc.) to build:
  - TOOL_MISFIRE traces: inject an error + identical-retry onto real tool calls
  - NORMAL traces: successful tool call conversations as-is

The error injection is deliberate: we need the classifier's rule-based Stage 1
(tool_error_retry) to fire on real tool names / argument schemas.

Output: tests/fixtures/toolbench_traces.json
"""

from __future__ import annotations

import itertools
import json
import os
import random
import re
import sys
from datetime import datetime, timezone

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

random.seed(42)

MAX_SCAN = 2000
MAX_MISFIRE = 50
MAX_NORMAL = 50
OUT_PATH = os.path.join(_REPO, "tests", "fixtures", "toolbench_traces.json")
TS = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

_INJECTED_ERRORS = [
    "Error: Tool execution failed — invalid argument schema",
    "Error: timeout after 30s waiting for external API",
    "Failed: resource not found (404)",
    "Error: rate limit exceeded, retry after 60s",
    "Invalid input: required parameter missing",
]


def _span(trace_id, j, span_type, inp, out, duration_ms,
          error_type=None, error_message=None, metadata=None):
    return {
        "span_id": f"{trace_id}_span_{j}",
        "trace_id": trace_id,
        "parent_span_id": None,
        "agent_name": "toolbench_agent",
        "span_type": span_type,
        "input": inp,
        "output": out,
        "duration_ms": duration_ms,
        "error_type": error_type,
        "error_message": error_message,
        "metadata": metadata or {},
        "client_timestamp": TS,
        "server_timestamp": TS,
        "environment": "benchmark",
        "sdk_version": "1.0.0",
    }


def _trace(trace_id, spans, source):
    total_ms = sum(s["duration_ms"] for s in spans)
    return {
        "trace_id": trace_id,
        "agent_name": "toolbench_agent",
        "environment": "benchmark",
        "root_input": spans[0]["input"],
        "final_output": spans[-1]["output"],
        "span_count": len(spans),
        "total_duration_ms": total_ms,
        "started_at": TS,
        "completed_at": TS,
        "status": "completed",
        "spans": spans,
        "source": source,
    }


def _extract_tool_call(conversations: list[dict]) -> tuple[str, str, str]:
    """Returns (user_message, tool_name, tool_call_text) from conversation."""
    user_msg = ""
    tool_name = "unknown_tool"
    tool_call_text = ""
    for msg in conversations:
        # Support both "role"/"content" and "from"/"value" schemas
        role = str(msg.get("from") or msg.get("role") or "")
        val = str(msg.get("value") or msg.get("content") or "")
        if role in ("human", "user") and not user_msg and len(val.strip()) > 10:
            user_msg = val[:300]
        if role in ("gpt", "assistant") and "<tool_call>" in val:
            match = re.search(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", val, re.DOTALL)
            if match:
                tool_call_text = match.group(1)[:300]
                try:
                    parsed = json.loads(tool_call_text)
                    tool_name = parsed.get("name", "unknown_tool")
                except Exception:
                    nm = re.search(r'"name"\s*:\s*"([^"]+)"', tool_call_text)
                    if nm:
                        tool_name = nm.group(1)
            elif not tool_call_text:
                tool_call_text = val[:300]
                nm = re.search(r'"name"\s*:\s*"([^"]+)"', val)
                if nm:
                    tool_name = nm.group(1)
    return user_msg or "execute tool task", tool_name, tool_call_text or ""


def _get_tool_response(conversations: list[dict]) -> str:
    for msg in conversations:
        role = str(msg.get("from") or msg.get("role") or "")
        val = str(msg.get("value") or msg.get("content") or "")
        if role == "tool" or "<tool_response>" in val:
            match = re.search(r"<tool_response>\s*(.*?)\s*</tool_response>", val, re.DOTALL)
            return (match.group(1) if match else val)[:300]
    return "tool executed successfully"


def _get_final_msg(conversations: list[dict]) -> str:
    for msg in reversed(conversations):
        role = str(msg.get("from") or msg.get("role") or "")
        val = str(msg.get("value") or msg.get("content") or "")
        if role in ("gpt", "assistant") and "<tool_call>" not in val and len(val.strip()) > 20:
            return val[:300]
    return "task completed"


def build_misfire_trace(i: int, user_msg: str, tool_name: str, tool_call_text: str) -> dict:
    tid = f"toolbench_{i:04d}_tool_misfire"
    err = random.choice(_INJECTED_ERRORS)
    spans = [
        _span(tid, 0, "agent_step", user_msg, "dispatching tool call",
              random.uniform(30, 100)),
        _span(tid, 1, "tool_call", tool_call_text, err,
              random.uniform(100, 500),
              error_type="ToolExecutionError",
              error_message=err[:200],
              metadata={"tool_name": tool_name}),
        # Identical retry — same input, same error (triggers tool_error_retry rule)
        _span(tid, 2, "tool_call", tool_call_text,
              "retry failed: " + err[:100],
              random.uniform(100, 500),
              error_type="ToolExecutionError",
              error_message="retry: " + err[:150],
              metadata={"tool_name": tool_name}),
    ]
    return _trace(tid, spans, "toolbench")


def build_normal_trace(i: int, user_msg: str, tool_name: str,
                       tool_call_text: str, tool_response: str, final_msg: str) -> dict:
    tid = f"toolbench_{i:04d}_normal"
    spans = [
        _span(tid, 0, "agent_step", user_msg, "dispatching tool call",
              random.uniform(30, 100)),
        _span(tid, 1, "tool_call", tool_call_text, tool_response,
              random.uniform(50, 300),
              metadata={"tool_name": tool_name}),
        _span(tid, 2, "agent_step", "finalize task", final_msg,
              random.uniform(30, 100)),
    ]
    return _trace(tid, spans, "toolbench")


def main():
    try:
        from datasets import load_dataset
        print("Loading hermes-function-calling-v1 (streaming, first 2000 rows)...")
        ds = load_dataset("NousResearch/hermes-function-calling-v1",
                          split="train", streaming=True)
        rows = list(itertools.islice(ds, MAX_SCAN))
        print(f"  Scanned {len(rows)} rows")
    except Exception as exc:
        print(f"WARNING: Failed to load dataset: {exc}")
        print("Writing empty toolbench_traces.json")
        os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
        with open(OUT_PATH, "w") as f:
            json.dump({"labels": [], "traces": []}, f)
        return

    traces, labels = [], []
    misfire_idx = normal_idx = 0

    for row in rows:
        if misfire_idx >= MAX_MISFIRE and normal_idx >= MAX_NORMAL:
            break
        convs = row.get("conversations", [])
        if not convs:
            continue

        user_msg, tool_name, tool_call_text = _extract_tool_call(convs)
        if not tool_call_text or tool_name == "unknown_tool":
            continue  # skip rows without a parseable tool call

        # Alternate: first fill misfire, then normal
        if misfire_idx < MAX_MISFIRE:
            t = build_misfire_trace(misfire_idx, user_msg, tool_name, tool_call_text)
            traces.append(t)
            labels.append("TOOL_MISFIRE")
            misfire_idx += 1
        elif normal_idx < MAX_NORMAL:
            tool_resp = _get_tool_response(convs)
            final_msg = _get_final_msg(convs)
            t = build_normal_trace(normal_idx, user_msg, tool_name,
                                   tool_call_text, tool_resp, final_msg)
            traces.append(t)
            labels.append("NORMAL")
            normal_idx += 1

    n_misfire = labels.count("TOOL_MISFIRE")
    n_normal = labels.count("NORMAL")

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump({"labels": labels, "traces": traces}, f, indent=2)

    print(f"Generated {n_misfire} TOOL_MISFIRE + {n_normal} NORMAL traces from hermes-function-calling-v1")
    print(f"Saved -> {OUT_PATH}")


if __name__ == "__main__":
    main()
