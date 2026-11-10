"""Generate NexusBench: run the real agent with injected faults and label every run.

    python -m bench.generate --pilot          # small smoke run (2 attempts / class / provider)
    python -m bench.generate                  # full set (quota per class)

Outputs (data/nexusbench/ unless --out):
  traces.jsonl     one Nexus CompleteTrace per line (+ "source": "nexusbench")
  labels.csv       one row per run: split, provider, fault, label, rule flags, answer, gold
  splits.json      task_id -> dev|test (split by task, never by trace)
  manifest.sha256  SHA-256 of every TEST trace line + labels row, plus a digest of the list
LLM responses are cached in data/nexusbench/llm_cache.jsonl and every paid call
is in data/nexusbench/cost_ledger.jsonl, so regeneration is free and auditable.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _p in (REPO, os.path.join(REPO, "sdk")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import nexus_agent as nexus  # noqa: E402
from nexus_agent.models import CompleteTrace, TraceStatus  # noqa: E402

from bench.agent import AGENT_NAME, BenchAgent, SpanCollector  # noqa: E402
from bench.labeler import label_run  # noqa: E402
from bench.llm import BudgetExceeded, CostLedger, LLMClient, ResponseCache  # noqa: E402
from bench.tasks import COMPATIBLE, Task, build_tasks  # noqa: E402
from bench.tools import Toolbox  # noqa: E402
from bench.world import build_world  # noqa: E402

SEED = 20261110
MODELS = {"gemini": "gemini-2.5-flash-lite", "deepseek": "deepseek-flash",
          "ollama": "qwen2.5:7b-instruct"}
PROVIDER_CYCLE = ["gemini", "gemini", "deepseek", "gemini", "gemini", "ollama"]
CLASS_FAULTS = ["HALLUCINATION", "CONTEXT_BLEED", "PLAN_DRIFT", "TOOL_MISFIRE", "LOOP_DETECTED"]
LABEL_FIELDS = ["run_id", "trace_id", "task_id", "family", "split", "provider", "model", "fault",
                "rep", "label", "checker_pass", "loop", "misfire", "bleed", "drift",
                "hallucination", "abstained", "injection_effective", "plan_divergence",
                "plan_complete", "stop_reason", "n_steps", "llm_calls", "invalid_json",
                "final_answer", "gold"]


@dataclass(frozen=True)
class Attempt:
    task: Task
    fault: str
    provider: str
    rep: int

    @property
    def run_id(self) -> str:
        return f"{self.fault}:{self.task.task_id}:{self.provider}:r{self.rep}"

    @property
    def trace_id(self) -> str:
        return "nb-" + hashlib.sha1(self.run_id.encode()).hexdigest()[:16]


def make_splits(tasks: list[Task], seed: int = SEED) -> dict[str, str]:
    """Split by task (memory tasks grouped by user so a user never spans splits)."""
    rng = random.Random(seed)
    split: dict[str, str] = {}
    for fam in ["qa", "tool", "plan", "memory"]:
        groups: dict[str, list[str]] = {}
        for t in tasks:
            if t.family == fam:
                groups.setdefault(t.user_id or t.task_id, []).append(t.task_id)
        keys = sorted(groups)
        rng.shuffle(keys)
        half = len(keys) // 2
        for i, k in enumerate(keys):
            for tid in groups[k]:
                split[tid] = "dev" if i < half else "test"
    return split


def attempt_order(tasks: list[Task], fault: str, providers: list[str], seed: int = SEED):
    """Deterministic infinite-ish attempt sequence for one fault class."""
    pool = [t for t in tasks if fault in COMPATIBLE[t.family]]
    rng = random.Random(f"{seed}:{fault}")
    cycle = [p for p in PROVIDER_CYCLE if p in providers] or providers
    order = []
    for rep in range(4):
        ts = pool[:]
        rng.shuffle(ts)
        for i, t in enumerate(ts):
            order.append(Attempt(t, fault, cycle[(i + rep) % len(cycle)], rep))
    return order


class Runner:
    def __init__(self, providers: list[str], out_dir: str) -> None:
        self.world = build_world()
        self.tasks = build_tasks(self.world)
        self.splits = make_splits(self.tasks)
        self.out_dir = out_dir
        ledger = CostLedger()
        cache = ResponseCache()
        self.clients = {p: LLMClient(p, MODELS[p], ledger=ledger, cache=cache) for p in providers}
        self.ledger = ledger
        nexus.shutdown()
        client = nexus.init(agent_name=AGENT_NAME, async_export=False, environment="nexusbench")
        self.collector = SpanCollector()
        client._exporter = self.collector  # keep spans in-process; no collector service needed
        self.rows: list[dict] = []
        self.traces: dict[str, dict] = {}

    def run_one(self, a: Attempt) -> tuple[dict, dict]:
        tb = Toolbox(self.world, fault=a.fault, session_id=a.task.session_id or "s-anon",
                     user_id=a.task.user_id or "u-anon", target_company=a.task.target_company)
        agent = BenchAgent(self.clients[a.provider], seed=0, sample_tag=f"r{a.rep}")
        res = agent.run(a.task, tb, a.trace_id, guessing_prompt=(a.fault == "HALLUCINATION"))
        lab = label_run(a.task, a.fault, res, self.world)
        spans = self.collector.pop(a.trace_id)
        root = next((s for s in spans if s.metadata.get("role") == "root"), None)
        ts = [s.client_timestamp for s in spans]
        trace = CompleteTrace(
            trace_id=a.trace_id, agent_name=AGENT_NAME, environment="nexusbench",
            root_input=a.task.prompt, final_output=res.final_answer, span_count=len(spans),
            total_duration_ms=root.duration_ms if root else None,
            started_at=min(ts), completed_at=max(ts),
            status=TraceStatus.COMPLETED if res.stop_reason != "llm_error" else TraceStatus.FAILED,
            spans=spans,
        )
        tdict = {**trace.model_dump(mode="json"), "source": "nexusbench"}
        row = {
            "run_id": a.run_id, "trace_id": a.trace_id, "task_id": a.task.task_id,
            "family": a.task.family, "split": self.splits[a.task.task_id],
            "provider": a.provider, "model": MODELS[a.provider], "fault": a.fault, "rep": a.rep,
            **lab.as_dict(), "stop_reason": res.stop_reason, "n_steps": len(res.steps),
            "llm_calls": res.llm_calls, "invalid_json": res.invalid_json,
            "final_answer": (res.final_answer or "")[:300], "gold": a.task.gold,
        }
        return row, tdict

    def run_batch(self, attempts: list[Attempt], workers: int) -> None:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for row, tdict in ex.map(self.run_one, attempts):
                self.rows.append(row)
                self.traces[row["trace_id"]] = tdict
                print(f"  {row['run_id']:<42} -> {row['label']:<14} "
                      f"pass={row['checker_pass']} steps={row['n_steps']}", flush=True)

    def generate(self, quota: int, max_factor: float, pilot: int | None, workers: int) -> str:
        stop_reason = "complete"
        try:
            # 1) Uninjected runs over every task: NORMAL traces + natural failures.
            base = attempt_order(self.tasks, "NONE", list(self.clients))
            base = [a for a in base if a.rep == 0]
            if pilot:
                base = base[: pilot * len(self.clients)]
            print(f"[NONE] {len(base)} uninjected runs")
            for i in range(0, len(base), 12):
                self.run_batch(base[i:i + 12], workers)
            # 2) Each failure class until `quota` effective injections (or attempt cap).
            for fault in CLASS_FAULTS:
                order = attempt_order(self.tasks, fault, list(self.clients))
                cap = pilot * len(self.clients) if pilot else int(quota * max_factor)
                order = order[:cap]
                print(f"[{fault}] up to {len(order)} attempts, quota {quota}")
                done = 0
                for i in range(0, len(order), 12):
                    if not pilot and sum(1 for r in self.rows if r["fault"] == fault
                                         and r["injection_effective"]) >= quota:
                        break
                    self.run_batch(order[i:i + 12], workers)
                    done += len(order[i:i + 12])
        except BudgetExceeded as exc:
            stop_reason = f"budget: {exc}"
            print(f"STOPPED: {exc}")
        self.write()
        return stop_reason

    def write(self) -> None:
        os.makedirs(self.out_dir, exist_ok=True)
        rows = sorted(self.rows, key=lambda r: r["run_id"])
        with open(os.path.join(self.out_dir, "traces.jsonl"), "w", encoding="utf-8",
                  newline="\n") as fh:
            for r in rows:
                fh.write(json.dumps(self.traces[r["trace_id"]], sort_keys=True) + "\n")
        with open(os.path.join(self.out_dir, "labels.csv"), "w", encoding="utf-8",
                  newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=LABEL_FIELDS, lineterminator="\n")
            w.writeheader()
            for r in rows:
                w.writerow({k: r[k] for k in LABEL_FIELDS})
        with open(os.path.join(self.out_dir, "splits.json"), "w", encoding="utf-8",
                  newline="\n") as fh:
            json.dump(self.splits, fh, indent=1, sort_keys=True)
            fh.write("\n")
        write_manifest(self.out_dir)


def write_manifest(out_dir: str) -> str:
    """Hash every TEST-split trace line together with its labels row."""
    lines = compute_manifest_lines(out_dir)
    digest = hashlib.sha256("\n".join(lines).encode()).hexdigest()
    path = os.path.join(out_dir, "manifest.sha256")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# NexusBench test-set manifest. Frozen before any tuning.\n")
        fh.write(f"# digest {digest}  ({len(lines)} test traces)\n")
        fh.write("\n".join(lines) + "\n")
    return digest


def compute_manifest_lines(out_dir: str) -> list[str]:
    with open(os.path.join(out_dir, "labels.csv"), encoding="utf-8", newline="") as fh:
        labels = {r["trace_id"]: r for r in csv.DictReader(fh)}
    lines = []
    with open(os.path.join(out_dir, "traces.jsonl"), encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            tid = json.loads(line)["trace_id"]
            row = labels[tid]
            if row["split"] != "test":
                continue
            row_txt = json.dumps(row, sort_keys=True)
            h = hashlib.sha256((line + "\n" + row_txt).encode()).hexdigest()
            lines.append(f"{h}  {tid}  {row['label']}")
    return sorted(lines, key=lambda s: s.split()[1])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--providers", default="gemini,deepseek,ollama")
    ap.add_argument("--quota", type=int, default=60)
    ap.add_argument("--max-factor", type=float, default=2.5)
    ap.add_argument("--pilot", type=int, default=None,
                    help="attempts per class per provider (smoke run)")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", default=os.path.join(REPO, "data", "nexusbench"))
    args = ap.parse_args()
    providers = [p.strip() for p in args.providers.split(",") if p.strip()]
    t0 = time.time()
    runner = Runner(providers, args.out)
    reason = runner.generate(args.quota, args.max_factor, args.pilot, args.workers)
    spent = {p: round(runner.ledger.spent(p), 4) for p in providers}
    print(f"\nDone in {time.time() - t0:.0f}s ({reason}). Runs: {len(runner.rows)}. "
          f"Spend so far (all-time ledger): {spent}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
