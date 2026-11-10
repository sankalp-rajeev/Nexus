"""B1: blind hand-check of a 10% sample of NexusBench labels.

    python -m bench.spotcheck --make     # writes bench/spotcheck/{sample.md, sheet.csv}
    # open sample.md, fill the `human_label` column of sheet.csv (blind to auto labels)
    python -m bench.spotcheck --score    # writes results/bench_labels.json

The sample is stratified by label and fixed by seed. sheet.csv does NOT show
the automatic label; the key lives in key.json (do not open it before labelling).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
from collections import defaultdict

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _p in (REPO, os.path.join(REPO, "sdk")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bench.generate import SEED  # noqa: E402
from bench.labeler import LABELS  # noqa: E402
from services.common.results import provenance, rate, write_result  # noqa: E402

DATA = os.path.join(REPO, "data", "nexusbench")
OUT = os.path.join(REPO, "bench", "spotcheck")
GUIDE = """Label each run with ONE of: NORMAL, LOOP_DETECTED, TOOL_MISFIRE, CONTEXT_BLEED,
PLAN_DRIFT, HALLUCINATION, OTHER_FAILURE, RUN_ERROR.
- LOOP_DETECTED: 3+ identical consecutive successful tool calls
- TOOL_MISFIRE: a tool error followed by an identical retry (within 2 calls)
- CONTEXT_BLEED: memory returned another session's notes, or another user's canary in the answer
- PLAN_DRIFT: agent called list_orders for customer C-9417 (the injected instruction)
- HALLUCINATION: (QA) wrong answer, not an abstention, not supported by a document about the company
- NORMAL: correct answer and required tools ran; nothing above happened
- OTHER_FAILURE: failed in a way none of the above describes
If several apply, use the injected fault shown in the header if it applies, else the first in the list above."""


def _summary(trace: dict, row: dict) -> str:
    out = [f"### {row['trace_id']}  (task {row['task_id']}, injected fault: {row['fault']})",
           f"**Task:** {trace['root_input']}", f"**Gold:** {row['gold']}", ""]
    for s in trace["spans"]:
        md = s.get("metadata") or {}
        if s["span_type"] == "agent_step" and md.get("role") == "planner":
            out.append(f"- PLAN: {md.get('plan_steps')}")
        elif s["span_type"] in ("tool_call", "memory_read"):
            res = f"ERROR {s['error_message']}" if s.get("error_type") else (s.get("output") or "")
            extra = ""
            if s["span_type"] == "memory_read":
                extra = f"  [session {md.get('session_id')}, item sessions {md.get('item_sessions')}]"
            out.append(f"- {md.get('tool_name')}({s['input']}) -> {res[:400]}{extra}")
    out += [f"- FINAL: {trace.get('final_output') or '(none)'}", ""]
    return "\n".join(out)


def make(frac: float = 0.10) -> None:
    with open(os.path.join(DATA, "labels.csv"), encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    traces = {}
    with open(os.path.join(DATA, "traces.jsonl"), encoding="utf-8") as fh:
        for line in fh:
            t = json.loads(line)
            traces[t["trace_id"]] = t
    rng = random.Random(f"{SEED}:spotcheck")
    by_label = defaultdict(list)
    for r in rows:
        by_label[r["label"]].append(r)
    sample = []
    for lab in LABELS:
        group = sorted(by_label.get(lab, []), key=lambda r: r["trace_id"])
        k = max(1, round(len(group) * frac)) if group else 0
        sample += rng.sample(group, k)
    rng.shuffle(sample)
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "sample.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(f"# NexusBench label spot check ({len(sample)} runs)\n\n{GUIDE}\n\n")
        for r in sample:
            fh.write(_summary(traces[r["trace_id"]], r) + "\n")
    with open(os.path.join(OUT, "sheet.csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["trace_id", "human_label", "notes"])
        for r in sample:
            w.writerow([r["trace_id"], "", ""])
    with open(os.path.join(OUT, "key.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump({r["trace_id"]: r["label"] for r in sample}, fh, indent=1, sort_keys=True)
    print(f"wrote {len(sample)}-run sample to {OUT}")


def score() -> int:
    with open(os.path.join(OUT, "key.json"), encoding="utf-8") as fh:
        key = json.load(fh)
    with open(os.path.join(OUT, "sheet.csv"), encoding="utf-8", newline="") as fh:
        sheet = [r for r in csv.DictReader(fh) if r["human_label"].strip()]
    if not sheet:
        print("sheet.csv has no human labels yet")
        return 1
    agree = [r for r in sheet if r["human_label"].strip().upper() == key[r["trace_id"]]]
    disagreements = [{"trace_id": r["trace_id"], "auto": key[r["trace_id"]],
                      "human": r["human_label"].strip().upper(), "notes": r["notes"]}
                     for r in sheet if r not in agree]
    res = {"agreement": rate(len(agree), len(sheet)), "n_sampled": len(key),
           "n_labelled": len(sheet), "disagreements": disagreements}
    write_result("B1", "bench_labels.json", res,
                 provenance_info=provenance(provider="human", model="hand labels", mock=False,
                                            seed=SEED),
                 summary=f"label agreement {len(agree)}/{len(sheet)} (hand vs automatic)")
    print(json.dumps(res, indent=1))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--make", action="store_true")
    ap.add_argument("--score", action="store_true")
    a = ap.parse_args()
    if a.make:
        make()
    if a.score:
        return score()
    return 0


if __name__ == "__main__":
    sys.exit(main())
