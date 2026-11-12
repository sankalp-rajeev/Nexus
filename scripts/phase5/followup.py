"""Capped, isolated-process Phase 5 L3 heal and Gemini side-row controller."""
import argparse
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "sdk")]
import numpy as np
import portalocker
from scripts.phase5.measurement import Budget, atomic_json

BASE = ROOT / "data/phase5/runs"
SEED = 2026111203


def sample():
    manifest = json.loads((ROOT / "reports/phase5/sample_manifest.json").read_text(encoding="utf-8"))
    ids = json.dumps(manifest["id_list"], sort_keys=True, separators=(",", ":")).encode()
    if hashlib.sha256(ids).hexdigest() != manifest["id_list_sha256"]:
        raise ValueError("Manifest digest mismatch")
    return manifest["items"]


def freeze():
    subprocess.run([sys.executable, str(ROOT / "scripts/phase5/check_frozen.py")], stdout=subprocess.DEVNULL, check=True)


def worker(item_path, root, gemini):
    from scripts.phase5.pipeline import execute
    item = json.loads(item_path.read_text(encoding="utf-8"))
    factory = None
    if gemini:
        from scripts.phase5.gemini_critic import GeminiBudget, GeminiCritic
        factory = lambda **kw: GeminiCritic(root=root, heal_id=item["item_id"], **kw)
    rec = execute(item, root, critic_factory=factory)
    if gemini:
        rec["gemini_calls"] = [r for r in GeminiBudget(root).rows() if r["heal_id"] == item["item_id"]]
        rec["critic_model"] = "gemini-3.5-flash-lite"
        atomic_json(root / "records" / f"{item['item_id']}.json", rec)


def invoke(item, root, gemini):
    record = root / "records" / f"{item['item_id']}.json"
    if record.exists():
        return json.loads(record.read_text(encoding="utf-8"))
    item_path = root / "items" / f"{item['item_id']}.json"
    atomic_json(item_path, item)
    (root / "logs").mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "scripts.phase5.followup", "--worker", str(item_path), "--root", str(root)]
    if gemini:
        cmd.append("--gemini-worker")
    started = time.perf_counter()
    with (root / "logs" / f"{item['item_id']}.log").open("ab") as log:
        try:
            proc = subprocess.run(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=7200,
                                  creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            err = "worker_exit" if proc.returncode else "missing_record"
        except subprocess.TimeoutExpired:
            err = "timeout"
    if record.exists():
        return json.loads(record.read_text(encoding="utf-8"))
    rec = dict(item_id=item["item_id"], trace_id=item["trace_id"], task_id=item["task_id"], split="dev",
               status=err, total_s=time.perf_counter()-started, stage_status={}, stages_s={},
               gate_decision="not_evaluated", calls=Budget(root).calls(item["item_id"]))
    atomic_json(record, rec)
    return rec


def stats(values, quantiles=(.5, .9)):
    return dict(n=len(values), **{f"p{int(q*100)}":float(np.quantile(values,q)) if values else None for q in quantiles})


def cohort(rows):
    completed = [r for r in rows if r["status"] == "ok"]
    full = [r for r in completed if all(r.get("stage_status",{}).get(s) == "complete" for s in ("gate_repair", "gate_heldout", "gate_regression"))]
    critic_calls = [c for r in rows for c in r.get("gemini_calls", r.get("calls",[]))
                    if "gemini_calls" in r or c.get("temperature") == .2]
    latencies = [c["latency_ms"] for c in critic_calls if "latency_ms" in c]
    # DeepSeek call records carry exact attempt wall timestamps, not latency_ms.
    latencies += [(datetime.fromisoformat(c["ended_at"])-datetime.fromisoformat(c["started_at"])).total_seconds()*1000
                  for c in critic_calls if "latency_ms" not in c and c.get("ended_at")]
    cost = sum((c.get("cost_usd") if "cost_usd" in c else c.get("provider_actual_usd")) or 0 for c in critic_calls)
    return dict(terminal_n=len(rows), completed_n=len(completed), full_gate_n=len(full),
                statuses=dict(Counter(r["status"] for r in rows)),
                decisions_descriptive_only=dict(Counter(r["gate_decision"] for r in rows)),
                all_completed_time_s=stats([r["total_s"] for r in completed]),
                full_gate_time_s=stats([r["total_s"] for r in full]),
                critic_call_latency_ms=stats(latencies), critic_cost_total_usd=cost,
                critic_cost_per_completed_heal_usd=cost/len(completed) if completed else None,
                critic_call_count=len(critic_calls),
                critic_http_status_counts=dict(Counter(str(c.get("http_status")) for c in critic_calls)),
                critic_model_versions=sorted({c.get("model_version") or c.get("provider_model") or "not_reported" for c in critic_calls}),
                api_errors=sum(bool(c.get("error")) for r in rows for c in [*r.get("calls",[]),*r.get("gemini_calls",[])]),
                timeouts=sum(c.get("error", "") in {"ReadTimeout","ConnectTimeout","WriteTimeout","PoolTimeout"} for r in rows for c in [*r.get("calls",[]),*r.get("gemini_calls",[])]),
                per_stage_s={s:stats([r["stages_s"][s] for r in completed if r.get("stage_status",{}).get(s)=="complete"]) for s in ("detect","classify","critic_call","gate_repair","gate_heldout","gate_regression")})


def run_level(items, root, concurrency, gemini):
    from scripts.phase5.gemini_critic import GeminiBudget
    budget = Budget(root)
    timing_path = root / f"level-{concurrency}-timing.json"
    identity = hashlib.sha256(json.dumps([(i["item_id"], i["trace_id"]) for i in items]).encode()).hexdigest()
    timing = json.loads(timing_path.read_text(encoding="utf-8")) if timing_path.exists() else dict(
        started_at=datetime.now(timezone.utc).isoformat(), manifest_sha256=identity)
    if timing["manifest_sha256"] != identity:
        raise ValueError("Level resume manifest differs")
    atomic_json(timing_path,timing)
    started = timing["started_at"]
    rows = []
    remaining = []
    for item in items:
        path = root / "records" / f"{item['item_id']}.json"
        if path.exists():
            rec = json.loads(path.read_text(encoding="utf-8"))
            if rec["item_id"] != item["item_id"] or rec["trace_id"] != item["trace_id"] or rec["split"] != "dev":
                raise ValueError("Resume record identity differs")
            rows.append(rec)
        else:
            remaining.append(item)
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        pending, active = iter(remaining), set()

        def submit():
            if budget.stopped() or gemini and GeminiBudget(root).snapshot().get("stopped"):
                return
            item = next(pending, None)
            if item is not None:
                active.add(pool.submit(invoke, item, root, gemini))

        for _ in range(concurrency):
            submit()
        while active:
            done, active = wait(active, return_when=FIRST_COMPLETED)
            for future in done:
                rec = future.result()
                rows.append(rec)
                print(json.dumps(dict(id=rec["item_id"], status=rec["status"], decision=rec["gate_decision"],
                        seconds=rec["total_s"], deepseek=budget.snapshot()["provider_actual_usd"],
                        gemini=GeminiBudget(root).snapshot()["actual_usage_priced_usd"] if gemini else 0)), flush=True)
                submit()
    timing.setdefault("ended_at",datetime.now(timezone.utc).isoformat())
    atomic_json(timing_path,timing)
    elapsed = (datetime.fromisoformat(timing["ended_at"])-datetime.fromisoformat(started)).total_seconds()
    result = dict(concurrency=concurrency, planned_n=len(items), started_at=started,
                  ended_at=timing["ended_at"], elapsed_s=elapsed,
                  not_started_ids=[i["item_id"] for i in items if i["item_id"] not in {r["item_id"] for r in rows}],
                  **cohort(rows))
    result["completed_heals_per_hour"] = result["completed_n"]*3600/elapsed
    result["terminal_heals_per_hour"] = len(rows)*3600/elapsed
    result["deepseek_budget"] = budget.snapshot()
    if gemini:
        result["gemini_budget"] = GeminiBudget(root).snapshot()
    return result, rows


def main(args):
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1",
                      LANGSMITH_TRACING="false", LANGCHAIN_TRACING_V2="false", LANGCHAIN_TRACING="false")
    if args.worker:
        if not args.root.resolve().is_relative_to(BASE):
            raise ValueError("Run state outside approved ignored directory")
        worker(args.worker, args.root, args.gemini_worker)
        return
    freeze()
    items = sample()
    if args.part == "c":
        chosen = random.Random(SEED).sample(items, 10)
        root = BASE / "l3_heals"
        root.mkdir(parents=True, exist_ok=True)
        # Levels share one durable budget by using one root and distinct occurrence IDs.
        Budget(root, cap=100, provider_cap=1.50)
        result = dict(seed=SEED, selected_ids=[i["item_id"] for i in chosen], levels=[], protocol="reports/phase5/amendment_2.md")
        with portalocker.Lock(str(root/"controller.lock"),timeout=1):
            for level in (1,4):
                repeated = [dict(i, item_id=f"c{level}-"+i["item_id"]) for i in chosen]
                measured, _ = run_level(repeated,root,level,False)
                result["levels"].append(measured)
                atomic_json(ROOT / "results/phase5/heal_concurrency.json",result)
    elif args.part == "d":
        from bench.llm import load_env
        from scripts.phase5.gemini_critic import MODEL
        import httpx
        load_env(str(ROOT / ".env"))
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            response = client.get("https://generativelanguage.googleapis.com/v1beta/models",headers={"x-goog-api-key":os.environ["GEMINI_API_KEY"]})
            if response.status_code != 200:
                raise RuntimeError(f"Gemini models.list HTTP {response.status_code}")
            names = {m["name"]:m for m in response.json()["models"]}
            if "models/"+MODEL not in names:
                raise RuntimeError("Registered fast model unavailable; no generation attempted")
            selected = names["models/"+MODEL]
        root = BASE / "gemini_side"
        root.mkdir(parents=True,exist_ok=True)
        Budget(root,cap=100,provider_cap=.75)
        with portalocker.Lock(str(root/"controller.lock"),timeout=1):
            current, rows = run_level(items[:20],root,2,True)
            baseline = [json.loads((BASE/"records"/f"{i['item_id']}.json").read_text(encoding="utf-8")) for i in items[:20]]
            result = dict(model=MODEL, available_model_metadata=selected, current=current, baseline=cohort(baseline),
                baseline_for_completed_ids=cohort([b for b in baseline if b["item_id"] in {r["item_id"] for r in rows if r["status"]=="ok"}]),
                occurrence_ids=[i["item_id"] for i in items[:20]], baseline_source="100-heal concurrency-2 DEV run",
                side_row_only=True, prompt_temperature=.2, max_output_tokens=800,
                wire_adaptation="unchanged prompt/system/schema; forced strict tool -> application/json responseJsonSchema; minimal thinking; same frozen validation",
                paired_decisions=[dict(item_id=r["item_id"], baseline=b["gate_decision"], now=r["gate_decision"], status=r["status"]) for r in rows for b in baseline if r["item_id"]==b["item_id"]])
            atomic_json(ROOT/"results/phase5/gemini_side.json", result)
    freeze()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--part", choices=["c","d"])
    parser.add_argument("--worker",type=Path)
    parser.add_argument("--root",type=Path)
    parser.add_argument("--gemini-worker",action="store_true")
    main(parser.parse_args())
