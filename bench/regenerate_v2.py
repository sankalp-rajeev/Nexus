"""NexusBench v2 regeneration (preregistration Amendment 1).

Re-runs only the runs whose trace called read_memory, with the v2 memory store.
Same run ids, trace ids, providers, seeds and attempt order; every other trace
line is kept byte-identical. CONTEXT_BLEED is topped up in its original seeded
attempt order if fewer than 60 runs show the failure (cap: 150 attempts).
DeepSeek spend for this step is capped at $1.00.

    python -m bench.regenerate_v2
"""

from __future__ import annotations

import csv
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _p in (REPO, os.path.join(REPO, "sdk")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bench import llm as llm_mod  # noqa: E402
from bench.generate import LABEL_FIELDS, Attempt, Runner, attempt_order, write_manifest  # noqa: E402

DATA = os.path.join(REPO, "data", "nexusbench")
PROVIDERS = ["deepseek", "ollama"]
REGEN_CAP_USD = 1.00
QUOTA, MAX_ATTEMPTS = 60, 150


def main() -> int:
    with open(os.path.join(DATA, "labels.csv"), encoding="utf-8", newline="") as fh:
        rows = {r["trace_id"]: r for r in csv.DictReader(fh)}
    lines: dict[str, str] = {}
    affected: list[str] = []
    with open(os.path.join(DATA, "traces.jsonl"), encoding="utf-8", newline="") as fh:
        for line in fh:
            t = json.loads(line)
            lines[t["trace_id"]] = line if line.endswith("\n") else line + "\n"
            if any(s["span_type"] == "memory_read" for s in t["spans"]):
                affected.append(t["trace_id"])

    ledger = llm_mod.CostLedger()
    before = ledger.spent("deepseek")
    llm_mod.CAPS_USD["deepseek"] = before + REGEN_CAP_USD  # this step's cap only
    runner = Runner(PROVIDERS, DATA)
    tasks = {t.task_id: t for t in runner.tasks}

    def attempt_for(row) -> Attempt:
        return Attempt(tasks[row["task_id"]], row["fault"], row["provider"], int(row["rep"]))

    def run(attempts):
        with ThreadPoolExecutor(max_workers=6) as ex:
            for row, tdict in ex.map(runner.run_one, attempts):
                rows[row["trace_id"]] = {k: str(row[k]) for k in LABEL_FIELDS}
                lines[row["trace_id"]] = json.dumps(tdict, sort_keys=True) + "\n"
                print(f"  {row['run_id']:<42} -> {row['label']}", flush=True)

    print(f"regenerating {len(affected)} affected runs")
    run([attempt_for(rows[tid]) for tid in sorted(affected, key=lambda t: rows[t]["run_id"])])

    def cb_effective() -> int:
        return sum(1 for r in rows.values() if r["fault"] == "CONTEXT_BLEED"
                   and r["injection_effective"] == "True")

    done = {r["run_id"] for r in rows.values() if r["fault"] == "CONTEXT_BLEED"}
    order = attempt_order(runner.tasks, "CONTEXT_BLEED", PROVIDERS)[:MAX_ATTEMPTS]
    pending = [a for a in order if a.run_id not in done]
    topped = 0
    while cb_effective() < QUOTA and pending:
        batch, pending = pending[:12], pending[12:]
        run(batch)
        topped += len(batch)
    print(f"CONTEXT_BLEED effective: {cb_effective()} (top-up attempts: {topped})")

    ordered = sorted(rows.values(), key=lambda r: r["run_id"])
    with open(os.path.join(DATA, "traces.jsonl"), "w", encoding="utf-8", newline="\n") as fh:
        for r in ordered:
            fh.write(lines[r["trace_id"]])
    with open(os.path.join(DATA, "labels.csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=LABEL_FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(ordered)
    digest = write_manifest(DATA)
    spent = llm_mod.CostLedger().spent("deepseek") - before
    print(f"done: {len(ordered)} runs; regeneration DeepSeek spend ${spent:.4f}; "
          f"manifest {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
