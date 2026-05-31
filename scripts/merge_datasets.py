"""Merge synthetic + HaluEval + ToolBench datasets into master_traces.json.

Output: tests/fixtures/master_traces.json
"""

from __future__ import annotations

import json
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

SYNTHETIC_PATH = os.path.join(_REPO, "tests", "fixtures", "synthetic_traces.json")
HALUEVAL_PATH = os.path.join(_REPO, "tests", "fixtures", "halueval_traces.json")
TOOLBENCH_PATH = os.path.join(_REPO, "tests", "fixtures", "toolbench_traces.json")
OUT_PATH = os.path.join(_REPO, "tests", "fixtures", "master_traces.json")

ALL_LABEL_TYPES = ["NORMAL", "HALLUCINATION", "TOOL_MISFIRE",
                   "LOOP_DETECTED", "PLAN_DRIFT", "CONTEXT_BLEED"]


def _load(path: str, default_source: str) -> tuple[list, list]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    traces = data.get("traces", [])
    labels = data.get("labels", [])
    # Backfill source field on traces that don't have it.
    for t in traces:
        if "source" not in t or not t["source"]:
            t["source"] = default_source
    return traces, labels


def _counts(traces: list, labels: list) -> dict:
    c = {k: 0 for k in ALL_LABEL_TYPES}
    for lbl in labels:
        if lbl in c:
            c[lbl] += 1
    return c


def _row(name: str, counts: dict, total: int) -> str:
    cols = [f"{counts.get(k, 0):>7}" for k in ALL_LABEL_TYPES]
    return f"  {name:<12} | " + " | ".join(cols) + f" | {total:>6}"


def main():
    syn_traces, syn_labels = _load(SYNTHETIC_PATH, "synthetic")
    hal_traces, hal_labels = _load(HALUEVAL_PATH, "halueval")
    tb_traces, tb_labels = _load(TOOLBENCH_PATH, "toolbench")

    all_traces = syn_traces + hal_traces + tb_traces
    all_labels = syn_labels + hal_labels + tb_labels

    # Print summary table
    header = f"  {'Source':<12} | " + " | ".join(f"{k:>7}" for k in ALL_LABEL_TYPES) + f" | {'Total':>6}"
    sep = "-" * len(header)
    print(sep)
    print(header)
    print(sep)
    for name, ts, ls in [("synthetic", syn_traces, syn_labels),
                          ("halueval", hal_traces, hal_labels),
                          ("toolbench", tb_traces, tb_labels)]:
        c = _counts(ts, ls)
        print(_row(name, c, len(ls)))
    print(sep)
    tot = _counts(all_traces, all_labels)
    print(_row("TOTAL", tot, len(all_labels)))
    print(sep)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump({"labels": all_labels, "traces": all_traces}, f, indent=2)

    print(f"\nSaved {len(all_traces)} traces -> {OUT_PATH}")


if __name__ == "__main__":
    main()
