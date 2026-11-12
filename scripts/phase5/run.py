"""Phase 5 smoke and detached resumable run controller; DeepSeek + DEV only."""
import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "sdk"))

import portalocker
from scripts.phase5.measurement import Budget, Measurement, atomic_json

RUNS = ROOT / "data/phase5/runs"
MANIFEST = ROOT / "reports/phase5/sample_manifest.json"


def frozen_check():
    subprocess.run([sys.executable, str(ROOT / "scripts/phase5/check_frozen.py")], cwd=ROOT, check=True)


def worker(item_path, root):
    from scripts.phase5.pipeline import execute
    item = json.loads(Path(item_path).read_text(encoding="utf-8"))
    rec = execute(item, root)
    print(f"{rec['item_id']} {rec['status']} {rec['gate_decision']} {rec['total_s']:.3f}s", flush=True)


def invoke(item, root, timeout):
    from scripts.phase5.pipeline import completed
    record_path = root / "records" / f"{item['item_id']}.json"
    existing = completed(record_path, item)
    if existing is not None:
        return existing
    item_path = root / "items" / f"{item['item_id']}.json"
    atomic_json(item_path, item)
    log = root / "work" / f"{item['item_id']}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    started_wall = datetime.now(timezone.utc).isoformat()
    error = None
    with log.open("ab", buffering=0) as output:
        try:
            result = subprocess.run([sys.executable, "-m", "scripts.phase5.run", "--worker", str(item_path),
                                     "--root", str(root)], cwd=ROOT, stdout=output, stderr=subprocess.STDOUT,
                                    timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            if result.returncode:
                error = f"worker_exit_{result.returncode}"
        except subprocess.TimeoutExpired:
            error = "heal_timeout"
    rec = completed(record_path, item)
    if rec is None:
        # Killed/crashed workers still occupy a sample slot, retain API reservations,
        # and produce one explicit terminal error record instead of disappearing.
        measure = Measurement(item["item_id"], item["trace_id"])
        measure.record.update(status="timeout" if error == "heal_timeout" else "error",
            gate_decision="not_evaluated", error=error or "missing_worker_record", outcome=None,
            split="dev", task_id=item["task_id"], fault=item["fault"])
        rec = measure.finish(Budget(root))
        rec.update(started_at=started_wall, total_s=time.perf_counter() - started,
                   stages_s={s: None for s in rec["stages_s"]},
                   stage_status={s: "unavailable_worker_interrupted" for s in rec["stage_status"]})
        rec["timeout_count"] += error == "heal_timeout"
        atomic_json(record_path, rec)
    return rec


def progress(root, rec, filename):
    """Atomic progress journal regenerates the human log after a crash."""
    path = root / (filename + ".index.json")
    journal = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"lines": {}}
    if rec["item_id"] not in journal["lines"]:
        spend = Budget(root).snapshot()
        journal["lines"][rec["item_id"]] = (f"id={rec['item_id']} decision={rec['gate_decision']} "
            f"seconds={rec['total_s']:.3f} running_spend=${spend['ledger_accounted_usd']:.6f} "
            f"provider_spend=${spend['provider_actual_usd']:.6f} status={rec['status']}")
    atomic_json(path, journal)
    target = root / filename
    temporary = target.with_suffix(target.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(journal["lines"].values()) + "\n")
        if Budget(root).stopped():
            stream.write("stopped: cap reached\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, target)
    print(journal["lines"][rec["item_id"]], flush=True)


def smoke(root):
    from scripts.phase5.prepare import smoke_items
    frozen_check()
    rows = []
    for item in smoke_items():
        rec = invoke(item, root, 7200)
        progress(root, rec, "smoke.log")
        expected = item["expected"]
        compared = {key: dict(phase4=expected[key], phase5=rec.get(key), match=expected[key] == rec.get(key))
                    for key in ("gate_decision", "failure_class", "outcome")}
        rows.append(dict(item_id=item["item_id"], trace_id=item["trace_id"], task_id=item["task_id"],
                         status=rec["status"], comparisons=compared, total_s=rec["total_s"]))
        if rec["status"] not in {"ok", "agent_errors"}:
            break
    passed = len(rows) == 2 and all(all(c["match"] for c in r["comparisons"].values()) and r["status"] == "ok" for r in rows)
    report = dict(status="PASS" if passed else "STOP", rows=rows,
                  estimated_100_heals_seconds=100 * sum(r["total_s"] for r in rows) / len(rows))
    atomic_json(ROOT / "reports/phase5/smoke_comparison.json", report)
    print("item | gate Phase4/Phase5 | class Phase4/Phase5 | outcome Phase4/Phase5 | match", flush=True)
    for r in rows:
        c = r["comparisons"]
        fields = [f"{c[k]['phase4']}/{c[k]['phase5']}" for k in ("gate_decision", "failure_class", "outcome")]
        print(" | ".join([r["trace_id"], *fields, str(all(x["match"] for x in c.values()))]), flush=True)
    frozen_check()
    if not passed:
        raise RuntimeError("Smoke differs from Phase 4; STOP: no pre-registration or overnight launch")
    print(f"Smoke matches; 100-heal concurrency-1 estimate: {report['estimated_100_heals_seconds']/3600:.2f} hours", flush=True)


def load_registered():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    payload = json.dumps(manifest["id_list"], sort_keys=True, separators=(",", ":")).encode("utf-8")
    if hashlib.sha256(payload).hexdigest() != manifest["id_list_sha256"]:
        raise ValueError("Registered ID list digest differs")
    if [dict(item_id=i["item_id"], trace_id=i["trace_id"]) for i in manifest["items"]] != manifest["id_list"]:
        raise ValueError("Manifest items differ from the registered ID list")
    config = json.loads((ROOT / "reports/phase5/run_config.json").read_text(encoding="utf-8"))
    if (config["sample_sha256"] != manifest["id_list_sha256"] or config["ledger_cap_usd"] != 9.0
            or config["provider_cap_usd"] != 4.0 or config["concurrency"] != 2
            or not config["smoke_accepted_by_user"]):
        raise ValueError("Run configuration differs from registration")
    return manifest, config


def check_registration_commit():
    git = ["git", "-c", f"safe.directory={ROOT.as_posix()}"]
    head = subprocess.check_output([*git, "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    registered = subprocess.check_output([*git, "rev-parse", "phase5-prereg^{commit}"], cwd=ROOT, text=True).strip()
    if head != registered:
        raise ValueError("HEAD must equal the new phase5-prereg commit")
    changed = subprocess.check_output([*git, "diff", "--name-only", "phase5-prereg", "--",
        "scripts/phase5", "infra/entrypoints/critic.py", "infra/phase5_health.py",
        "docker-compose.phase5.yml", "reports/phase5/preregistration.md",
        "reports/phase5/sample_manifest.json", "reports/phase5/run_config.json"], cwd=ROOT)
    if changed:
        raise ValueError("Registered code or inputs changed; STOP")


def run_registered(root):
    from scripts.phase5.pipeline import completed
    manifest, config = load_registered()
    check_registration_commit()
    frozen_check()
    budget = Budget(root, cap=config["ledger_cap_usd"], provider_cap=config["provider_cap_usd"])
    with portalocker.Lock(str(root / "runner.lock"), timeout=1):
        pending = []
        for item in manifest["items"]:
            rec = completed(root / "records" / f"{item['item_id']}.json", item)
            if rec is not None:
                progress(root, rec, "heals.log")
            else:
                pending.append(item)
        with ThreadPoolExecutor(max_workers=config["concurrency"]) as pool:
            active = set()
            remaining = iter(pending)
            def submit():
                if budget.stopped():
                    return False
                item = next(remaining, None)
                if item is None:
                    return False
                active.add(pool.submit(invoke, item, root, config["heal_timeout_seconds"]))
                return True
            for _ in range(config["concurrency"]):
                submit()
            while active:
                done, active = wait(active, return_when=FIRST_COMPLETED)
                for future in done:
                    rec = future.result()
                    progress(root, rec, "heals.log")
                    submit()
        if budget.stopped():
            print("stopped: cap reached", flush=True)
        else:
            print("completed: all registered heal IDs have terminal records", flush=True)
        frozen_check()


def detach(root):
    load_registered()
    check_registration_commit()
    frozen_check()
    # Must remain detached from the terminal and its Windows job when VS Code exits.
    command = [sys.executable, "-m", "scripts.phase5.run", "--run", "--root", str(root)]
    root.mkdir(parents=True, exist_ok=True)
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_BREAKAWAY_FROM_JOB if os.name == "nt" else 0
    with (root / "runner.stdout.log").open("ab", buffering=0) as output:
        process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output,
            stderr=subprocess.STDOUT, close_fds=True, creationflags=flags, start_new_session=os.name != "nt")
    atomic_json(root / "runner.pid.json", dict(pid=process.pid, command=command,
                started_at=datetime.now(timezone.utc).isoformat()))
    print(f"Detached runner PID: {process.pid}", flush=True)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    # Disable optional framework telemetry before importing model libraries.
    # CI stages pinned local models; do not force global offline mode here.
    os.environ.update(HF_HUB_DISABLE_TELEMETRY="1",
                      LANGSMITH_TRACING="false", LANGCHAIN_TRACING_V2="false", LANGCHAIN_TRACING="false")
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--worker", type=Path)
    mode.add_argument("--smoke", action="store_true")
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--detach", action="store_true")
    parser.add_argument("--root", type=Path, default=RUNS)
    args = parser.parse_args()
    root = args.root.resolve()
    if root != RUNS.resolve():
        raise ValueError("All Phase 5 run state must stay under data/phase5/runs")
    root.mkdir(parents=True, exist_ok=True)
    if args.worker:
        worker(args.worker, root)
    elif args.smoke:
        smoke(root)
    elif args.detach:
        detach(root)
    else:
        run_registered(root)


if __name__ == "__main__":
    main()
