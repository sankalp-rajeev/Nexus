"""Single registered TRAIL-A evaluation. No B/parquet loader or network path.

Only aggregate metrics are exported. Private checkpoints prevent a second
completed run and permit an explicitly documented crash-only continuation.
"""
from __future__ import annotations

import argparse
import copy
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
import traceback
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "sdk"), str(ROOT)]
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from bench.detector_view import detector_view
from scripts.external.prepare_trail import PRIVATE, REVISION
from scripts.external.trail_dev_check import check_frozen
from scripts.external.trail_dev_check_a1 import applicability
from services.collector.openinference import complete_trace
from services.critic.detector_adapter import from_detector
from services.detectors import hallucination, pipeline

CLASSES = ("LOOP_DETECTED", "TOOL_MISFIRE", "HALLUCINATION")
LOCAL_ZONE = ZoneInfo("America/New_York")
ORIGINAL = ROOT / "reports/external/trail_split"
A2 = ORIGINAL / "a2"
STATE = PRIVATE / "trail_a_run_state.json"
OUTPUT = ROOT / "results/external/trail_a_scored.json"
ORIGINAL_HASH = "4081a888f8d624b257cc8a6fe1648a0709160b05154bfd5df59967bf6c16f061"
A_HASH = "1b1c8afba707315f519735f7bb52e8f63ae4d0922334a9f46728688b641346bf"
DISCLOSURE = "d19cb86bdc2e601aff1282607fb5ae8cc9da4e2b"
EXCLUDED = {
    "0035f455b3ff2295167a844f04d85d34": "missing_label_trace_id",
    "5b5a35053775cbf29701c171e6675853": "missing_label_trace_id",
    "5e5dc94e090341c564d582f551a0cddb": "missing_label_trace_id",
    "5ec1cd43eb8ae4094e93a4892ff0f06f": "missing_label_trace_id",
    "6cc6dc35a28bbed6cfd873756094bc16": "missing_label_trace_id",
    "a96c6811716c0473b86a23321db79c34": "invalid_label_json",
}
PROTECTED = ("services/collector/", "services/detectors/", "bench/detector_view.py",
    "bench/tools.py", "bench/world.py", "sdk/nexus_agent/", "sdk/nexus_llmops/",
    "services/classifier/live_detectors.py", "services/critic/", ".github/model-revisions.json",
    "scripts/external/prepare_trail.py", "scripts/external/trail_dev_check.py",
    "scripts/external/trail_dev_check_a1.py")


def git(*args) -> bytes:
    return subprocess.check_output(["git", "-c", f"safe.directory={ROOT.as_posix()}", *args], cwd=ROOT)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def wilson(x: int, n: int):
    if not 0 <= x <= n:
        raise ValueError("Invalid binomial counts")
    if n == 0:
        return None
    z = 1.959963984540054
    p, z2 = x / n, z * z
    d = 1 + z2 / n
    center = (p + z2 / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / d
    return [max(0.0, center - half), min(1.0, center + half)]


def ratio(x: int, n: int) -> dict:
    return {"numerator": x, "denominator": n, "estimate": x / n if n else None,
            "wilson95": wilson(x, n)}


def fresh_counts() -> dict:
    return {"tp": 0, "fp": 0, "fn": 0, "tn": 0, "abstentions": {}, "exclusions": {},
            "localization": {"matched_within_1": 0, "eligible_true_positives": 0,
                             "ambiguous_gold_true_positives": 0, "missing_locator_true_positives": 0}}


def add_observation(counts: dict, gold: bool | None, predicted: bool | None,
                    *, abstention: str | None = None, exclusion: str | None = None):
    if exclusion:
        counts["exclusions"][exclusion] = counts["exclusions"].get(exclusion, 0) + 1
        return
    if abstention:
        counts["abstentions"][abstention] = counts["abstentions"].get(abstention, 0) + 1
        return
    if gold is None or predicted is None:
        raise ValueError("Unassessable observation lacks explicit reason")
    key = ("tp" if predicted else "fn") if gold else ("fp" if predicted else "tn")
    counts[key] += 1


def summarize(counts: dict) -> dict:
    out = dict(counts)
    out["evaluated"] = sum(counts[k] for k in ("tp", "fp", "fn", "tn"))
    out["gold_positive"] = counts["tp"] + counts["fn"]
    out["precision"] = ratio(counts["tp"], counts["tp"] + counts["fp"])
    out["recall"] = ratio(counts["tp"], counts["tp"] + counts["fn"])
    return out


def normalize_category(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


# Exactly the terms in the original protocol and the user's part 2 instruction;
# no substrings, plurals, fuzzy matches, or post-result expansion.
CATEGORY_CLASS = {
    "resource abuse": "LOOP_DETECTED", "timeout issues": "LOOP_DETECTED",
    "api errors": "TOOL_MISFIRE", "formatting errors": "TOOL_MISFIRE",
    "language only": "HALLUCINATION", "language only hallucination": "HALLUCINATION",
    "tool related hallucination": "HALLUCINATION",
}


def resolve_location(location, positions: dict[str, int]):
    if not isinstance(location, str):
        return None
    ids = set(x.lower() for x in re.findall(r"(?<![0-9a-fA-F])[0-9a-fA-F]{16}(?![0-9a-fA-F])", location))
    return positions[next(iter(ids))] if len(ids) == 1 and next(iter(ids)) in positions else None


def map_labels(label: dict, view) -> tuple[dict, dict, dict]:
    """Read only category/location. Never read evidence, description, impact, scores."""
    positives = {c: False for c in CLASSES}
    uncertain = {c: False for c in CLASSES}
    locations = {c: set() for c in CLASSES}
    ambiguous = {c: False for c in CLASSES}
    unmapped = Counter()
    errors = label.get("errors")
    positions = {s.span_id.lower(): i for i, s in enumerate(view.spans)}
    if not isinstance(errors, list):
        return {c: None for c in CLASSES}, {c: None for c in CLASSES}, {}
    for error in errors:
        category = error.get("category") if isinstance(error, dict) else None
        if not isinstance(category, str) or not category.strip():
            uncertain = {c: True for c in CLASSES}
            continue
        name = normalize_category(category)
        cls = CATEGORY_CLASS.get(name)
        if cls is None:
            # Document unmapped categories by irreversible fingerprint/count,
            # rather than exporting unregistered annotation strings.
            unmapped[hashlib.sha256(name.encode()).hexdigest()] += 1
            continue
        position = resolve_location(error.get("location"), positions)
        if cls == "TOOL_MISFIRE":
            if position is None:
                uncertain[cls] = True
                ambiguous[cls] = True
                continue
            raw = view.spans[position].metadata.get("otel.attributes", {})
            if str(raw.get("openinference.span.kind", "")).upper() != "TOOL":
                continue
        positives[cls] = True
        if position is None:
            ambiguous[cls] = True
        else:
            locations[cls].add(position)
    gold = {c: True if positives[c] else None if uncertain[c] else False for c in CLASSES}
    loc = {c: None if ambiguous[c] else sorted(locations[c]) for c in CLASSES}
    return gold, loc, dict(unmapped)


def load_requested(entries: dict, requested: set[str], base: Path, *, decode=json.loads):
    """Structural ID filter precedes BOTH file opens and all JSON decoding.

    Generic for synthetic tests; production preflight restricts requested and
    catalog membership to exactly the committed TRAIL-A IDs.
    """
    found = set()
    for tid, row in sorted(entries.items()):
        if tid not in requested:
            continue
        paths = row["paths"]
        trace = decode((base / paths["trace"]).read_text(encoding="utf-8"))
        label = decode((base / paths["labels"]).read_text(encoding="utf-8"))
        if trace.get("trace_id") != tid or label.get("trace_id") != tid:
            raise RuntimeError("Trace-ID label join mismatch")
        found.add(tid)
        yield tid, row["split"], trace, label
    if found != requested:
        raise RuntimeError("Requested trace absent from A-only catalog")


def convert_for_evaluation(source):
    """Retain the frozen adapter's validation; count its preregistered exclusion.

    No normalization, deduplication, input repair, detector substitute, or
    model-error suppression. Only adapter validation errors are in this scope.
    """
    try:
        converted = complete_trace(source)
    except ValueError:
        return None
    return detector_view(converted.model_dump(mode="json"))


def committed_blob(path: Path, commit: str) -> bytes:
    blob = path.read_bytes()
    if blob.replace(b"\r\n", b"\n") != git("show", f"{commit}:{path.relative_to(ROOT).as_posix()}").replace(b"\r\n", b"\n"):
        raise RuntimeError("Committed pre-registration artifact differs")
    return blob


def preflight() -> tuple[dict, dict, set]:
    from huggingface_hub.constants import HF_HUB_CACHE
    if Path.cwd().resolve() != ROOT or git("branch", "--show-current").decode().strip() != "external-validation":
        raise RuntimeError("Wrong workspace or branch")
    if git("diff", "8222003", "--", *PROTECTED):
        raise RuntimeError("Adapter/detector path differs from A1")
    for name in git("ls-tree", "-r", "--name-only", "8222003", "--", *PROTECTED).decode().splitlines():
        if (ROOT / name).read_bytes().replace(b"\r\n", b"\n") != git("show", f"8222003:{name}").replace(b"\r\n", b"\n"):
            raise RuntimeError("Adapter/detector working bytes differ")
    old_blob = committed_blob(ORIGINAL / "manifest.json", "8222003")
    if hashlib.sha256(old_blob).hexdigest() != ORIGINAL_HASH:
        raise RuntimeError("Original manifest digest mismatch")
    old = json.loads(old_blob)
    for name, sha in old["sha256"].items():
        if hashlib.sha256(committed_blob(ORIGINAL / name, "8222003")).hexdigest() != sha:
            raise RuntimeError("Original ID-list digest mismatch")
    a2_blob = committed_blob(A2 / "manifest.json", "999b28a")
    a2 = json.loads(a2_blob)
    for name, sha in a2["sha256"].items():
        if hashlib.sha256(committed_blob(A2 / name, "999b28a")).hexdigest() != sha:
            raise RuntimeError("A2 ID-list digest mismatch")
    committed_blob(A2 / "manifest.sha256", "999b28a")
    committed_blob(ROOT / "reports/external/trail_prereg_a2.md", DISCLOSURE)
    ids = set((A2 / "trail_a.txt").read_text().splitlines())
    b_ids = set((A2 / "trail_b.txt").read_text().splitlines())
    if len(ids) != 64 or len(b_ids) != 63 or ids & b_ids or ids & set(EXCLUDED):
        raise RuntimeError("A2 cohort membership differs")
    if set(old["join_audit"]["gaia"]["traces_without_labels"]) != set(EXCLUDED):
        raise RuntimeError("Predeclared exclusion IDs differ")
    catalog = json.loads((PRIVATE / "trail_a_catalog.json").read_text())
    if catalog["revision"] != REVISION or set(catalog["entries"]) != ids or catalog["a2_manifest_sha256"] != hashlib.sha256(a2_blob).hexdigest():
        raise RuntimeError("A-only catalog provenance differs")
    expected_files = set()
    split_counts = Counter()
    for tid, row in catalog["entries"].items():
        split_counts[row["split"]] += 1
        prefix = "GAIA" if row["split"] == "gaia" else "SWE Bench"
        expected = {"trace": f"{prefix}/{tid}.json", "labels": f"processed_annotations_{row['split']}/{tid}.json"}
        if row["paths"] != expected:
            raise RuntimeError("Noncanonical A-only file path")
        for path in expected.values():
            expected_files.add(path)
            target = PRIVATE / "a2_source" / path
            marker = PRIVATE / "a2_source/.cache/huggingface/download" / (path + ".metadata")
            if not marker.is_file() or marker.read_text().splitlines()[0] != REVISION or digest(target) != catalog["sha256"][path]:
                raise RuntimeError("Pinned on-disk A data differs")
    if split_counts != {"gaia": 50, "swe_bench": 14} or set(catalog["sha256"]) != expected_files:
        raise RuntimeError("Unexpected A file inventory")
    repo = hallucination.NLI_MODEL
    pin = json.loads((ROOT / ".github/model-revisions.json").read_text())[repo]
    snapshot = Path(HF_HUB_CACHE) / ("models--" + repo.replace("/", "--")) / "snapshots" / pin
    required = ("config.json", "model.safetensors", "tokenizer.json")
    if not all((snapshot / n).is_file() for n in required):
        raise RuntimeError("STOP: exact model missing from local cache")
    if (ROOT / repo / ".nexus-model-revision").read_text().strip() != pin:
        raise RuntimeError("Staged model revision differs")
    for source in snapshot.rglob("*"):
        if source.is_file() and source.suffix in {".json", ".safetensors", ".txt", ".model"}:
            if digest(source) != digest(ROOT / repo / source.relative_to(snapshot)):
                raise RuntimeError("Staged model differs from pinned cache")
    report = {"status": "PASS", "dataset_revision": REVISION, "adapter_detector_diff": "empty against 8222003",
        "split_manifest_sha256": ORIGINAL_HASH, "trail_a_manifest_sha256": A_HASH,
        "a2_manifest_sha256": hashlib.sha256(a2_blob).hexdigest(), "exclusions": EXCLUDED,
        "A_counts": dict(split_counts), "nli_revision": pin, "frozen_checks": check_frozen()}
    return report, catalog, ids


def save_state(state):
    temp = STATE.with_suffix(".tmp")
    temp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, STATE)


def now():
    return datetime.now(timezone.utc).isoformat()


def score(resume_reason: str | None):
    pre, catalog, ids = preflight()
    code_commit = git("rev-parse", "HEAD").decode().strip()
    for path in ("scripts/external/score_trail.py", "tests/unit/external/test_score_trail.py"):
        committed_blob(ROOT / path, "HEAD")
    if STATE.exists():
        state = json.loads(STATE.read_text())
        if state["status"] != "failed" or not resume_reason:
            raise RuntimeError("Existing run blocks another scoring run")
    else:
        if resume_reason or OUTPUT.exists():
            raise RuntimeError("Invalid retry or existing output")
        state = {"status": "running", "completed_ids": [], "attempts": [],
            "counts": {s: {c: fresh_counts() for c in CLASSES} for s in ("gaia", "swe_bench")},
            "unmapped_category_fingerprints": {}, "workload": {}, "preflight": pre}
        # Exclusive create prevents two concurrent initial runs.
        with STATE.open("x", encoding="utf-8") as stream:
            json.dump(state, stream)
    attempt = {"started_at_utc": now(), "scoring_code_commit": code_commit, "resume_after_crash_reason": resume_reason,
               "completed_before_attempt": len(state["completed_ids"])}
    state["attempts"].append(attempt)
    state["status"] = "running"
    save_state(state)
    started = time.perf_counter()
    try:
        with (PRIVATE / "trail_a_runtime.log").open("a", encoding="utf-8") as log:
            with redirect_stdout(log), redirect_stderr(log):
                hallucination._nli()  # Exact, verified local model, offline; no fallback.
            thresholds = pipeline.load_thresholds()
            remaining = ids - set(state["completed_ids"])
            for tid, split, source, label in load_requested(catalog["entries"], remaining, PRIVATE / "a2_source"):
                tick = time.perf_counter()
                trace_counts = copy.deepcopy(state["counts"][split])
                trace_categories = dict(state["unmapped_category_fingerprints"])
                trace_workload = copy.deepcopy(state["workload"])
                with redirect_stdout(log), redirect_stderr(log):
                    view = convert_for_evaluation(source)
                if view is None:
                    # This exclusion is declared in the original protocol.
                    # It is determined before labels/outputs are examined.
                    for cls in CLASSES:
                        add_observation(trace_counts[cls], None, None, exclusion="conversion_failure")
                    state["counts"][split] = trace_counts
                    state.setdefault("conversion_failure_ids", []).append(tid)
                    state["completed_ids"].append(tid)
                    save_state(state)
                    print(json.dumps({"TRAIL_A_completed": len(state["completed_ids"]), "of": 64}), flush=True)
                    continue
                with redirect_stdout(log), redirect_stderr(log):
                    gold, gold_locations, unmapped = map_labels(label, view)
                    reached, reason = applicability(view)
                    premises = hallucination.retrieved_context(view)
                    units = hallucination.premise_units(premises)
                    claims = hallucination.claims(view.final_output or "", view.root_input or "")
                    scores = pipeline.compute_scores(view)  # Exactly once per completed trace.
                    if reached != (scores.halluc is not None):
                        raise RuntimeError("NLI applicability disagrees with frozen output")
                    flags = pipeline.fired(scores, thresholds)
                    for cls in CLASSES:
                        counts = trace_counts[cls]
                        exclusion = "malformed_category_or_location" if gold[cls] is None else None
                        abstention = None
                        if cls == "HALLUCINATION" and exclusion is None:
                            if not reached:
                                abstention = reason
                            elif reason:
                                exclusion = reason
                        add_observation(counts, gold[cls], flags[cls], abstention=abstention, exclusion=exclusion)
                        if cls != "HALLUCINATION" and not exclusion and gold[cls] and flags[cls]:
                            loc = counts["localization"]
                            if not gold_locations[cls]:
                                loc["ambiguous_gold_true_positives"] += 1
                            else:
                                evidence = from_detector({"pred": cls}, view)
                                if evidence is None:
                                    loc["missing_locator_true_positives"] += 1
                                else:
                                    loc["eligible_true_positives"] += 1
                                    loc["matched_within_1"] += int(any(abs(evidence.step - p) <= 1 for p in gold_locations[cls]))
                    for key, count in unmapped.items():
                        trace_categories[key] = trace_categories.get(key, 0) + count
                    chars = sum(len(p) for p in premises)
                    bucket = "no_source" if not chars else "under_6000_chars" if chars < 6000 else "6000_plus_chars"
                    work = trace_workload.setdefault(bucket, {"traces": 0, "nli_pairs": 0,
                        "runtime_seconds": 0.0, "max_premise_characters": 0})
                    work["traces"] += 1
                    work["nli_pairs"] += len(units) * len(claims) if reached else 0
                    work["runtime_seconds"] += time.perf_counter() - tick
                    work["max_premise_characters"] = max(work["max_premise_characters"], max(map(len, premises), default=0))
                    del scores, flags, label, source, view, premises, units, claims
                state["counts"][split] = trace_counts
                state["unmapped_category_fingerprints"] = trace_categories
                state["workload"] = trace_workload
                state["completed_ids"].append(tid)
                save_state(state)
                print(json.dumps({"TRAIL_A_completed": len(state["completed_ids"]), "of": 64}), flush=True)
        if set(state["completed_ids"]) != ids:
            raise RuntimeError("Incomplete A run")
        attempt["status"] = "complete"
        attempt["runtime_seconds"] = time.perf_counter() - started
        attempt["finished_at_utc"] = now()
        overall = {c: fresh_counts() for c in CLASSES}
        for split in state["counts"].values():
            for cls, values in split.items():
                for key in ("tp", "fp", "fn", "tn"):
                    overall[cls][key] += values[key]
                for key in ("abstentions", "exclusions", "localization"):
                    for name, count in values[key].items():
                        overall[cls][key][name] = overall[cls][key].get(name, 0) + count
        result = {"scope": "TRAIL-A only", "cohort_flow": {"original_test": 133, "predeclared_join_exclusions": 6,
            "reserved_TRAIL_B": 63, "TRAIL_A": 64, "TRAIL_A_by_split": {"gaia": 50, "swe_bench": 14}},
            "classes": {c: summarize(v) for c, v in overall.items()},
            "by_split": {s: {c: summarize(v) for c, v in values.items()} for s, values in state["counts"].items()},
            "not_scored": ["PLAN_DRIFT", "CONTEXT_BLEED"],
            "localization_scope": "LOOP/MISFIRE only; conditional on trace TP, unambiguous gold and existing locator; +/-1 completion-order span. HALLUCINATION omitted: no pre-existing unambiguous locator.",
            "unmapped_category_fingerprints": state["unmapped_category_fingerprints"], "workload": state["workload"],
            "conversion_failure_ids": state.get("conversion_failure_ids", []),
            "provenance": {**pre, "prereg_commits": [git("rev-parse", c).decode().strip() for c in ("8bc721b", "8222003")],
                "a2_commit": git("rev-parse", "999b28a").decode().strip(), "disclosure_commit": DISCLOSURE,
                "scoring_code_commit": state["attempts"][0]["scoring_code_commit"], "attempts": state["attempts"],
                "detector_config": "phase2-detectors-frozen", "detector_thresholds": thresholds,
                "date_timezone": "America/New_York",
                "date": datetime.fromisoformat(state["attempts"][0]["started_at_utc"]).astimezone(LOCAL_ZONE).date().isoformat(),
                "started_at_utc": state["attempts"][0]["started_at_utc"],
                "finished_at_utc": now(), "runtime_seconds": sum(a.get("runtime_seconds", 0) for a in state["attempts"]),
                "machine": {"hostname": platform.node(), "platform": platform.platform(), "processor": platform.processor(),
                    "logical_cpus": os.cpu_count(), "python": platform.python_version()},
                "scored_once": len(state["attempts"]) == 1, "statement": "scored once" if len(state["attempts"]) == 1 else "crash-only continuation recorded",
                "TRAIL_B_loaded_or_inspected_in_scoring": False, "TRAIL_B_scored": False,
                "prior_mechanical_join_check": "Disclosed and accepted; no categories, evidence or descriptions inspected; no detectors or metrics before A2.",
                "HF_HUB_OFFLINE": True, "TRANSFORMERS_OFFLINE": True}}
        for values in result["classes"].values():
            assert values["evaluated"] + sum(values["abstentions"].values()) + sum(values["exclusions"].values()) == 64
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        state["status"] = "complete"
        save_state(state)
        print(json.dumps({"status": "complete", "cohort": "TRAIL-A", "traces": 64,
                          "runtime_seconds": result["provenance"]["runtime_seconds"]}), flush=True)
    except BaseException as exc:
        attempt["status"] = "failed"
        attempt["runtime_seconds"] = time.perf_counter() - started
        attempt["finished_at_utc"] = now()
        tb = traceback.extract_tb(exc.__traceback__)[-1]
        attempt["failure"] = {"type": type(exc).__name__, "file": Path(tb.filename).name,
                              "function": tb.name, "line": tb.lineno}
        state["status"] = "failed"
        save_state(state)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--resume-after-crash", metavar="FIX_AND_REASON")
    args = parser.parse_args()
    try:
        if args.preflight_only:
            print(json.dumps(preflight()[0], indent=2, sort_keys=True))
        else:
            score(args.resume_after_crash)
    except BaseException as exc:
        # Never print exception messages or source/annotation objects.
        print(json.dumps({"STOP": "scoring/preflight failed", "exception_type": type(exc).__name__}), flush=True)
        raise SystemExit(1) from None
