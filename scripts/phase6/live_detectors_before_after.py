"""DEV-only before/after: the legacy classifier (the old live default) vs the scored detectors.

"Before" runs the legacy ``FailureClassifier`` through the service path on every DEV trace.
"After" is the Phase 2 DEV prediction file, which ``live_detectors_equivalence.py`` shows the live
detector classifier reproduces trace for trace. Both are scored against DEV labels from the DEV
adapter (``fx.dev_labelled``); TEST and the raw label file are never touched. Recall and false
alerts follow the Phase 2 definitions: headline macro recall over HALLUCINATION, CONTEXT_BLEED,
PLAN_DRIFT; OTHER_FAILURE traces are excluded from per-class scoring.

    python scripts/phase6/live_detectors_before_after.py --out results/phase6/live_detectors_before_after.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "sdk")]

from scripts.phase6 import otel_fixtures as fx  # noqa: E402
from scripts.phase6.otel_parity import make_classifier, native_path, spread, timed  # noqa: E402

HEADLINE = ("HALLUCINATION", "CONTEXT_BLEED", "PLAN_DRIFT")
SCORED = ("HALLUCINATION", "TOOL_MISFIRE", "CONTEXT_BLEED", "PLAN_DRIFT", "LOOP_DETECTED")


def score(labels: dict[str, str], preds: dict[str, str]) -> dict:
    per_class = {}
    for cls in SCORED:
        truth = [t for t, label in labels.items() if label == cls]
        predicted = [t for t, p in preds.items() if p == cls and labels[t] != "OTHER_FAILURE"]
        hit = sum(preds[t] == cls for t in truth)
        correct = sum(labels[t] == cls for t in predicted)
        per_class[cls] = {"recall": round(hit / len(truth), 3), "recall_n": f"{hit}/{len(truth)}",
                          "precision": round(correct / len(predicted), 3) if predicted else None,
                          "precision_n": f"{correct}/{len(predicted)}"}
    normal = [t for t, label in labels.items() if label == "NORMAL"]
    false_alerts = sum(preds[t] != "NORMAL" for t in normal)
    return {
        "per_class": per_class,
        "headline_macro_recall": round(sum(per_class[c]["recall"] for c in HEADLINE) / len(HEADLINE), 3),
        "macro_recall_all_five": round(sum(per_class[c]["recall"] for c in SCORED) / len(SCORED), 3),
        "false_alerts_on_normal": f"{false_alerts}/{len(normal)}",
        "false_alert_rate_on_normal": round(false_alerts / len(normal), 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    ids = fx.dev_trace_ids()
    labels = fx.dev_labelled()
    stored = json.loads((ROOT / "results" / "phase2_dev_predictions.json").read_text(encoding="utf-8"))["predictions"]
    if set(stored) != set(ids):
        raise RuntimeError("Phase 2 DEV predictions and the DEV whitelist cover different traces")
    traces = fx.load_dev_traces(ids)
    legacy = make_classifier("legacy")
    legacy_ms = timed(legacy)
    legacy_preds, started = {}, time.time()
    for n, tid in enumerate(ids, 1):
        _, record = native_path(legacy, traces[tid])
        legacy_preds[tid] = record["failure_type"]
        if n % 25 == 0:
            print(f"legacy {n}/{len(ids)} ({time.time() - started:.0f}s)", flush=True)
    detector_preds = {tid: stored[tid]["pred"] for tid in ids}
    agree = sum(legacy_preds[t] == detector_preds[t] for t in ids)
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "all DEV traces, scored against DEV labels via the DEV adapter",
        "traces": len(ids),
        "dev_label_counts": dict(Counter(labels.values())),
        "legacy": score(labels, legacy_preds),
        "detectors": score(labels, detector_preds),
        "legacy_agrees_with_detectors": f"{agree}/{len(ids)}",
        "legacy_classify_ms": spread(legacy_ms),
        "legacy_prediction_counts": dict(Counter(legacy_preds.values())),
        "detector_prediction_counts": dict(Counter(detector_preds.values())),
        "legacy_predictions": legacy_preds,
        "seconds": round(time.time() - started, 1),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("legacy headline", result["legacy"]["headline_macro_recall"], "detectors headline",
          result["detectors"]["headline_macro_recall"], "agreement", result["legacy_agrees_with_detectors"])


if __name__ == "__main__":
    main()
