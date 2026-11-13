"""DEV-only parity between the native SDK span path and the OTLP path.

(a) in-process, all DEV traces:
        native spans -> JSON round trip -> TraceBuffer -> ClassifierService
        OTLP request -> wire bytes -> mapping -> JSON round trip -> TraceBuffer -> ClassifierService
(b) end to end on a deterministic 20-trace DEV subset through the running nexus-phase6 stack
    (collector -> Kafka -> assembler/classifier), both paths, every span marked nexus.synthetic=true.

No LLM/provider call anywhere; the classifier loads its local NLI/embedding snapshots. Compares
``failure_type`` per trace, then explains every mismatch by patching single mapped fields into the
native trace and re-classifying. The classifier is never tuned.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "sdk")]

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest  # noqa: E402

from services.collector.otel import span_batches  # noqa: E402
from nexus_agent.models import CompleteTrace, Span, SpanBatch  # noqa: E402
from scripts.phase6 import otel_fixtures as fx  # noqa: E402
from services.classifier.consumer import TOPIC_ALERTS, TOPIC_CLASSIFIED, ClassifierService  # noqa: E402
from services.classifier.main import classifier_mode, load_classifier  # noqa: E402
from services.common.trace_buffer import TIMEOUT_SECONDS, TraceBuffer  # noqa: E402


# Whether native traces are delivered the way SDK 0.1.0rc1+ does (root last, metadata.final on it).
FINAL_ON_ROOT = True
# Whether the fixture writes an agent span's plan as the documented nexus.agent.* attributes.
PLAN_ATTRIBUTES = True


def make_classifier(mode: str):
    """The classifier the service runs for ``NEXUS_CLASSIFIER=mode`` (default ``detectors``)."""
    if classifier_mode(mode) == "legacy":
        return load_classifier()
    from services.classifier.live_detectors import DetectorClassifier

    classifier = DetectorClassifier()
    classifier.require_models()
    return classifier


def timed(classifier):
    """Record every ``classify`` call's wall time (ms) on the instance; returns the list."""
    samples: list[float] = []
    original = classifier.classify

    def classify(trace):
        start = time.perf_counter()
        try:
            return original(trace)
        finally:
            samples.append((time.perf_counter() - start) * 1000)

    classifier.classify = classify
    return samples


def spread(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    ordered = sorted(values)
    pick = lambda q: ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]  # noqa: E731
    return {"n": len(ordered), "p50": round(pick(.5), 2), "p95": round(pick(.95), 2),
            "min": round(ordered[0], 2), "max": round(ordered[-1], 2)}

COMPARED_FIELDS = ("span_type", "input", "output", "duration_ms", "error_type", "error_message",
                   "agent_name", "environment", "sdk_version", "client_timestamp")
COMPARED_METADATA = ("tool_name", "model", "provider", "tokens_used", "input_tokens", "output_tokens")
# Mapped-field groups used to explain a mismatch (native trace patched with the mapped value).
PATCH_GROUPS = {
    "duration_ms": ("duration_ms",),
    "input": ("input",),
    "output": ("output",),
    "error_message": ("error_message",),
    "metadata.tool_name": ("metadata.tool_name",),
    "metadata.model/tokens": ("metadata.model", "metadata.tokens_used", "metadata.provider"),
    "metadata.role+plan_steps": ("metadata.role", "metadata.plan_steps"),
    "input+output": ("input", "output"),
    "input+output+duration_ms": ("input", "output", "duration_ms"),
}
ALL_FIELDS = tuple(dict.fromkeys(n for f in PATCH_GROUPS.values() for n in f))


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _service(classifier):
    clock = Clock()
    service = ClassifierService(classifier, buffer=TraceBuffer(clock=clock))
    service._producer = MagicMock()
    return service, clock


def _classification(service) -> dict:
    records = [json.loads(c.kwargs["value"]) for c in service._producer.produce.call_args_list
               if c.args[0] == TOPIC_CLASSIFIED]
    if len(records) != 1:
        raise RuntimeError(f"expected one classification, saw {len(records)}")
    return records[0]


def run_spans(classifier, spans: list[Span]):
    """Feed spans one by one as the Kafka consumer does, then classify.

    A trace with a ``final`` root completes on that span; otherwise it completes by inactivity.
    A span that arrives after its root completed the trace would be dropped by the buffer; that is
    an error here, because both delivery orders in this script put the root last.
    """
    service, clock = _service(classifier)
    seen: list[CompleteTrace] = []
    process = service.process_trace

    def recording(trace):
        seen.append(trace)
        return process(trace)

    service.process_trace = recording
    for span in spans:
        service._handle(span.model_dump_json().encode())
    if not seen:
        clock.now += TIMEOUT_SECONDS + 1
        for trace in service.buffer.sweep():
            service.process_trace(trace)
    if len(seen) != 1:
        raise RuntimeError(f"expected one assembled trace, saw {len(seen)}")
    if service.buffer.late_spans_after_completion:
        raise RuntimeError("a span arrived after its root completed the trace and was dropped")
    return seen[0], _classification(service)


def native_path(classifier, trace):
    """Spans exactly as the SDK exporter would deliver them (SpanBatch JSON, <=100 per batch)."""
    if FINAL_ON_ROOT:
        trace = fx.sdk_delivery(trace)
    spans = []
    for i in range(0, len(trace.spans), 100):
        batch = SpanBatch(spans=trace.spans[i:i + 100])
        spans += SpanBatch.model_validate_json(batch.model_dump_json()).spans
    return run_spans(classifier, spans)

def otlp_path(classifier, trace):
    wire = fx.trace_to_otlp(trace, plan_attributes=PLAN_ATTRIBUTES).SerializeToString()
    request = ExportTraceServiceRequest()
    request.ParseFromString(wire)
    spans = [span for batch in span_batches(request) for span in batch.spans]
    return run_spans(classifier, spans)


def _get(span: Span, name: str):
    if name.startswith("metadata."):
        return (span.metadata or {}).get(name.split(".", 1)[1])
    return getattr(span, name)


def field_fidelity(native: CompleteTrace, mapped: CompleteTrace) -> dict:
    diffs = Counter()
    for a, b in zip(native.spans, mapped.spans, strict=True):
        for name in (*COMPARED_FIELDS, *(f"metadata.{k}" for k in COMPARED_METADATA)):
            va, vb = _get(a, name), _get(b, name)
            if name == "duration_ms":
                if va != vb:
                    diffs["duration_ms"] += 1
                    if abs(va - vb) > 1e-6:  # more than 1 ns
                        diffs["duration_ms_over_1ns"] += 1
            elif name == "client_timestamp":
                if va != vb:
                    diffs[name] += 1
            elif va != vb:
                diffs[name] += 1
    # parent structure compared positionally through span ids
    index_a = {s.span_id: i for i, s in enumerate(native.spans)}
    index_b = {s.span_id: i for i, s in enumerate(mapped.spans)}
    for a, b in zip(native.spans, mapped.spans, strict=True):
        if index_a.get(a.parent_span_id) != index_b.get(b.parent_span_id):
            diffs["parent_span_id"] += 1
    return dict(diffs)


def _patched(native: CompleteTrace, mapped: CompleteTrace, fields: tuple[str, ...]) -> CompleteTrace:
    spans = []
    for a, b in zip(native.spans, mapped.spans, strict=True):
        update, metadata = {}, dict(a.metadata)
        for name in fields:
            if name.startswith("metadata."):
                key = name.split(".", 1)[1]
                if key in b.metadata:
                    metadata[key] = b.metadata[key]
                else:
                    metadata.pop(key, None)
            else:
                update[name] = getattr(b, name)
        spans.append(a.model_copy(update={**update, "metadata": metadata}))
    return native.model_copy(update={"spans": spans})


def explain(classifier, native: CompleteTrace, mapped: CompleteTrace, native_record: dict, otlp_record: dict) -> dict:
    """Which mapped fields, patched alone into the native trace, reproduce the OTLP outcome?"""
    service, _ = _service(classifier)
    outcomes = {}
    for group, fields in PATCH_GROUPS.items():
        service._producer.reset_mock()
        service.process_trace(_patched(native, mapped, fields))
        outcomes[group] = _classification(service)["failure_type"]
    service._producer.reset_mock()
    service.process_trace(_patched(native, mapped, ALL_FIELDS))
    everything = _classification(service)["failure_type"]
    target = otlp_record["failure_type"]
    return {
        "patched_alone_outcome": outcomes,
        "single_field_explanations": [g for g, o in outcomes.items() if o == target],
        "all_mapped_fields_patched_outcome": everything,
        "all_fields_reproduce_otlp": everything == target,
    }


def _failure_index(record: dict, ids: list[str]):
    span_id = record.get("failure_span_id")
    return ids.index(span_id) if span_id in ids else None


def run_inprocess(limit: int | None = None, progress: bool = True, mode: str = "detectors") -> dict:
    ids = fx.dev_trace_ids()
    labels = fx.dev_labelled()
    if limit:
        ids = ids[:limit]
    traces = fx.load_dev_traces(ids)
    classifier = make_classifier(mode)
    classify_ms = timed(classifier)
    rows, fidelity, mismatches, localisation_diffs = [], Counter(), [], []
    started = time.time()
    for n, tid in enumerate(ids, 1):
        trace = traces[tid]
        t_native, native = native_path(classifier, trace)
        t_otlp, otlp = otlp_path(classifier, trace)
        n_ids = [s.span_id for s in t_native.spans]
        o_ids = [s.span_id for s in t_otlp.spans]
        rows.append({
            "trace_id": tid, "dev_label": labels[tid], "span_count": len(trace.spans),
            "native": native["failure_type"], "otlp": otlp["failure_type"],
            "native_rule": native["triggered_rule"], "otlp_rule": otlp["triggered_rule"],
            "native_failure_span_index": _failure_index(native, n_ids),
            "otlp_failure_span_index": _failure_index(otlp, o_ids),
            "native_anomaly_score": native["anomaly_score"], "otlp_anomaly_score": otlp["anomaly_score"],
            "native_confidence": native["confidence"], "otlp_confidence": otlp["confidence"],
            "span_order_preserved": [s.span_type.value for s in t_native.spans] == [s.span_type.value for s in t_otlp.spans],
        })
        fidelity.update(field_fidelity(t_native, t_otlp))
        if native["failure_type"] != otlp["failure_type"]:
            row = rows[-1]
            row["explanation"] = explain(classifier, t_native, t_otlp, native, otlp)
            row["field_diffs"] = field_fidelity(t_native, t_otlp)
            mismatches.append(row)
        elif rows[-1]["native_failure_span_index"] != rows[-1]["otlp_failure_span_index"]:
            # Same verdict, different span blamed: say which spans, and whether the one field
            # that differs on them (memory-op tool names have no semconv attribute) accounts for it.
            row = rows[-1]
            service, _ = _service(classifier)
            service.process_trace(_patched(t_native, t_otlp, ("metadata.tool_name",)))
            patched = _failure_index(_classification(service), n_ids)
            blamed = lambda tr, i: None if i is None else {  # noqa: E731
                "span_type": tr.spans[i].span_type.value, "tool_name": tr.spans[i].metadata.get("tool_name")}
            row["localisation"] = {
                "native_span": blamed(t_native, row["native_failure_span_index"]),
                "otlp_span": blamed(t_otlp, row["otlp_failure_span_index"]),
                "tool_name_patch_gives_otlp_index": patched == row["otlp_failure_span_index"]}
            localisation_diffs.append(row)
        if progress and n % 25 == 0:
            print(f"in-process {n}/{len(ids)} mismatches={len(mismatches)}", flush=True)
    match = sum(r["native"] == r["otlp"] for r in rows)
    scores = [abs(r["native_anomaly_score"] - r["otlp_anomaly_score"]) for r in rows
              if r["native_anomaly_score"] is not None and r["otlp_anomaly_score"] is not None]
    by_label = {}
    for label in sorted({r["dev_label"] for r in rows}):
        part = [r for r in rows if r["dev_label"] == label]
        by_label[label] = {"traces": len(part), "match": sum(r["native"] == r["otlp"] for r in part)}
    return {
        "scope": "all DEV traces" if not limit else f"first {limit} DEV traces (smoke)",
        "classifier": classifier_mode(mode),
        "classify_ms_both_paths": spread(classify_ms),
        "traces": len(rows), "spans": sum(r["span_count"] for r in rows),
        "failure_type_match": match, "failure_type_match_rate": match / len(rows),
        "mismatch_count": len(mismatches),
        "confusion_native_to_otlp": {f"{a}->{b}": c for (a, b), c in Counter((r["native"], r["otlp"]) for r in rows if r["native"] != r["otlp"]).items()},
        "triggered_rule_match": sum(r["native_rule"] == r["otlp_rule"] for r in rows),
        "failure_span_index_match": sum(r["native_failure_span_index"] == r["otlp_failure_span_index"] for r in rows),
        "span_order_preserved": sum(r["span_order_preserved"] for r in rows),
        "anomaly_score_abs_diff": {"max": max(scores) if scores else None, "median": statistics.median(scores) if scores else None, "compared": len(scores)},
        "by_dev_label": by_label,
        "field_differences_over_all_spans": dict(fidelity),
        "mismatches": mismatches,
        "failure_span_differences": localisation_diffs,
        "seconds": round(time.time() - started, 1),
    }


# ── (b) end to end ────────────────────────────────────────────────────────────

def pick_subset(count: int = 20) -> list[str]:
    """Deterministic, label-stratified: per DEV label, sha256-sorted; round-robin to ``count``."""
    labels = fx.dev_labelled()
    buckets = {}
    for tid, label in labels.items():
        buckets.setdefault(label, []).append(tid)
    for label in buckets:
        buckets[label].sort(key=lambda t: hashlib.sha256(t.encode()).hexdigest())
    order, picked = sorted(buckets), []
    while len(picked) < count:
        for label in order:
            if buckets[label] and len(picked) < count:
                picked.append(buckets[label].pop(0))
    return picked


NATIVE_WAIT_SECONDS = 180
OTLP_GAP_SECONDS = 6.0


def run_e2e(collector="http://127.0.0.1:8000", kafka="localhost:29092", wait_seconds: int = 600,
            expect: str | None = None) -> dict:
    import gzip

    import httpx
    import psycopg2
    from confluent_kafka import Consumer

    from bench.llm import load_env

    load_env(str(ROOT / ".env"))
    ids = pick_subset(20)
    labels = fx.dev_labelled()
    traces = fx.load_dev_traces(ids)
    nonce = uuid.uuid4().hex[:8]
    group = f"p6otel-{nonce}"
    sink = Consumer({"bootstrap.servers": kafka, "group.id": group, "auto.offset.reset": "earliest"})
    sink.subscribe([TOPIC_CLASSIFIED, TOPIC_ALERTS])
    sink.poll(2.0)  # join the group before producing
    client = httpx.Client(timeout=30, trust_env=False)
    expected = {}  # trace id -> (path, index, original id)
    sent_at, started_at = {}, {}  # POST returned / POST about to start, per trace id
    classified, alerts = {}, []

    def poll(seconds: float) -> None:
        """Read the sink for ``seconds``; record when each classification was first seen."""
        end = time.time() + seconds
        while time.time() < end:
            msg = sink.poll(min(1.0, max(0.05, end - time.time())))
            if msg is None or msg.error():
                continue
            seen = time.time()
            value = json.loads(msg.value())
            if msg.topic() == TOPIC_CLASSIFIED and value["trace_id"] in expected:
                if value["trace_id"] not in classified:
                    classified[value["trace_id"]] = {
                        **value, "seen_after_s": round(seen - sent_at[value["trace_id"]], 2),
                        "seen_after_post_start_s": round(seen - started_at[value["trace_id"]], 2)}
            elif msg.topic() == TOPIC_ALERTS and value.get("trace_id") in expected:
                alerts.append(value)

    # Latency is the time from the POST that carried a trace's final span returning to its
    # classification being read from Kafka. Traces are paced so they do not queue behind each
    # other: native one at a time (it completes on metadata.final), OTLP every OTLP_GAP_SECONDS
    # (it completes after the 30 s inactivity timeout, so waiting per trace would only idle).
    for i, tid in enumerate(ids):
        native_id = f"p6otel-{nonce}-n{i:02d}"
        spans = fx.native_spans(fx.sdk_delivery(traces[tid]) if FINAL_ON_ROOT else traces[tid],
                                trace_id=native_id, id_salt=nonce, synthetic=True)
        expected[native_id] = ("native", i, tid)
        started_at[native_id] = time.time()
        response = client.post(f"{collector}/v1/spans", json=SpanBatch(spans=spans).model_dump(mode="json"))
        response.raise_for_status()
        assert response.json()["accepted"] == len(spans), response.text
        sent_at[native_id] = time.time()
        deadline = time.time() + NATIVE_WAIT_SECONDS
        while native_id not in classified and time.time() < deadline:
            poll(1.0)
    for i, tid in enumerate(ids):
        request = fx.trace_to_otlp(traces[tid], trace_salt=nonce, synthetic=True, plan_attributes=PLAN_ATTRIBUTES)
        otlp_id = request.resource_spans[0].scope_spans[0].spans[0].trace_id.hex()
        expected[otlp_id] = ("otlp", i, tid)
        started_at[otlp_id] = time.time()
        response = client.post(f"{collector}/v1/traces", content=gzip.compress(request.SerializeToString()),
                               headers={"Content-Type": "application/x-protobuf", "Content-Encoding": "gzip"})
        response.raise_for_status()
        sent_at[otlp_id] = time.time()
        poll(OTLP_GAP_SECONDS)
    deadline = time.time() + wait_seconds
    while time.time() < deadline and len(classified) < len(expected):
        poll(1.0)
    # Give a late alert one more chance to show up (synthetic suppression must hold).
    end = time.time() + 5
    while time.time() < end:
        msg = sink.poll(1.0)
        if msg is not None and not msg.error() and msg.topic() == TOPIC_ALERTS:
            value = json.loads(msg.value())
            if value.get("trace_id") in expected:
                alerts.append(value)
    sink.close()
    conn = psycopg2.connect(host="127.0.0.1", port=int(os.getenv("NEXUS_TEST_PG_PORT", "55432")), dbname=os.getenv("POSTGRES_DB", "nexus"),
                            user=os.getenv("POSTGRES_USER", "nexus"), password=os.getenv("POSTGRES_PASSWORD", "nexus_dev_password"))
    with conn, conn.cursor() as cur:
        cur.execute("SELECT trace_id, span_count FROM traces WHERE trace_id = ANY(%s)", (list(expected),))
        assembled = dict(cur.fetchall())
    conn.close()
    pairs = []
    for i, tid in enumerate(ids):
        n_id = next(k for k, v in expected.items() if v[0] == "native" and v[1] == i)
        o_id = next(k for k, v in expected.items() if v[0] == "otlp" and v[1] == i)
        n, o = classified.get(n_id), classified.get(o_id)
        pairs.append({
            "dev_trace_id": tid, "dev_label": labels[tid], "span_count": len(traces[tid].spans),
            "native": n and n["failure_type"], "otlp": o and o["failure_type"],
            "native_rule": n and n["triggered_rule"], "otlp_rule": o and o["triggered_rule"],
            "native_assembled_spans": assembled.get(n_id), "otlp_assembled_spans": assembled.get(o_id),
            "native_seen_after_s": n and n["seen_after_s"], "otlp_seen_after_s": o and o["seen_after_s"],
            "native_seen_after_post_start_s": n and n["seen_after_post_start_s"],
            "otlp_seen_after_post_start_s": o and o["seen_after_post_start_s"],
        })
    complete = [p for p in pairs if p["native"] and p["otlp"]]
    match = sum(p["native"] == p["otlp"] for p in complete)
    for p in pairs:
        if p["native"] != p["otlp"]:
            p["note"] = "mismatch or a path was never classified"
    stored = json.loads((ROOT / "results" / "phase2_dev_predictions.json").read_text(encoding="utf-8"))["predictions"]
    for p in pairs:
        p["phase2_pred"] = stored[p["dev_trace_id"]]["pred"]
    vs_phase2 = {path: sum(p[path] == p["phase2_pred"] for p in pairs) for path in ("native", "otlp")}
    rules_seen = {c["triggered_rule"] for c in classified.values()}
    observed = ("detectors" if all(r and (r.startswith("detectors:") or r == "insufficient_content")
                                   for r in rules_seen) else "legacy")
    if expect and observed != expect:
        raise RuntimeError(f"expected the {expect} classifier in the stack, saw rules {sorted(rules_seen)}")
    latency = {path: spread([p[f"{path}_seen_after_s"] for p in pairs if p[f"{path}_seen_after_s"] is not None])
               for path in ("native", "otlp")}
    latency_from_post_start = {
        path: spread([p[f"{path}_seen_after_post_start_s"] for p in pairs
                      if p[f"{path}_seen_after_post_start_s"] is not None])
        for path in ("native", "otlp")}
    return {
        "classifier_observed": observed,
        "matches_phase2_dev_prediction": vs_phase2,
        "latency_final_span_to_classification_s": latency,
        "latency_from_final_post_start_to_classification_s": latency_from_post_start,
        "latency_pacing": f"native one at a time; OTLP every {OTLP_GAP_SECONDS:g} s; "
                          "latency_final_span_to_classification_s is measured from the final span's POST returning; "
                          "latency_from_final_post_start_to_classification_s from just before that POST started "
                          "(an upper bound: it includes the POST itself)",
        "scope": "20-trace DEV subset, label-stratified, sha256-ordered", "nonce": nonce,
        "traces": len(pairs), "classified_both_paths": len(complete),
        "failure_type_match": match, "failure_type_match_rate": match / len(pairs),
        "all_assembled_with_full_span_count": all(
            p["native_assembled_spans"] == p["span_count"] and p["otlp_assembled_spans"] == p["span_count"] for p in pairs),
        "alerts_published_for_synthetic_traces": len(alerts),
        "classifications_published": len(classified),
        "pairs": pairs,
        "mismatches": [p for p in pairs if p["native"] != p["otlp"]],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--inprocess", action="store_true")
    parser.add_argument("--e2e", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--classifier", choices=("detectors", "legacy"), default="detectors",
                        help="in-process: which classifier; end to end: which one the stack must be running")
    parser.add_argument("--no-plan-attributes", action="store_true",
                        help="emit role/plan_steps as app.* attributes, as an application unaware of Nexus would")
    parser.add_argument("--no-final", action="store_true",
                        help="deliver native traces without the SDK root-final signal (pre-6.4a behaviour)")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    global PLAN_ATTRIBUTES, FINAL_ON_ROOT
    PLAN_ATTRIBUTES = not args.no_plan_attributes
    FINAL_ON_ROOT = not args.no_final
    result = {"generated_at": datetime.now(timezone.utc).isoformat(), "classifier": args.classifier,
              "plan_attributes": PLAN_ATTRIBUTES, "native_final_on_root": FINAL_ON_ROOT}
    if args.inprocess:
        result["inprocess"] = run_inprocess(args.limit, mode=args.classifier)
    if args.e2e:
        result["end_to_end"] = run_e2e(expect=args.classifier)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    for key in ("inprocess", "end_to_end"):
        if key in result:
            r = result[key]
            print(key, f"match {r['failure_type_match']}/{r['traces']}", "mismatches", len(r["mismatches"]))


if __name__ == "__main__":
    main()
