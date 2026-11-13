"""DEV-only equivalence: the live detector classifier vs committed Phase 2 DEV predictions.

Every DEV trace goes through the classifier that now runs in the service, two ways:

* ``adapter``: ``DetectorClassifier.classify`` on the DEV ``CompleteTrace`` itself (same trace id as
  the Phase 2 run, so the detector view is byte-identical to the one Phase 2 scored).
* ``service``: SDK-style spans -> JSON round trip -> ``TraceBuffer`` -> ``ClassifierService`` (the
  live path; this re-assembles the trace, and the detectors see the same spans).

Both are compared with ``results/phase2_dev_predictions.json`` (``pred``), and the HALLUCINATION
NLI score with the stored ``nli_score`` where Phase 2 computed one. Detector thresholds and config
are never touched. TEST is never read: the traces come through the DEV adapter whitelist.

    python scripts/phase6/live_detectors_equivalence.py --out results/phase6/live_detectors_equivalence.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "sdk")]

from scripts.phase6 import otel_fixtures as fx  # noqa: E402
from scripts.phase6.otel_parity import native_path  # noqa: E402
from services.classifier.live_detectors import DetectorClassifier, detector_config  # noqa: E402

PREDICTIONS = ROOT / "results" / "phase2_dev_predictions.json"


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def run(limit: int | None = None) -> dict:
    stored = json.loads(PREDICTIONS.read_text(encoding="utf-8"))["predictions"]
    ids = fx.dev_trace_ids()
    if set(stored) != set(ids):
        raise RuntimeError("Phase 2 DEV predictions and the DEV whitelist cover different traces")
    if limit:
        ids = ids[:limit]
    labels = fx.dev_labelled()
    traces = fx.load_dev_traces(ids)
    classifier = DetectorClassifier()
    classifier.require_models()
    rows, mismatches, adapter_ms, service_ms, score_diffs = [], [], [], [], []
    started = time.time()
    for n, tid in enumerate(ids, 1):
        trace = traces[tid]
        expected = stored[tid]["pred"]
        t0 = time.perf_counter()
        direct = classifier.classify(trace)
        adapter_ms.append((time.perf_counter() - t0) * 1000)
        halluc = classifier.last_scores.halluc
        original = classifier.classify
        timed = []

        def clock(assembled, _original=original, _timed=timed):
            t = time.perf_counter()
            try:
                return _original(assembled)
            finally:
                _timed.append((time.perf_counter() - t) * 1000)

        classifier.classify = clock
        try:
            _, live = native_path(classifier, trace)
        finally:
            del classifier.classify
        service_ms += timed
        stored_score = stored[tid].get("nli_score")
        if stored_score is not None and halluc is not None:
            score_diffs.append(abs(stored_score - halluc))
        row = {"trace_id": tid, "dev_label": labels[tid], "phase2_pred": expected,
               "adapter": direct.failure_type.value, "service": live["failure_type"],
               "adapter_rule": direct.triggered_rule, "service_rule": live["triggered_rule"],
               "span_count": len(trace.spans)}
        rows.append(row)
        if expected != row["adapter"] or expected != row["service"]:
            row["phase2_nli_score"] = stored_score
            row["live_nli_score"] = halluc
            mismatches.append(row)
        if n % 25 == 0:
            print(f"equivalence {n}/{len(ids)} mismatches={len(mismatches)}", flush=True)
    adapter_match = sum(r["adapter"] == r["phase2_pred"] for r in rows)
    service_match = sum(r["service"] == r["phase2_pred"] for r in rows)
    by_label = {}
    for label in sorted({r["dev_label"] for r in rows}):
        part = [r for r in rows if r["dev_label"] == label]
        by_label[label] = {"traces": len(part),
                           "adapter_match": sum(r["adapter"] == r["phase2_pred"] for r in part),
                           "service_match": sum(r["service"] == r["phase2_pred"] for r in part)}
    return {
        "scope": "all DEV traces" if not limit else f"first {limit} DEV traces (smoke)",
        "compared_with": "results/phase2_dev_predictions.json (pred)",
        "detector_config": detector_config(),
        "traces": len(rows),
        "adapter_match": adapter_match, "adapter_match_rate": adapter_match / len(rows),
        "service_match": service_match, "service_match_rate": service_match / len(rows),
        "mismatch_count": len(mismatches),
        "predicted_distribution": dict(Counter(r["phase2_pred"] for r in rows)),
        "by_dev_label": by_label,
        "nli_score_abs_diff_vs_phase2": {
            "compared": len(score_diffs),
            "max": max(score_diffs) if score_diffs else None,
            "median": statistics.median(score_diffs) if score_diffs else None},
        "classify_ms": {
            "adapter_direct": {"n": len(adapter_ms), "p50": round(percentile(adapter_ms, .5), 1),
                               "p95": round(percentile(adapter_ms, .95), 1), "max": round(max(adapter_ms), 1)},
            "service_path": {"n": len(service_ms), "p50": round(percentile(service_ms, .5), 1),
                             "p95": round(percentile(service_ms, .95), 1), "max": round(max(service_ms), 1)}},
        "mismatches": mismatches,
        "seconds": round(time.time() - started, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = {"generated_at": datetime.now(timezone.utc).isoformat(), "equivalence": run(args.limit)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    r = result["equivalence"]
    print(f"adapter {r['adapter_match']}/{r['traces']}  service {r['service_match']}/{r['traces']}  "
          f"mismatches {r['mismatch_count']}")


if __name__ == "__main__":
    main()
