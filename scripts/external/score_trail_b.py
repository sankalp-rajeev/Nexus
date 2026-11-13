"""Registered once-only B comparison; reuse A scorer metrics, labels and loader.

Only aggregates are published. Each version's completed per-trace checkpoint is
durable before the next version executes. Continuations skip those checkpoints.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "sdk"), str(ROOT)]
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from scripts.external import score_trail as original
from scripts.external.check_frozen import check as check_frozen
from scripts.external.prepare_trail import PRIVATE, REVISION
from scripts.external.trail_dev_check_a1 import applicability
from scripts.external.v2_nli_cache import EntailmentCache
from services.detectors import hallucination, pipeline as v1
from services.detectors_v2 import openinference as c1, pipeline as v2

B_HASH = "7c100a724edd4faabf27ce4b5d84b469d72ae474d6645f496c998c806dbfc72f"
V2_COMMIT = "5660480673c8a4b3b1f2dbbd0dad6b2438ea3284"
NLI_REVISION = "6c749ce3425cd33b46d187e45b92bbf96ee12ec7"
PREREGS = {"original": ("8bc721b", "trail_prereg.md"), "A1": ("8222003", "trail_prereg_a1.md"),
    "A2": ("999b28a", None), "disclosure": ("d19cb86", "trail_prereg_a2.md"),
    "A3": ("0f0eda0", "trail_prereg_a3.md")}
RUN = PRIVATE / "b_scoring"
CATALOG = PRIVATE / "trail_b_catalog.json"
SOURCE = PRIVATE / "b_source"
OUTPUT = ROOT / "results/external/trail_b_test.json"
VERSIONS = ("v1", "v2")
CLASSES = original.CLASSES


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def now():
    return datetime.now(timezone.utc).isoformat()


def metadata_preflight():
    from huggingface_hub.constants import HF_HUB_CACHE
    if Path.cwd().resolve() != ROOT or original.git("branch", "--show-current").decode().strip() != "external-validation":
        raise RuntimeError("Wrong workspace or branch")
    preregs = {}
    for kind, (commit, name) in PREREGS.items():
        full = original.git("rev-parse", commit).decode().strip()
        original.git("merge-base", "--is-ancestor", full, "HEAD")
        preregs[kind] = full
        if name:
            original.committed_blob(ROOT / "reports/external" / name, full)
    old = json.loads(original.committed_blob(original.ORIGINAL / "manifest.json", "8222003"))
    for name, expected in old["sha256"].items():
        if hashlib.sha256(original.committed_blob(original.ORIGINAL / name, "8222003")).hexdigest() != expected:
            raise RuntimeError("Original ID-list checksum mismatch")
    manifest = json.loads(original.committed_blob(original.A2 / "manifest.json", "999b28a"))
    for name, expected in manifest["sha256"].items():
        if hashlib.sha256(original.committed_blob(original.A2 / name, "999b28a")).hexdigest() != expected:
            raise RuntimeError("A2 ID-list checksum mismatch")
    b = original.A2 / "trail_b.txt"
    ids = set(b.read_text().splitlines())
    if original.digest(b) != B_HASH or len(ids) != 63 or ids & set(original.EXCLUDED):
        raise RuntimeError("B membership or checksum mismatch")
    if ids & set((original.A2 / "trail_a.txt").read_text().splitlines()):
        raise RuntimeError("A/B overlap")
    gaia = set((original.ORIGINAL / "test_gaia.txt").read_text().splitlines())
    splits = {tid: "gaia" if tid in gaia else "swe_bench" for tid in ids}
    if Counter(splits.values()) != {"gaia": 49, "swe_bench": 14}:
        raise RuntimeError("B split counts mismatch")
    access = json.loads((PRIVATE / "access.json").read_text())
    if access["revision"] != REVISION or REVISION != "b424ce63d5973d5dcd7169b1bc3c07ccdee276d1":
        raise RuntimeError("On-disk dataset revision mismatch")
    frozen = check_frozen()
    for prefix, commit in (("services/detectors_v2", V2_COMMIT), ("scripts/external/score_trail.py", "0f0eda0"),
            ("scripts/external/trail_dev_check_a1.py", "0f0eda0"), ("scripts/external/v2_nli_cache.py", "0f0eda0")):
        if original.git("diff", commit, "--", prefix):
            raise RuntimeError("Frozen scoring path differs")
        names = original.git("ls-tree", "-r", "--name-only", commit, "--", prefix).decode().splitlines()
        for name in names:
            original.committed_blob(ROOT / name, commit)
    if original.git("ls-files", "--others", "--exclude-standard", "--", "services/detectors_v2"):
        raise RuntimeError("Untracked v2 modules")
    if v2.load_config()["c5_scope"] != "final" or v2.load_config()["name"] != "detectors-v2":
        raise RuntimeError("Frozen config differs")
    pin = json.loads((ROOT / ".github/model-revisions.json").read_text())[hallucination.NLI_MODEL]
    if pin != NLI_REVISION:
        raise RuntimeError("NLI revision mismatch")
    snapshot = Path(HF_HUB_CACHE) / ("models--" + hallucination.NLI_MODEL.replace("/", "--")) / "snapshots" / pin
    if not all((snapshot / n).is_file() for n in ("config.json", "model.safetensors", "tokenizer.json")):
        raise RuntimeError("STOP: exact local model cache missing")
    local = ROOT / hallucination.NLI_MODEL
    if (local / ".nexus-model-revision").read_text().strip() != pin:
        raise RuntimeError("Local model marker differs")
    for path in snapshot.rglob("*"):
        if path.is_file() and path.suffix in {".json", ".safetensors", ".txt", ".model"}:
            if original.digest(path) != original.digest(local / path.relative_to(snapshot)):
                raise RuntimeError("Local model bytes differ")
    pre = {"status": "PASS", "dataset_revision": REVISION, "B_manifest_sha256": B_HASH,
        "cohort": 63, "by_split": dict(Counter(splits.values())), "v2_code_config_identical_to": V2_COMMIT,
        "v1_frozen": frozen, "nli_revision": pin, "local_model_bytes_match": True,
        "prereg_commits": preregs, "loader": "score_trail.load_requested: ID filter before file opens and JSON decode",
        "HF_HUB_OFFLINE": True, "TRANSFORMERS_OFFLINE": True}
    return pre, ids, splits


def preflight():
    pre, ids, splits = metadata_preflight()
    catalog = json.loads(CATALOG.read_text())
    if catalog["revision"] != REVISION or catalog["cohort"] != "TRAIL-B" or set(catalog["entries"]) != ids:
        raise RuntimeError("B-only catalog mismatch")
    if catalog["B_manifest_sha256"] != B_HASH:
        raise RuntimeError("Catalog manifest differs")
    expected_files = set()
    for tid, row in catalog["entries"].items():
        split = splits[tid]
        prefix = "GAIA" if split == "gaia" else "SWE Bench"
        expected = {"trace": f"{prefix}/{tid}.json", "labels": f"processed_annotations_{split}/{tid}.json"}
        if row["split"] != split or row["paths"] != expected:
            raise RuntimeError("Noncanonical B path")
        for name in expected.values():
            expected_files.add(name)
            marker = SOURCE / ".cache/huggingface/download" / (name + ".metadata")
            if marker.read_text().splitlines()[0] != REVISION or original.digest(SOURCE / name) != catalog["sha256"][name]:
                raise RuntimeError("B data revision or bytes differ")
    if set(catalog["sha256"]) != expected_files:
        raise RuntimeError("Unexpected B catalog file inventory")
    actual = {p.relative_to(SOURCE).as_posix() for p in SOURCE.rglob("*.json") if ".cache" not in p.relative_to(SOURCE).parts}
    if actual != expected_files:
        raise RuntimeError("B source directory not exactly the requested 126 files")
    # Mechanical joins only: categories/evidence/descriptions are not inspected.
    joined = sum(1 for _ in original.load_requested(catalog["entries"], ids, SOURCE))
    if joined != 63:
        raise RuntimeError("B join audit incomplete")
    pre.update({"B_files_verified": len(expected_files), "joinable_B_traces": joined,
        "catalog_sha256": original.digest(CATALOG), "A3_committed_before_B_scoring": True})
    return pre, catalog, ids


def observation(gold, flags, reason, *, conversion_failure=False):
    result = {}
    for cls in CLASSES:
        counts = original.fresh_counts()
        exclusion = "conversion_failure" if conversion_failure else "malformed_category_or_location" if gold[cls] is None else None
        abstention = None
        if cls == "HALLUCINATION" and exclusion is None:
            if reason == "source_below_registered_readability_gate":
                exclusion = reason
            elif reason:
                abstention = reason
        original.add_observation(counts, None if conversion_failure else gold[cls],
            None if conversion_failure else flags[cls], exclusion=exclusion, abstention=abstention)
        result[cls] = counts
    return result


def tables(records, version, mapping="primary", split=None):
    counts = {c: original.fresh_counts() for c in CLASSES}
    chosen = [r for r in records if r["version"] == version and (split is None or r["split"] == split)]
    for record in chosen:
        flags = dict(record.get("flags", {}))
        if mapping == "C3_secondary" and version == "v2" and not record.get("conversion_failure"):
            flags["LOOP_DETECTED"] = flags["LOOP_DETECTED"] or flags["TOOL_MISFIRE"]
        current = observation(record.get("gold"), flags, record.get("hallucination_reason"),
            conversion_failure=record.get("conversion_failure", False))
        for cls, values in current.items():
            for key in ("tp", "fp", "fn", "tn"):
                counts[cls][key] += values[key]
            for key in ("abstentions", "exclusions"):
                for reason, n in values[key].items():
                    counts[cls][key][reason] = counts[cls][key].get(reason, 0) + n
    output = {}
    for cls, count in counts.items():
        value = original.summarize(count)
        value.pop("localization")  # No v2 locator was frozen; optional localization is omitted.
        value["cohort_denominator"] = len(chosen)
        value["gold_positive_in_cohort_assessable"] = sum((r.get("gold") or {}).get(cls) is True for r in chosen)
        assert value["evaluated"] + sum(value["abstentions"].values()) + sum(value["exclusions"].values()) == len(chosen)
        output[cls] = value
    return output


def checkpoint_path(tid, version, run=RUN):
    return run / "checkpoints" / f"{tid}.{version}.json"


def version_checkpoint(tid, split, version, gold, view, thresholds, cache, *, run=RUN, compute=None):
    """A completed checkpoint is the transaction boundary; never recompute it."""
    path = checkpoint_path(tid, version, run)
    if path.exists():
        record = json.loads(path.read_text())
        if record["trace_id"] != tid or record["version"] != version or record["split"] != split or record["gold"] != gold:
            raise RuntimeError("Completed checkpoint identity differs")
        return record
    tick = time.perf_counter()
    if view is None:
        record = {"trace_id": tid, "split": split, "version": version, "gold": gold, "conversion_failure": True}
    else:
        compute = compute or (v1.compute_scores if version == "v1" else v2.compute_scores)
        scores = compute(view)
        reached, reason = applicability(view)
        if version == "v1" and reached != (scores.halluc is not None):
            raise RuntimeError("V1 applicability disagrees with output")
        if version == "v2":
            reason = scores.hallucination_reason
        flags = v1.fired(scores, thresholds)
        if set(CLASSES) - set(flags):
            raise RuntimeError("Emitted class names differ")
        record = {"trace_id": tid, "split": split, "version": version, "gold": gold,
            "flags": flags, "hallucination_reason": reason,
            "raw": {"loop": bool(scores.loop), "misfire": bool(scores.misfire), "bleed": scores.bleed,
                "drift": scores.drift, "hallucination": scores.halluc}}
    record["runtime_seconds"] = time.perf_counter() - tick
    save(path, record)
    return record


def aggregate(state, records):
    expected = {(tid, version) for tid in state["ids"] for version in VERSIONS}
    if {(r["trace_id"], r["version"]) for r in records} != expected or len(records) != len(expected):
        raise RuntimeError("Incomplete or duplicate version checkpoints")
    mappings = {}
    for mapping in ("primary", "C3_secondary"):
        mappings[mapping] = {version: {"classes": tables(records, version, mapping),
            "by_split": {split: tables(records, version, mapping, split) for split in ("gaia", "swe_bench")}} for version in VERSIONS}
    attempts = state["attempts"]
    pre = state["preflight"]
    return {"scope": "TRAIL-B held-out once-only v1-vs-v2 comparison", "cohort_flow": {
        "TRAIL_B": 63, "by_split": {"gaia": 49, "swe_bench": 14}, "prior_join_exclusions_outside_B": 6},
        "mappings": mappings, "not_scored": ["PLAN_DRIFT", "CONTEXT_BLEED"],
        "localization": "Omitted for both versions: no v2 span locator was frozen; optional secondary measure only.",
        "conversion_failure_ids": sorted({r["trace_id"] for r in records if r.get("conversion_failure")}),
        "unmapped_category_fingerprints": dict(sum((Counter(v) for v in state.get("category_fingerprints_by_trace", {}).values()), Counter())),
        "provenance": {**pre, "v2_commit": V2_COMMIT, "scoring_code_commit": attempts[0]["scoring_code_commit"],
            "attempts": attempts, "detector_configs": {"v1": "phase2-detectors-frozen", "v2": "detectors-v2"},
            "thresholds": v1.load_thresholds(), "started_at_utc": attempts[0]["started_at_utc"],
            "finished_at_utc": now(), "date": datetime.fromisoformat(attempts[0]["started_at_utc"]).astimezone(original.LOCAL_ZONE).date().isoformat(),
            "date_timezone": "America/New_York", "runtime_seconds": sum(a["runtime_seconds"] for a in attempts),
            "per_version_runtime_seconds": {v: sum(r["runtime_seconds"] for r in records if r["version"] == v) for v in VERSIONS},
            "scored_once": True, "statement": "scored once; completed per-version checkpoints never rescored",
            "crash_continuation": len(attempts) > 1, "machine": {"hostname": platform.node(), "platform": platform.platform(),
                "python": platform.python_version(), "logical_cpus": os.cpu_count()},
            "label_mapping": "Unchanged score_trail.map_labels; original primary; C3 v2 LOOP OR MISFIRE secondary",
            "v1_TRAIL_A_result_sha256": state["immutable_sha256"][str(original.OUTPUT)],
            "prior_mechanical_join_check": "Disclosed in d19cb86 and A3; no label categories, evidence or descriptions inspected then"}}


def score(resume_reason=None):
    pre, catalog, ids = preflight()
    for name in ("scripts/external/score_trail_b.py", "tests/unit/external/test_score_trail_b.py"):
        original.committed_blob(ROOT / name, "HEAD")
    RUN.mkdir(exist_ok=True)
    state_path = RUN / "run_state.json"
    if OUTPUT.exists():
        raise RuntimeError("Completed result blocks scoring")
    if state_path.exists():
        state = json.loads(state_path.read_text())
        if state["status"] != "failed" or not resume_reason:
            raise RuntimeError("Existing run requires documented crash-only continuation")
        if state["preflight"] != pre or set(state["ids"]) != ids:
            raise RuntimeError("Preflight changed since initial attempt")
    else:
        if resume_reason or list((RUN / "checkpoints").glob("*.json")):
            raise RuntimeError("Unexpected retry or prior checkpoints")
        immutable = [original.OUTPUT, ROOT / "reports/external/trail_results.md", original.STATE,
            ROOT / "reports/external/trail_v2_dev.md"]
        state = {"status": "running", "ids": sorted(ids), "completed_ids": [], "attempts": [], "preflight": pre,
            "immutable_sha256": {str(p): original.digest(p) for p in immutable}}
        with state_path.open("x", encoding="utf-8") as stream:
            json.dump(state, stream)
    lock = RUN / "active.lock"
    with lock.open("x", encoding="utf-8") as stream:
        stream.write(str(os.getpid()))
    attempt = {"scoring_code_commit": original.git("rev-parse", "HEAD").decode().strip(), "started_at_utc": now(),
        "resume_after_crash_fix_and_reason": resume_reason, "completed_version_checkpoints_before": len(list((RUN / "checkpoints").glob("*.json")))}
    state["attempts"].append(attempt)
    state["status"] = "running"
    save(state_path, state)
    started = time.perf_counter()
    cache = None
    try:
        with (RUN / "runtime.log").open("a", encoding="utf-8") as log:
            with redirect_stdout(log), redirect_stderr(log):
                cache = EntailmentCache(RUN / "entailment.sqlite", NLI_REVISION)
            thresholds = v1.load_thresholds()
            for tid, split, source, label in original.load_requested(catalog["entries"], ids - set(state["completed_ids"]), SOURCE):
                with redirect_stdout(log), redirect_stderr(log):
                    base = original.convert_for_evaluation(source)
                    gold, _, unmapped = original.map_labels(label, base) if base is not None else (None, None, {})
                    state.setdefault("category_fingerprints_by_trace", {})[tid] = unmapped
                    for version in VERSIONS:
                        state["inflight"] = {"trace_id": tid, "version": version}
                        save(state_path, state)
                        view = base if version == "v1" or base is None else c1.adapt(base)
                        model = hallucination._nli()
                        predict = model.predict
                        model.predict = cache.predict
                        try:
                            version_checkpoint(tid, split, version, gold, view, thresholds, cache)
                        finally:
                            model.predict = predict
                    state["completed_ids"].append(tid)
                    state.pop("inflight", None)
                    save(state_path, state)
                print(json.dumps({"TRAIL_B_completed_both_versions": len(state["completed_ids"]), "of": 63}), flush=True)
        for name, expected in state["immutable_sha256"].items():
            if original.digest(Path(name)) != expected:
                raise RuntimeError("Protected historical artifact changed")
        records = [json.loads(checkpoint_path(tid, version).read_text()) for tid in sorted(ids) for version in VERSIONS]
        attempt.update({"status": "complete", "runtime_seconds": time.perf_counter() - started, "finished_at_utc": now()})
        result = aggregate(state, records)
        save(OUTPUT, result)
        state["status"] = "complete"
        save(state_path, state)
        print(json.dumps({"TRAIL_B_status": "complete", "traces": 63, "versions": 2,
            "runtime_seconds": result["provenance"]["runtime_seconds"], "crash_continuation": result["provenance"]["crash_continuation"]}), flush=True)
    except BaseException as exc:
        with (RUN / "failure.log").open("a", encoding="utf-8") as failure_log:
            traceback.print_exc(file=failure_log)
        tb = traceback.extract_tb(exc.__traceback__)[-1]
        attempt.update({"status": "failed", "runtime_seconds": time.perf_counter() - started, "finished_at_utc": now(),
            "failure": {"type": type(exc).__name__, "file": Path(tb.filename).name, "line": tb.lineno, "function": tb.name}})
        state["status"] = "failed"
        save(state_path, state)
        raise
    finally:
        if cache is not None:
            cache.close()
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-metadata-only", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--resume-after-crash", metavar="FIX_AND_REASON")
    args = parser.parse_args()
    try:
        if args.preflight_metadata_only:
            print(json.dumps(metadata_preflight()[0], indent=2, sort_keys=True))
        elif args.preflight_only:
            print(json.dumps(preflight()[0], indent=2, sort_keys=True))
        else:
            score(args.resume_after_crash)
    except BaseException as exc:
        print(json.dumps({"STOP": "B scoring/preflight failed", "exception_type": type(exc).__name__}), flush=True)
        raise SystemExit(1) from None
