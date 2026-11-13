"""A1 dev-only NLI applicability check, without labels or accuracy scoring.

Uses the sealed dev-ID loader, the unchanged pipeline, and the exact pinned
local NLI model. Exports only path/abstention counts; never exports detector
values, decisions, IDs, span content, or annotations. No test execution path.
"""
from __future__ import annotations

from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "sdk"), str(ROOT)]
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from bench.detector_view import detector_view
from scripts.external.prepare_trail import PRIVATE, REVISION
from scripts.external.trail_dev_check import check_frozen, dev_traces, readable_source
from services.collector.openinference import complete_trace
from services.detectors import hallucination, pipeline


def stage_pinned_nli() -> str:
    """Copy only the configured model from an existing exact-revision cache.

    Frozen model-name constructors resolve the staged directory as usual.
    No network fallback, alternate model, inference stub, or detector edit.
    """
    from huggingface_hub.constants import HF_HUB_CACHE

    repo = hallucination.NLI_MODEL
    pin = json.loads((ROOT / ".github/model-revisions.json").read_text())[repo]
    snapshot = Path(HF_HUB_CACHE) / ("models--" + repo.replace("/", "--")) / "snapshots" / pin
    required = ("config.json", "model.safetensors", "tokenizer.json")
    if not all((snapshot / name).is_file() for name in required):
        raise RuntimeError("Exact pinned NLI cache is incomplete; no fallback")
    target = ROOT / repo
    marker = target / ".nexus-model-revision"
    if marker.is_file() and marker.read_text().strip() != pin:
        raise RuntimeError("Staged NLI revision differs from the pin")
    for source in snapshot.rglob("*"):
        if source.is_file() and source.suffix in {".json", ".safetensors", ".txt", ".model"}:
            dest = target / source.relative_to(snapshot)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, dest)
    if not all((target / name).is_file() for name in required):
        raise RuntimeError("Pinned NLI staging failed")
    marker.write_text(pin + "\n", encoding="utf-8")
    return pin


def applicability(view) -> tuple[bool, str | None]:
    """Identify the frozen score() early-return paths, without any gold labels."""
    premises = hallucination.retrieved_context(view)
    if not premises:
        return False, "no_successful_retrieval_text"
    if not hallucination.claims(view.final_output or "", view.root_input or ""):
        return False, "no_checkable_claims"
    if not any(readable_source(p) for p in premises):
        # The original preregistration's conservative readability gate remains.
        # This is an eligibility exclusion, not a frozen score() abstention.
        return True, "source_below_registered_readability_gate"
    return True, None


def main() -> None:
    if Path.cwd().resolve() != ROOT:
        raise RuntimeError("Run from the external-validation workspace")
    check_frozen()
    pin = stage_pinned_nli()
    counts = Counter({"traces": 0, "nli_path_reached": 0, "abstained": 0,
                      "readable_nli_path_eligible": 0})
    reasons = Counter()
    by_split = {}
    PRIVATE.mkdir(parents=True, exist_ok=True)
    # Model/runtime diagnostics can include input details on failure. Keep them
    # private; only our fixed-key aggregate counts are printed or committed.
    with (PRIVATE / "a1_nli_runtime.log").open("w", encoding="utf-8") as log:
        for split, source in dev_traces():
            with redirect_stdout(log), redirect_stderr(log):
                view = detector_view(complete_trace(source).model_dump(mode="json"))
                reached, reason = applicability(view)
                output = pipeline.compute_scores(view)
                if reached != (output.halluc is not None):
                    raise RuntimeError("Frozen NLI branch/output disagrees with applicability")
                del output  # No detector values/decisions are retained.
            current = by_split.setdefault(split, Counter({"traces": 0, "nli_path_reached": 0,
                "abstained": 0, "readable_nli_path_eligible": 0}))
            increment = {"traces": 1, "nli_path_reached": int(reached),
                         "abstained": int(not reached),
                         "readable_nli_path_eligible": int(reached and reason is None)}
            counts.update(increment)
            current.update(increment)
            if reason:
                reasons[reason] += 1
            print(json.dumps({"dev_processed": counts["traces"],
                              "nli_path_reached": counts["nli_path_reached"],
                              "abstained": counts["abstained"]}), flush=True)
    if counts["traces"] != 15:
        raise RuntimeError("Expected exactly 15 sealed dev traces")
    report = {"amendment": "A1", "scope": "dev-only; no labels, detector values, or predictions exported",
              "dataset_revision": REVISION, "nli_revision": pin,
              "aggregate": dict(counts), "abstention_or_ineligibility_reasons": dict(reasons),
              "by_split": {k: dict(v) for k, v in by_split.items()}}
    (ROOT / "reports/external/trail_dev_applicability_a1.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"STOP": "A1 dev check failed", "exception_type": type(exc).__name__}))
        raise SystemExit(1) from None
