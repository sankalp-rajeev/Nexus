"""Recompute NexusBench labels from the committed traces alone.

Labels are a pure function of (trace, task, injected fault). This module
rebuilds the agent's run from the trace spans and re-applies the labeler, so
anyone can audit labels.csv against traces.jsonl:

    python -m bench.relabel            # rewrite labels.csv label columns + manifest
    python -m bench.relabel --check    # exit 1 if labels.csv disagrees with the traces
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _p in (REPO, os.path.join(REPO, "sdk")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bench.agent import RunResult, Step, _parse_json  # noqa: E402
from bench.labeler import Labels, label_run  # noqa: E402
from bench.tasks import build_tasks  # noqa: E402
from bench.world import build_world  # noqa: E402

DATA = os.path.join(REPO, "data", "nexusbench")
LABEL_COLS = list(Labels.__dataclass_fields__)


def run_from_trace(trace: dict) -> RunResult:
    spans = trace["spans"]  # recorded in completion order, which is execution order per trace
    steps: list[Step] = []
    for s in spans:
        if s["span_type"] in ("tool_call", "memory_read"):
            md = dict(s.get("metadata") or {})
            tool = md.pop("tool_name", "")
            try:
                args = json.loads(s["input"]) if s["input"] else {}
            except json.JSONDecodeError:
                args = {}
            err = s["error_message"] if s.get("error_type") else None
            steps.append(Step(tool, args, None if err else s.get("output"), err, md))
    planner = next((s for s in spans if s["span_type"] == "agent_step"
                    and (s.get("metadata") or {}).get("role") == "planner"), None)
    plan_tools = list((planner or {}).get("metadata", {}).get("plan_steps", []))
    root = next((s for s in spans if (s.get("metadata") or {}).get("role") == "root"), None)
    if root is not None and root.get("error_type"):
        stop = "llm_error"
    else:
        actor_llm = [s for s in spans if s["span_type"] == "llm_call"
                     and (s.get("metadata") or {}).get("role") == "actor"]
        last = _parse_json(actor_llm[-1]["output"]) if actor_llm else None
        is_final = bool(last) and (last.get("action") == "final"
                                   or ("answer" in last and "tool" not in last))
        stop = "final" if is_final else "max_steps"
    llm_calls = sum(1 for s in spans if s["span_type"] == "llm_call")
    return RunResult(plan_tools, steps, trace.get("final_output") or "", stop, llm_calls, 0.0, 0)


def relabel(data_dir: str = DATA, check: bool = False) -> int:
    world = build_world()
    tasks = {t.task_id: t for t in build_tasks(world)}
    traces = {}
    with open(os.path.join(data_dir, "traces.jsonl"), encoding="utf-8") as fh:
        for line in fh:
            t = json.loads(line)
            traces[t["trace_id"]] = t
    path = os.path.join(data_dir, "labels.csv")
    with open(path, encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames
        rows = list(reader)
    changed = 0
    for r in rows:
        run = run_from_trace(traces[r["trace_id"]])
        lab = label_run(tasks[r["task_id"]], r["fault"], run, world).as_dict()
        new = {k: str(v) for k, v in lab.items()}
        new["stop_reason"] = run.stop_reason
        new["n_steps"] = str(len(run.steps))
        if any(r.get(k) != v for k, v in new.items()):
            changed += 1
            r.update(new)
    if check:
        print(f"{changed} of {len(rows)} label rows disagree with the traces")
        return 1 if changed else 0
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    from bench.generate import write_manifest  # noqa: PLC0415
    digest = write_manifest(data_dir)
    print(f"relabelled {changed} of {len(rows)} rows; manifest digest {digest[:16]}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--data", default=DATA)
    a = ap.parse_args()
    return relabel(a.data, a.check)


if __name__ == "__main__":
    sys.exit(main())
