"""L4: paired replay of the registered 20 DEV traces, with no provider calls."""
from collections import Counter
from contextlib import contextmanager
import ctypes
from datetime import datetime, timezone
import gc
from functools import lru_cache
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import multiprocessing as mp
import os
from pathlib import Path
import platform
import sqlite3
import sys
import threading
import time
import tracemalloc

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "sdk"))

import numpy as np
import nexus_agent as nexus
from services.critic.dev_adapter import dev_labels, dev_traces

RAW = ROOT / "data/phase5/runs/l4"
SEED = 202611117
PASSES = 18
WARMUPS = 2


def local_only():
    os.environ.update(NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost",
                      LANGSMITH_TRACING="false", LANGCHAIN_TRACING_V2="false")
    def guard(event, args):
        if event in {"socket.connect", "socket.bind"} and isinstance(args[1], tuple):
            if args[1][0] not in {"127.0.0.1", "::1", "localhost"}:
                raise RuntimeError("L4 external network blocked")
        if event == "socket.getaddrinfo" and args[0] not in {"127.0.0.1", "::1", "localhost", None}:
            raise RuntimeError("L4 external DNS blocked")
    sys.addaudithook(guard)


def source_fields(span):
    return dict(kind=span.span_type.value, input=span.input or "", output=span.output,
                metadata=dict(span.metadata), error_type=span.error_type, error_message=span.error_message)


def load_workload():
    items = json.loads((ROOT / "reports/phase5/sample_manifest.json").read_text(encoding="utf-8"))["items"][:20]
    ids = {i["trace_id"] for i in items}
    labels = {r["trace_id"]: r for r in dev_labels(ROOT / "data/nexusbench/labels.csv") if r["trace_id"] in ids}
    if set(labels) != ids or any(r["split"] != "dev" for r in labels.values()):
        raise ValueError("Registered workload must be DEV-only")
    traces = dev_traces(ROOT / "data/nexusbench/traces.jsonl", ids)
    tasks = []
    for item in items:
        trace = traces[item["trace_id"]]
        steps = sorted((s for s in trace.spans if s.span_type.value == "agent_step" and s.metadata.get("role") in {"planner", "actor"}), key=lambda s: s.client_timestamp)
        roots = [s for s in trace.spans if s.span_type.value == "agent_step" and s.metadata.get("role") == "root"]
        if len(roots) != 1 or not steps:
            raise ValueError("Trace lacks a single task root or planner/actor steps")
        groups = []
        assigned = set()
        for step in steps:
            children = sorted((s for s in trace.spans if s.parent_span_id == step.span_id), key=lambda s: s.client_timestamp)
            if not children or any(s.span_type.value not in {"llm_call", "tool_call", "memory_read"} for s in children):
                raise ValueError("Unexpected recorded step hierarchy")
            assigned.update(s.span_id for s in children)
            groups.append(dict(span=source_fields(step), children=[source_fields(s) for s in children]))
        observed = {s.span_id for s in trace.spans if s.span_type.value in {"llm_call", "tool_call", "memory_read"}}
        if assigned != observed:
            raise ValueError("A recorded response/tool event would be dropped")
        tasks.append(dict(occurrence_id=item["item_id"], task_id=item["task_id"], trace_id=item["trace_id"],
                          root=source_fields(roots[0]), steps=groups))
    if len(tasks) != 20 or sum(len(t["steps"]) for t in tasks) != 113:
        raise ValueError("Registered 20-task/113-step workload differs")
    return tasks


class RecordedLLM:
    def __init__(self, task):
        self.expected = [e for s in task["steps"] for e in s["children"] if e["kind"] == "llm_call"]
        self.index = 0
        self.transcript = []

    def complete(self, prompt):
        event = self.expected[self.index]
        if event["input"] != prompt:
            raise ValueError("Replay prompt order changed")
        self.index += 1
        self.transcript.append((prompt, event["output"]))
        return event["output"]


def replay_event(event, llm):
    output = llm.complete(event["input"]) if event["kind"] == "llm_call" else event["output"]
    # Both arms perform identical parsing/history work, including malformed replies.
    try:
        parsed = json.loads(output) if output else None
    except (ValueError, TypeError):
        parsed = None
    return event["kind"], output, parsed, event["error_type"]


@contextmanager
def captured(event, phase):
    metadata = {**event["metadata"], "bench_phase": phase, "recorded_response_replay": True}
    with nexus.span(event["kind"], input=event["input"], **metadata) as handle:
        handle.set_output(event["output"])
        handle.error_type = event["error_type"]
        handle.error_message = event["error_message"]
        yield


def execute_task(task, sdk_on, phase):
    llm = RecordedLLM(task)
    durations, output = [], []
    def run_steps():
        for step in task["steps"]:
            started = time.perf_counter_ns()
            if sdk_on:
                with captured(step["span"], phase):
                    values = []
                    for event in step["children"]:
                        with captured(event, phase):
                            values.append(replay_event(event, llm))
            else:
                values = [replay_event(event, llm) for event in step["children"]]
            durations.append((time.perf_counter_ns() - started) / 1e6)
            output.append(values)
    started = time.perf_counter_ns()
    if sdk_on:
        with captured(task["root"], phase):
            run_steps()
    else:
        run_steps()
    elapsed = (time.perf_counter_ns() - started) / 1e6
    if llm.index != len(llm.expected):
        raise ValueError("Not every recorded LLM response was consumed")
    return dict(step_ms=durations, task_ms=elapsed, signature=output, transcript=llm.transcript)


def collector_process(pipe):
    local_only()
    state = dict(ids={}, counts=Counter(), duplicates=0)
    lock = threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path != "/v1/spans":
                self.send_error(404)
                return
            with lock:
                for span in body["spans"]:
                    phase = span["metadata"]["bench_phase"]
                    ids = state["ids"].setdefault(phase, set())
                    state["duplicates"] += span["span_id"] in ids
                    ids.add(span["span_id"])
                    state["counts"][phase] += 1
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
        def log_message(self, *args):
            pass
    class Server(ThreadingHTTPServer):
        allow_reuse_address = True
        daemon_threads = True
    server, thread, port = None, None, 0
    def start():
        nonlocal server, thread, port
        server = Server(("127.0.0.1", port), Handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        thread.start()
    def stop():
        nonlocal server
        if server:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            server = None
    try:
        start()
        pipe.send(dict(url=f"http://127.0.0.1:{port}"))
        while True:
            command = pipe.recv()
            if command == "stop":
                stop()
                pipe.send(dict(stopped=True))
            elif command == "start":
                if server is None:
                    start()
                pipe.send(dict(started=True))
            elif command == "stats":
                with lock:
                    pipe.send(dict(counts=dict(state["counts"]), duplicates=state["duplicates"]))
            elif isinstance(command, dict) and "ids" in command:
                with lock:
                    pipe.send(sorted(state["ids"].get(command["ids"], set())))
            elif command == "close":
                break
    finally:
        stop()
        pipe.close()


class Collector:
    def __init__(self):
        self.pipe, child = mp.Pipe()
        self.process = mp.Process(target=collector_process, args=(child,), daemon=True)
        self.process.start()
        if not self.pipe.poll(30):
            raise RuntimeError("Collector fixture startup timed out")
        self.url = self.pipe.recv()["url"]

    def command(self, value):
        self.pipe.send(value)
        if not self.pipe.poll(30):
            raise RuntimeError("Collector fixture command timed out")
        return self.pipe.recv()

    def close(self):
        if self.process.is_alive():
            self.pipe.send("close")
            self.process.join(timeout=10)
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(timeout=5)
        self.pipe.close()


def sdk_client(url):
    return nexus.init(agent_name="phase5-sdk-replay", collector_url=url, environment="phase5-l4-replay")


def summary(values):
    a = np.asarray(values, dtype=float)
    return dict(n=len(a), p50_ms=float(np.quantile(a, .5)), p99_ms=float(np.quantile(a, .99)), max_ms=float(a.max()))


def timing(workload, url, label):
    rng = np.random.default_rng(SEED)
    steps = {"off": [], "on": []}
    tasks = {"off": [], "on": []}
    paired_steps, paired_tasks, orders = [], [], []
    setup_s = drain_s = 0.0
    completed = Counter()
    for pass_index in range(WARMUPS + PASSES):
        gc.collect()
        orders_for_pass = np.asarray([0, 1] * 10)
        rng.shuffle(orders_for_pass)
        for index, task in enumerate(workload):
            order = ["off", "on"] if orders_for_pass[index] == 0 else ["on", "off"]
            pair = {}
            for arm in order:
                phase = f"{label}:{'warm' if pass_index < WARMUPS else 'measured'}:{pass_index}:{index}"
                client = None
                started = time.perf_counter()
                if arm == "on":
                    client = sdk_client(url)
                elif nexus.is_initialized():
                    raise RuntimeError("SDK off must have no active SDK client")
                setup_s += time.perf_counter() - started
                try:
                    pair[arm] = execute_task(task, arm == "on", phase)
                finally:
                    started = time.perf_counter()
                    nexus.shutdown()
                    drain_s += time.perf_counter() - started
                if client is not None and client.stats["queued"]:
                    raise RuntimeError("SDK queue was not drained between paired arms")
            if pair["off"]["signature"] != pair["on"]["signature"] or pair["off"]["transcript"] != pair["on"]["transcript"]:
                raise RuntimeError("Paired replay outputs or LLM requests/responses differ")
            if pass_index >= WARMUPS:
                for arm in ("off", "on"):
                    steps[arm] += pair[arm]["step_ms"]
                    tasks[arm].append(pair[arm]["task_ms"])
                    completed[arm] += len(pair[arm]["step_ms"])
                paired_steps += (np.asarray(pair["on"]["step_ms"]) - pair["off"]["step_ms"]).tolist()
                paired_tasks.append(pair["on"]["task_ms"] - pair["off"]["task_ms"])
                orders.append("-".join(order))
        print(f"{label}: pass {pass_index + 1}/{WARMUPS + PASSES} complete", flush=True)
    raw = dict(step_ms=steps, task_ms=tasks, paired_step_ms=paired_steps, paired_task_ms=paired_tasks, arm_orders=orders)
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / f"{label}_timings.json").write_text(json.dumps(raw), encoding="utf-8")
    return dict(steps_per_arm=dict(completed), warmup_steps_discarded_per_arm=226,
        task_pairs=len(paired_tasks), output_or_response_mismatches=0, exceptions=0,
        sdk_off=summary(steps["off"]), sdk_on=summary(steps["on"]),
        paired_added_per_step=summary(paired_steps), paired_added_per_task=summary(paired_tasks),
        sdk_client_setup_total_s=setup_s, flush_shutdown_total_s=drain_s,
        arm_order_counts=dict(Counter(orders)), gc_enabled=gc.isenabled())


@lru_cache(maxsize=1)
def rss_reader():
    if os.name == "nt":
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [(name, ctypes.c_size_t) for name in (
                "peak_working_set", "working_set", "quota_peak_paged", "quota_paged", "quota_peak_nonpaged", "quota_nonpaged", "pagefile", "peak_pagefile", "private")]
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        def read():
            counter = Counters()
            counter.cb = ctypes.sizeof(counter)
            if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counter), counter.cb):
                raise ctypes.WinError(ctypes.get_last_error())
            return counter.working_set
        return read
    return lambda: int(Path("/proc/self/statm").read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE")


def rss_bytes():
    return rss_reader()()


def memory_worker(pipe, url, arm, index):
    local_only()
    try:
        workload = load_workload()
        for warm in range(WARMUPS):
            if arm == "on":
                sdk_client(url)
            for task in workload:
                execute_task(task, arm == "on", f"memory-warm:{arm}:{index}:{warm}")
            nexus.shutdown()
        gc.collect()
        baseline = rss_bytes()
        sampled_peak = baseline
        sample_count = 0
        previous = interval_total = interval_max = 0.0
        stop = threading.Event()
        def sample():
            nonlocal sampled_peak, sample_count, previous, interval_total, interval_max
            while not stop.is_set():
                sampled_peak = max(sampled_peak, rss_bytes())
                now = time.perf_counter()
                if previous:
                    interval_total += now - previous
                    interval_max = max(interval_max, now - previous)
                previous = now
                sample_count += 1
                stop.wait(.001)
        tracemalloc.start()
        sampler = threading.Thread(target=sample, daemon=True)
        sampler.start()
        if arm == "on":
            sdk_client(url)
        count = 0
        for p in range(PASSES):
            for task in workload:
                count += len(execute_task(task, arm == "on", f"memory:{arm}:{index}")["step_ms"])
        sampled_peak = max(sampled_peak, rss_bytes())
        nexus.shutdown()
        gc.collect()
        post = rss_bytes()
        current, peak = tracemalloc.get_traced_memory()
        stop.set()
        sampler.join(timeout=5)
        tracemalloc.stop()
        pipe.send(dict(arm=arm, steps=count, baseline_rss_bytes=baseline, peak_rss_bytes=sampled_peak,
            post_cleanup_rss_bytes=post, peak_incremental_rss_bytes=sampled_peak - baseline,
            traced_heap_peak_bytes=peak, traced_heap_after_cleanup_bytes=current,
            rss_sample_count=sample_count, rss_sample_interval_mean_ms=interval_total * 1000 / max(sample_count - 1, 1),
            rss_sample_interval_max_ms=interval_max * 1000))
    except BaseException as exc:
        pipe.send(dict(error=type(exc).__name__))
    finally:
        nexus.shutdown()
        pipe.close()


def memory_trials(url):
    raw = {"off": [], "on": []}
    for index in range(3):
        for arm in (["off", "on"] if index % 2 == 0 else ["on", "off"]):
            parent, child = mp.Pipe()
            process = mp.Process(target=memory_worker, args=(child, url, arm, index))
            process.start()
            if not parent.poll(120):
                process.terminate()
                process.join(timeout=5)
                raise RuntimeError("Memory probe timed out")
            result = parent.recv()
            process.join(timeout=10)
            if "error" in result or process.exitcode != 0:
                raise RuntimeError(f"Memory probe failed: {result.get('error')}")
            raw[arm].append(result)
            parent.close()
            print(f"Memory trial {index + 1}/3 {arm} complete", flush=True)
    (RAW / "memory_trials.json").write_text(json.dumps(raw), encoding="utf-8")
    result = {}
    for arm in raw:
        result[arm] = {}
        for key in ("baseline_rss_bytes", "peak_rss_bytes", "post_cleanup_rss_bytes", "peak_incremental_rss_bytes", "traced_heap_peak_bytes", "traced_heap_after_cleanup_bytes", "rss_sample_count", "rss_sample_interval_mean_ms", "rss_sample_interval_max_ms"):
            values = [r[key] for r in raw[arm]]
            result[arm][key] = dict(median=float(np.median(values)), minimum=min(values), maximum=max(values))
    result["added_median_peak_rss_bytes"] = result["on"]["peak_rss_bytes"]["median"] - result["off"]["peak_rss_bytes"]["median"]
    result["added_median_traced_heap_peak_bytes"] = result["on"]["traced_heap_peak_bytes"]["median"] - result["off"]["traced_heap_peak_bytes"]["median"]
    result["trials_per_arm"] = 3
    result["steps_per_trial"] = 2034
    return result


def recovery_probe(workload, collector):
    phase = "recovery-outage"
    collector.command("stop")
    client = sdk_client(collector.url)
    original = client._exporter.export
    lock = threading.Lock()
    observed = dict(failed_batches=0, failed_events=0, accepted_events=0, in_flight=0)
    failed_ids = set()
    first_failure = threading.Event()
    held_batch = threading.Event()
    release = threading.Event()
    held_events = 0
    def observe(batch):
        nonlocal held_events
        with lock:
            observed["in_flight"] += 1
        try:
            if first_failure.is_set() and not release.is_set():
                held_events = len(batch.spans)
                held_batch.set()
                if not release.wait(timeout=30):
                    raise RuntimeError("Recovery scheduling barrier timed out")
            ok = original(batch)
            with lock:
                if ok:
                    observed["accepted_events"] += len(batch.spans)
                else:
                    observed["failed_batches"] += 1
                    observed["failed_events"] += len(batch.spans)
                    failed_ids.update(s.span_id for s in batch.spans)
                    first_failure.set()
            return ok
        finally:
            with lock:
                observed["in_flight"] -= 1
    client._exporter.export = observe
    generated_per_pass = sum(1 + sum(1 + len(s["children"]) for s in t["steps"]) for t in workload)
    try:
        for pass_index in range(PASSES):
            for task_index, task in enumerate(workload):
                execute_task(task, True, phase)
                if pass_index == task_index == 0 and not first_failure.wait(timeout=5):
                    raise RuntimeError("No failed HTTP attempt observed while collector was stopped")
        if not held_batch.wait(timeout=5):
            raise RuntimeError("No pending batch observed for recovery")
        queued_at_restart = client.stats["queued"]
        dropped_at_restart = client.stats["dropped"]
        with lock:
            failed_before_restart = observed["failed_events"]
        collector.command("start")
        release.set()
        nexus.flush()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with lock:
                inflight = observed["in_flight"]
            if not client.stats["queued"] and not inflight:
                break
            time.sleep(.01)
        old_received = set(collector.command({"ids": phase}))
        for task in workload:
            execute_task(task, True, "recovery-fresh")
        nexus.shutdown()
        old_received_final = set(collector.command({"ids": phase}))
        fresh_received = set(collector.command({"ids": "recovery-fresh"}))
        stats = client.stats
        generated = PASSES * generated_per_pass
        return dict(outage_steps=2034, generated_outage_events=generated, queued_events_at_restart=queued_at_restart,
            held_unattempted_batch_events=held_events, recovery_only_scheduling_barrier=True,
            queue_full_drops_at_restart=dropped_at_restart, failed_events_before_restart=failed_before_restart,
            failed_export_batches=observed["failed_batches"], failed_export_events=observed["failed_events"],
            old_events_received_after_restart=len(old_received), old_events_received_final=len(old_received_final),
            failed_event_ids_seen_after_restart=len(failed_ids & old_received_final),
            lost_outage_events=generated - len(old_received_final),
            fresh_recovery_steps=113, expected_fresh_events=generated_per_pass,
            fresh_recovery_events_received=len(fresh_received), final_queue_size=stats["queued"],
            final_queue_full_dropped=stats["dropped"],
            accounted_loss_matches=generated - len(old_received_final) == observed["failed_events"] + stats["dropped"],
            explanation="Failed HTTP batches are dropped without retry/persistence; events still queued when service returns can export, but previously failed batches are not replayed.")
    finally:
        release.set()
        collector.command("start")
        nexus.shutdown()


def write_report(result):
    healthy, outage, memory, recovery = (result[k] for k in ("collector_healthy", "collector_stopped", "memory", "recovery"))
    lines = ["", "## Part B: L4 SDK overhead with recorded DEV response replay", "",
        "Amendment 1 was committed before execution, including the user's 20-task recorded-response clarification. "
        "The exact first 20 manifest occurrences (20 DEV traces, 18 unique task IDs) are retained. "
        "Recorded LLM responses, tool/memory outputs and expected errors are replayed on identical scripted paths; "
        "this does not re-run agent/gate decisions. There are no live provider calls or API spend.", "",
        "Two complete warm-up passes (226 steps/arm) are discarded. Eighteen measured full-task passes give "
        "2,034 steps/arm and 360 task pairs in each collector condition. SDK-off/on task order is balanced "
        "AB/BA with seed 202611117. SDK off has no active client/exporter; SDK on uses the unchanged SDK "
        "and actual recorded span density. A separate loopback-only collector fixture excludes Kafka/backend work.", "",
        "### Per-step latency (milliseconds)", "",
        "| Collector | SDK off p50 / p99 | SDK on p50 / p99 | Paired added p50 / p99 | Paired added maximum |", "|---|---:|---:|---:|---:|"]
    for label, r in (("healthy", healthy), ("stopped", outage)):
        off, on, added = (r[k] for k in ("sdk_off", "sdk_on", "paired_added_per_step"))
        lines.append(f"| {label} | {off['p50_ms']:.6f} / {off['p99_ms']:.6f} | {on['p50_ms']:.6f} / {on['p99_ms']:.6f} | {added['p50_ms']:.6f} / {added['p99_ms']:.6f} | {added['max_ms']:.6f} |")
    lines += ["", "Paired additions are on-minus-off for the same recorded step; negative scheduling differences are retained. "
        "Client setup, flush and shutdown are outside the per-step timer; task-root capture is included in separately "
        "reported paired task duration in the JSON. Memory tracing is run separately from these latency measurements.", "",
        f"Across all 400 SDK-on task lifecycles per condition (including warm-ups), flush/shutdown took "
        f"{healthy['flush_shutdown_total_s']:.3f}s healthy versus {outage['flush_shutdown_total_s']:.3f}s stopped. "
        "Those waits are outside per-step timing: the fail-open bound concerns foreground capture/replay, "
        "not zero-cost client shutdown or draining. Failed HTTP batches in the timed outage phase were dropped; "
        "the event-level recovery counts below come from a separate observed probe.", "",
        "### Added memory", "",
        "Three fresh-process trials per arm replay the same 20 tasks, with two warm-up passes and 2,034 measured "
        "steps/trial. RSS is agent-process-only, sampled at a requested 1 ms interval; Python heap uses tracemalloc. "
        "The collector runs in a separate process and its memory is excluded.", "",
        "| Metric | SDK off median MiB | SDK on median MiB | Added median MiB |", "|---|---:|---:|---:|"]
    for key in ("peak_rss_bytes", "traced_heap_peak_bytes"):
        off, on = memory["off"][key]["median"], memory["on"][key]["median"]
        label = "sampled peak RSS" if key == "peak_rss_bytes" else "Python traced-heap peak"
        lines.append(f"| {label} | {off/2**20:.3f} | {on/2**20:.3f} | {(on-off)/2**20:.3f} |")
    lines += ["", "The JSON also reports baseline/post-cleanup RSS, incremental peak RSS, realized sampler intervals and trial min/max. "
        f"Although 1 ms was requested, realized mean RSS sample intervals had medians "
        f"{memory['off']['rss_sample_interval_mean_ms']['median']:.2f} ms off and "
        f"{memory['on']['rss_sample_interval_mean_ms']['median']:.2f} ms on under Windows scheduling/GIL contention. "
        "Sampled RSS peaks can miss short spikes; Python traced-heap peaks are separately tracked. "
        "These are workload-specific process/heap measurements, not a long-run leak bound.", "",
        "### Fail-open and recovery", "",
        f"Collector listener closed: {outage['steps_per_arm']['on']}/{outage['steps_per_arm']['on']} SDK-on steps "
        f"finished with {outage['exceptions']} exceptions and {outage['output_or_response_mismatches']} replay mismatches. "
        f"The predeclared paired-added latency bound (p99 <=5 ms, max <=100 ms) **{'passed' if result['fail_open_bound_passed'] else 'failed'}**.", ""]
    for key, value in recovery.items():
        if key != "explanation":
            lines.append(f"- `{key}`: {value}")
    lines += ["", "The recovery-only scheduling barrier held one unattempted batch after a real failed export; "
        "the listener then restarted and the held/queued events were released. This was outside latency and memory "
        "measurements; the retained queue depth is controlled test setup, not a natural-outage backlog estimate.", "",
        recovery["explanation"], "The queue-full drop counter alone excludes failed HTTP batches; "
        "the observer explicitly counted those losses. Fresh recovery events and retained pending events are "
        "distinguished from previously failed batches. The collector fixture was closed in cleanup; the user's "
        "Nexus stack and SDK source were not changed.", "",
        "Limits: local Windows host, recorded SDK-visible payloads, asynchronous default SDK settings and loopback "
        "collector. This is not provider latency, real tool execution or production backend throughput. "
        "Only aggregate results are committed; raw vectors/event identifiers stay ignored under `data/phase5/runs/l4/`.", ""]
    path = ROOT / "reports/phase5/results.md"
    current = path.read_text(encoding="utf-8").split("\n## Part B:", 1)[0]
    path.write_text(current.rstrip() + "\n" + "\n".join(lines), encoding="utf-8")


def budget_fingerprint():
    path = ROOT / "data/phase5/runs/budget.sqlite3"
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        count = conn.execute("SELECT count(*) FROM calls").fetchone()[0]
        spent, provider = conn.execute("SELECT spent,provider_spent FROM budget WHERE id=1").fetchone()
    return dict(api_attempts=count, ledger_usd=spent, provider_usd=provider)


def main():
    local_only()
    before = budget_fingerprint()
    RAW.mkdir(parents=True, exist_ok=True)
    workload = load_workload()
    collector = Collector()
    try:
        healthy = timing(workload, collector.url, "collector_healthy")
        memory = memory_trials(collector.url)
        collector.command("stop")
        outage = timing(workload, collector.url, "collector_stopped")
        collector.command("start")
        recovery = recovery_probe(workload, collector)
        sink = collector.command("stats")
    finally:
        nexus.shutdown()
        collector.close()
    after = budget_fingerprint()
    if before != after:
        raise RuntimeError("Provider ledger changed during L4; zero-spend verification failed")
    sdk_paths = ["client.py", "config.py", "decorators.py", "models.py", "exporters/http.py", "__init__.py"]
    result = dict(experiment_id="phase5-L4-recorded-response-replay", generated_at=datetime.now(timezone.utc).isoformat(),
        methodology=dict(seed=SEED, warmup_passes_discarded=WARMUPS, measured_passes=PASSES,
            manifest_occurrences=20, unique_dev_traces=20, unique_task_ids=18, agent_steps_per_pass=113,
            steps_per_arm=2034, task_pairing="same recorded task, balanced random AB/BA; paired step indices",
            network="loopback only; deterministic recorded DEV LLM/tool response replay; zero provider calls",
            collector="separate-process /v1/spans HTTP fixture; stopped listener for outage; no Kafka/downstream work",
            sdk_defaults=dict(async_export=True, export_timeout_ms=200, flush_interval_ms=100, max_batch_size=50, max_queue_size=10000),
            memory="three fresh processes/arm; RSS sampler requested 1ms; separate tracemalloc probe",
            runtime=platform.python_version(), platform=platform.platform(),
            workload_sha256=hashlib.sha256(json.dumps(workload, sort_keys=True).encode()).hexdigest(),
            sdk_source_sha256={p: hashlib.sha256((ROOT / "sdk/nexus_agent" / p).read_bytes()).hexdigest() for p in sdk_paths}),
        collector_healthy=healthy, collector_stopped=outage, memory=memory, recovery=recovery,
        duplicate_events_at_collector=sink["duplicates"],
        fail_open_bound_passed=outage["paired_added_per_step"]["p99_ms"] <= 5 and outage["paired_added_per_step"]["max_ms"] <= 100,
        api_spend_usd=0.0, no_api_spend_verification=dict(before=before, after=after, unchanged=before == after))
    (ROOT / "results/phase5/sdk_overhead.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    write_report(result)
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    mp.freeze_support()
    if "--render-existing" in sys.argv:
        path = ROOT / "results/phase5/sdk_overhead.json"
        result = json.loads(path.read_text(encoding="utf-8"))
        raw = json.loads((RAW / "memory_trials.json").read_text(encoding="utf-8"))
        for arm in ("off", "on"):
            for key in ("rss_sample_count", "rss_sample_interval_mean_ms", "rss_sample_interval_max_ms"):
                values = [r[key] for r in raw[arm]]
                result["memory"][arm][key] = dict(median=float(np.median(values)), minimum=min(values), maximum=max(values))
        path.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        write_report(result)
        print("Rendered saved L4 aggregates; no measurements or network calls performed.")
    else:
        main()
