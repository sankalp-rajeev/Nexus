"""Phase 3 end-to-end check.

Produces spans for 3 traces (NORMAL, TOOL_MISFIRE, HALLUCINATION) to
nexus.spans.raw, runs the assembler + classifier in background threads, then
verifies:
  * traces + spans land in Postgres
  * a non-NORMAL Alert lands in nexus.alerts for each failing trace
  * the NORMAL trace produces no alert

    set KAFKA_BOOTSTRAP_SERVERS=localhost:29092
    python tests/e2e/run_phase3_e2e.py
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "sdk"))

os.environ.setdefault("KAFKA_BOOTSTRAP_SERVERS", "localhost:29092")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

from confluent_kafka import Consumer, Producer  # noqa: E402

from nexus_agent.models import CompleteTrace, FailureType, Span, SpanType, TraceStatus  # noqa: E402

from services.assembler.consumer import AssemblerService  # noqa: E402
from services.assembler.db import AssemblerDB  # noqa: E402
from services.classifier.consumer import ClassifierService, TOPIC_ALERTS  # noqa: E402
from services.classifier.main import load_classifier  # noqa: E402
from services.common.trace_buffer import TraceBuffer  # noqa: E402

RUN = int(time.time())
TOPIC_RAW = "nexus.spans.raw"


def _span(tid, k, stype, inp, out=None, *, err=None, tool=None, final=False) -> Span:
    md = {}
    if tool:
        md["tool_name"] = tool
    if final:
        md["final"] = True
    base = datetime.now(timezone.utc) + timedelta(milliseconds=100 * k)
    return Span(span_id=f"{tid}_{k:02d}", trace_id=tid, agent_name="e2e-agent", span_type=stype,
                input=inp, output=out, duration_ms=90.0, error_type=err,
                error_message="error" if err else None, metadata=md,
                client_timestamp=base, server_timestamp=base, sdk_version="1.0.0")


def _build_traces():
    norm = f"e2e_{RUN}_norm"
    mis = f"e2e_{RUN}_misfire"
    hall = f"e2e_{RUN}_hall"
    traces = {
        (norm, FailureType.NORMAL): [
            _span(norm, 0, SpanType.AGENT_STEP, "task: research GDP figures", "plan: search then summarize"),
            _span(norm, 1, SpanType.TOOL_CALL, "query: GDP 2026", "found 3 reports", tool="web_search"),
            _span(norm, 2, SpanType.LLM_CALL, "summarize GDP figures", "GDP shows steady growth, consistent summary", final=True),
        ],
        (mis, FailureType.TOOL_MISFIRE): [
            _span(mis, 0, SpanType.AGENT_STEP, "task: lookup record", "will call db"),
            _span(mis, 1, SpanType.TOOL_CALL, "", None, err="ToolError", tool="db_lookup"),
            _span(mis, 2, SpanType.TOOL_CALL, "", None, err="ToolError", tool="db_lookup", final=True),
        ],
        (hall, FailureType.HALLUCINATION): [
            _span(hall, 0, SpanType.RETRIEVAL, "query: optimize SQL for orders", "docs about SQL optimization"),
            _span(hall, 1, SpanType.LLM_CALL, "answer using SQL context", "a recipe for tiramisu with mascarpone, unrelated", final=True),
        ],
    }
    return traces


def _produce(traces):
    p = Producer({"bootstrap.servers": os.environ["KAFKA_BOOTSTRAP_SERVERS"]})
    n = 0
    for (tid, _label), spans in traces.items():
        for s in spans:
            p.produce(TOPIC_RAW, key=tid.encode(), value=s.model_dump_json().encode())
            n += 1
            p.poll(0)
    p.flush(5)
    return n


def _collect_alerts(trace_ids, timeout=8):
    c = Consumer({"bootstrap.servers": os.environ["KAFKA_BOOTSTRAP_SERVERS"],
                  "group.id": f"e2e-alert-reader-{RUN}", "auto.offset.reset": "earliest"})
    c.subscribe([TOPIC_ALERTS])
    found = {}
    deadline = time.time() + timeout
    while time.time() < deadline:
        msg = c.poll(1.0)
        if msg is None or msg.error():
            continue
        data = json.loads(msg.value())
        if data.get("trace_id") in trace_ids:
            found[data["trace_id"]] = data["failure_type"]
    c.close()
    return found


def main() -> int:
    traces = _build_traces()
    ids_by_label = {label: tid for (tid, label) in traces}
    our_ids = set(ids_by_label.values())

    asm = AssemblerService(buffer=TraceBuffer(timeout_seconds=3))
    clf = ClassifierService(load_classifier(), buffer=TraceBuffer(timeout_seconds=3))
    threading.Thread(target=asm.run, daemon=True).start()
    threading.Thread(target=clf.run, daemon=True).start()
    time.sleep(3)  # let consumers join the group

    print(f"producing spans for {len(traces)} traces ...")
    n = _produce(traces)
    print(f"produced {n} spans to {TOPIC_RAW}")

    # Wait for the assembler to persist our traces.
    db = AssemblerDB(); db.connect()
    persisted = {}
    deadline = time.time() + 30
    while time.time() < deadline:
        with db._conn.cursor() as cur:
            cur.execute("SELECT trace_id, span_count FROM traces WHERE trace_id = ANY(%s)", (list(our_ids),))
            persisted = dict(cur.fetchall())
        if len(persisted) == len(our_ids):
            break
        time.sleep(1)

    with db._conn.cursor() as cur:
        cur.execute("SELECT trace_id, count(*) FROM spans WHERE trace_id = ANY(%s) GROUP BY trace_id", (list(our_ids),))
        span_counts = dict(cur.fetchall())

    alerts = _collect_alerts(our_ids)
    asm.stop(); clf.stop()
    db.close()

    # ---- verification ----
    ok = True
    print("\n--- Postgres ---")
    for label, tid in ids_by_label.items():
        present = tid in persisted
        sc = span_counts.get(tid, 0)
        print(f"  {label.value:14s} trace={present} spans={sc}")
        ok = ok and present and sc == len(traces[(tid, label)])

    print("\n--- Alerts (nexus.alerts) ---")
    for label, tid in ids_by_label.items():
        alerted = alerts.get(tid)
        expected_alert = label != FailureType.NORMAL
        status = "ALERT " + str(alerted) if alerted else "no alert"
        good = (alerted is not None) == expected_alert and (alerted == label.value if expected_alert else True)
        print(f"  {label.value:14s} {status} (expected_alert={expected_alert}) {'OK' if good else 'BAD'}")
        ok = ok and good

    print("\nPHASE 3 E2E:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
