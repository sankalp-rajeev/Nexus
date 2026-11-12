"""Local DEV replay through the real collector/Kafka/classifier/Postgres path."""
import argparse
import os
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "sdk")]
import json
import platform
import subprocess
import threading
import time
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import numpy as np
import psycopg2
from confluent_kafka import Consumer, TopicPartition
from bench.llm import load_env
from services.critic.dev_adapter import dev_labels, dev_traces
from scripts.phase5.measurement import atomic_json

RAW = ROOT / "data/phase5/runs/l3_ingestion"
COMPOSE = ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.phase5.yml"]


def docker(*args):
    return subprocess.check_output(["docker", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL)


def summary(values):
    return dict(n=len(values), p50=float(np.quantile(values, .5)) if values else None,
                p99=float(np.quantile(values, .99)) if values else None)


def grows(samples, rate):
    tail = [s for s in samples if s["s"] >= samples[-1]["s"] - 120]
    slopes = {}
    for name in ("assembler", "classifier"):
        x, y = [s["s"] for s in tail], [s[name] for s in tail]
        slope = float(np.polyfit(x, y, 1)[0]) if len(x) > 1 else 0.0
        slopes[name] = dict(slope_events_s=slope, start=y[0], end=y[-1],
                           growing=slope > max(.1, .01 * rate) or y[-1] - y[0] > max(10, .02 * rate * samples[-1]["s"]))
    return slopes


def main(*, addon=False):
    raw_dir = RAW / "addon_30_40_60" if addon else RAW
    output = ROOT / ("results/phase5/ingestion_load_addon.json" if addon else "results/phase5/ingestion_load.json")
    rates = (30, 40, 60) if addon else (1, 5, 20, 80, 320, 1280)
    raw_dir.mkdir(parents=True, exist_ok=True)
    for name in ("critic", "healer"):
        state = docker("inspect", "--format", "{{.State.Status}}", f"nexus-phase5-nexus-{name}-1").strip()
        if state != "exited":
            raise RuntimeError("Paid consumers must remain stopped")
    load_env(str(ROOT / ".env"))
    items = json.loads((ROOT / "reports/phase5/sample_manifest.json").read_text(encoding="utf-8"))["items"][:20]
    ids = {i["trace_id"] for i in items}
    allowed = {r["trace_id"] for r in dev_labels(ROOT / "data/nexusbench/labels.csv")}
    if not ids <= allowed:
        raise ValueError("DEV whitelist failed")
    traces = dev_traces(ROOT / "data/nexusbench/traces.jsonl", ids)
    templates = [traces[i["trace_id"]] for i in items]
    prefix = "p5load_" + uuid4().hex[:8]
    db = lambda: psycopg2.connect(host="127.0.0.1", port=55433, dbname=os.getenv("POSTGRES_DB", "nexus"),
                      user=os.getenv("POSTGRES_USER", "nexus"), password=os.getenv("POSTGRES_PASSWORD", "nexus_dev_password"))
    with db() as conn, conn.cursor() as cur:
        cur.execute("CREATE TABLE IF NOT EXISTS phase5_load_detections (trace_id TEXT PRIMARY KEY, classification JSONB NOT NULL, persisted_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp())")
    sink = Consumer({"bootstrap.servers": "localhost:29092", "group.id": prefix, "enable.auto.commit": False})
    metadata = sink.list_topics(timeout=15)
    # Ensure the classifier's output topic exists before measuring.
    if "nexus.spans.classified" not in metadata.topics:
        raise RuntimeError("Classification output topic absent")
    parts = [TopicPartition("nexus.spans.classified", p) for p in metadata.topics["nexus.spans.classified"].partitions]
    for p in parts:
        p.offset = sink.get_watermark_offsets(p, timeout=5)[1]
    sink.assign(parts)
    starts, finishes, errors = {}, {}, []
    stop = threading.Event()

    def consume():
        try:
            conn = db()
            conn.autocommit = True
            while not stop.is_set():
                msg = sink.poll(.1)
                if msg is None:
                    continue
                if msg.error():
                    errors.append("sink_kafka_error")
                    continue
                result = json.loads(msg.value())
                tid = result["trace_id"]
                if not tid.startswith(prefix):
                    continue
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO phase5_load_detections (trace_id, classification) VALUES (%s,%s) ON CONFLICT DO NOTHING", (tid, json.dumps(result)))
                finishes[tid] = time.perf_counter()
            conn.close()
        except Exception as exc:
            errors.append(type(exc).__name__)
        finally:
            sink.close()

    thread = threading.Thread(target=consume, daemon=True)
    thread.start()
    monitors = {name: Consumer({"bootstrap.servers": "localhost:29092", "group.id": "nexus-"+name}) for name in ("assembler", "classifier")}
    rawparts = list(metadata.topics["nexus.spans.raw"].partitions)

    def lag(name):
        c = monitors[name]
        ps = c.committed([TopicPartition("nexus.spans.raw", p) for p in rawparts], timeout=5)
        return sum(max(0, c.get_watermark_offsets(p, timeout=5)[1] - max(0, p.offset)) for p in ps)

    counter = 0
    http_errors = []
    client = httpx.Client(timeout=30, trust_env=False)

    def send(template):
        nonlocal counter
        counter += 1
        tid = f"{prefix}_{counter}"
        spans = [s.model_dump(mode="json") for s in template.spans]
        spans.sort(key=lambda s: (bool(s["metadata"].get("final")), s["client_timestamp"]))
        mapping = {s["span_id"]: f"{tid}_{i}" for i, s in enumerate(spans)}
        for i, s in enumerate(spans):
            s.update(trace_id=tid, span_id=mapping[s["span_id"]], agent_name="phase5-load-dev", environment="phase5-load-dev",
                     parent_span_id=mapping.get(s["parent_span_id"]), server_timestamp=None)
            s["metadata"] = {**s["metadata"], "final": i == len(spans)-1}
        starts[tid] = time.perf_counter()
        try:
            resp = client.post("http://127.0.0.1:8000/v1/spans", json={"spans": spans})
            resp.raise_for_status()
            value = resp.json()
            if value["accepted"] != len(spans) or value["rejected"]:
                http_errors.append("partial_acceptance")
            return tid, len(spans), value["accepted"]
        except Exception as exc:
            http_errors.append(type(exc).__name__)
            return tid, len(spans), 0

    def drain(tids, timeout=600):
        deadline = time.perf_counter() + timeout
        while not all(t in finishes for t in tids) and time.perf_counter() < deadline and not errors:
            time.sleep(.25)
        return [t for t in tids if t not in finishes]

    result = dict(started_at=datetime.now(timezone.utc).isoformat(), prefix=prefix, steps=[],
                  protocol="reports/phase5/amendment_2.md", path="collector -> Kafka -> deployed classifier -> Kafka -> measurement Postgres sink; assembler -> Postgres in parallel",
                  API_calls=0, machine=dict(platform=platform.platform(), python=platform.python_version(),
                    host=json.loads(subprocess.check_output(["powershell", "-NoProfile", "-Command", "@{cpu=(Get-CimInstance Win32_Processor).Name; cores=(Get-CimInstance Win32_Processor).NumberOfCores; threads=(Get-CimInstance Win32_Processor).NumberOfLogicalProcessors; ram_bytes=(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory} | ConvertTo-Json"], text=True)),
                    docker=dict(cpus=int(docker("info", "--format", '{{.NCPU}}')), ram_bytes=int(docker("info", "--format", '{{.MemTotal}}')))),
                  raw_trace_count=20, unique_task_count=len({i["task_id"] for i in items}),
                  offered_rates=list(rates), add_on=addon,
                  criteria="unchanged amendment_2.md thresholds; final-120-second committed lag; >=98% acceptance; complete detection/persistence; no errors",
                  paid_consumers="verified stopped before sending")
    try:
        warm = [send(t)[0] for t in templates]
        missing = drain(warm)
        if missing or http_errors or errors:
            raise RuntimeError("Warmup failed; no measured load")
        logs = subprocess.check_output([*COMPOSE, "logs", "nexus-classifier"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL)
        if "NLI model failed to load" in logs:
            raise RuntimeError("Classifier NLI fallback invalidates headline load test")
        result["classifier_nli"] = "cross-encoder/nli-MiniLM2-L6-H768; cached model, no fallback"
        if not addon:
            result["pilot"] = dict(status="aborted_not_headline", reason="initial image lacked NLI cache and used built-in zero fallback",
                                  raw_diagnostic="data/phase5/runs/l3_ingestion/pilot_without_nli.json")
        print("warmup complete", flush=True)
        for rate in rates:
            begin = time.perf_counter()
            tids, offered, accepted, samples, resources = [], 0, 0, [], []
            next_sample = begin
            initial_errors = len(errors) + len(http_errors)
            while time.perf_counter() - begin < 180:
                now = time.perf_counter()
                if now >= next_sample:
                    samples.append(dict(s=now-begin, **{n:lag(n) for n in monitors}))
                    resources.append(docker("stats", "--no-stream", "--format", '{{json .}}', *["nexus-phase5-"+n+"-1" for n in ("nexus-collector", "kafka", "nexus-classifier", "nexus-assembler", "postgres")]))
                    next_sample = now + 10
                if now - begin >= offered / rate:
                    tid, n, ok = send(templates[len(tids) % len(templates)])
                    tids.append(tid)
                    offered += n
                    accepted += ok
                else:
                    time.sleep(min(.02, max(0, offered/rate-(now-begin))))
            elapsed = time.perf_counter()-begin
            samples.append(dict(s=elapsed, **{n:lag(n) for n in monitors}))
            missing = drain(tids)
            with db() as conn, conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM traces WHERE trace_id = ANY(%s)", (tids,))
                assembled = cur.fetchone()[0]
            slopes = grows(samples, rate)
            stable = not any(s["growing"] for s in slopes.values())
            row = dict(offered_rate_events_s=rate, hold_s=elapsed, offered_events=offered, accepted_events=accepted,
                       accepted_events_s=accepted/elapsed, offered_traces=len(tids), detected_traces=len(tids)-len(missing),
                       assembled_traces_at_detection_drain=assembled, missing_detections=len(missing),
                       detection_latency_ms=summary([(finishes[t]-starts[t])*1000 for t in tids if t in finishes]),
                       committed_lag=samples, lag_growth=slopes, errors=len(errors)+len(http_errors)-initial_errors,
                       sustainable=stable and accepted/elapsed >= .98*rate and not missing and assembled==len(tids) and len(errors)+len(http_errors)==initial_errors)
            result["steps"].append(row)
            atomic_json(raw_dir / f"resources_{rate}.json", resources)
            atomic_json(raw_dir / f"latencies_{rate}.json", {t:(finishes[t]-starts[t])*1000 if t in finishes else None for t in tids})
            atomic_json(output, result)
            print(json.dumps({k:row[k] for k in ("offered_rate_events_s", "hold_s", "accepted_events_s", "detected_traces", "missing_detections", "sustainable", "detection_latency_ms", "lag_growth")}), flush=True)
            if not row["sustainable"] and not addon:
                break
    finally:
        stop.set()
        thread.join(10)
        client.close()
        for c in monitors.values():
            c.close()
        result.update(ended_at=datetime.now(timezone.utc).isoformat(), http_errors=http_errors, sink_errors=errors,
                      max_sustained_events_s=max([s["accepted_events_s"] for s in result["steps"] if s["sustainable"]], default=None))
        result["paid_consumers_final"] = {n:docker("inspect", "--format", "{{.State.Status}}", f"nexus-phase5-nexus-{n}-1").strip() for n in ("critic","healer")}
        atomic_json(output, result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--addon", action="store_true", help="Run all 30/40/60 steps, retaining the original experiment")
    main(addon=parser.parse_args().addon)
