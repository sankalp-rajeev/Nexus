"""Acquire gated TRAIL and seal ID-only splits before any content inspection.

Run with the project-approved Python. No labels are inspected beyond trace_id.
Raw files and Hub caches stay beneath the Git-excluded private data directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = ROOT / "data/external/trail"
SPLITS = ROOT / "reports/external/trail_split"
REPO = "PatronusAI/TRAIL"
REVISION = "b424ce63d5973d5dcd7169b1bc3c07ccdee276d1"
SEED = 20261113
EXPECTED = {"gaia": 117, "swe_bench": 31}
DEV_COUNTS = {"gaia": 12, "swe_bench": 3}


def acquire() -> None:
    from dotenv import dotenv_values
    from huggingface_hub import HfApi, hf_hub_download

    token = dotenv_values(ROOT / ".env").get("HF_TOKEN")
    if not token:
        raise RuntimeError("HF_TOKEN missing from workspace .env")
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    info = HfApi(token=token).dataset_info(REPO, revision=REVISION)
    for entry in info.siblings:
        if entry.rfilename.endswith(".parquet"):
            hf_hub_download(REPO, entry.rfilename, repo_type="dataset", revision=REVISION,
                            token=token, local_dir=PRIVATE / "snapshot",
                            cache_dir=PRIVATE / "cache")


def parquet_files() -> dict[str, Path]:
    files = {}
    for name in EXPECTED:
        matches = list((PRIVATE / "snapshot/data").glob(f"{name}-*.parquet"))
        if len(matches) != 1:
            raise RuntimeError("Expected exactly one parquet file per split")
        files[name] = matches[0]
    return files


def read_ids() -> tuple[dict[str, list[str]], dict]:
    import pyarrow.parquet as pq

    ids, joins = {}, {}
    for split, path in parquet_files().items():
        traces, labels = [], []
        invalid_labels, missing_label_ids = [], []
        # These columns are JSON strings. Decode solely to obtain join keys;
        # do not examine errors, scores, spans, or annotation descriptions.
        for row in pq.read_table(path, columns=["trace", "labels"]).to_pylist():
            trace = json.loads(row["trace"]) if row["trace"] else None
            try:
                label = json.loads(row["labels"]) if row["labels"] else None
            except json.JSONDecodeError:
                label = None
                invalid_labels.append(trace["trace_id"])
            if trace is not None:
                traces.append(trace["trace_id"])
            if label is not None and label.get("trace_id"):
                labels.append(label["trace_id"])
            elif label is not None:
                missing_label_ids.append(trace["trace_id"])
        if len(traces) != EXPECTED[split] or len(set(traces)) != len(traces):
            raise RuntimeError("Unexpected or duplicate trace count")
        if len(set(labels)) != len(labels):
            raise RuntimeError("Duplicate label join keys")
        if not all(re.fullmatch(r"[0-9a-f]{32}", x) for x in traces + labels):
            raise RuntimeError("Unexpected ID format; refusing to export arbitrary text")
        ids[split] = sorted(traces)
        joins[split] = {"traces_without_labels": sorted(set(traces) - set(labels)),
                        "labels_without_traces": sorted(set(labels) - set(traces)),
                        "row_trace_ids_with_invalid_label_json": sorted(invalid_labels),
                        "row_trace_ids_with_missing_label_trace_id": sorted(missing_label_ids),
                        "joined": len(set(traces) & set(labels))}
    if len(set(sum(ids.values(), []))) != sum(map(len, ids.values())):
        raise RuntimeError("Trace IDs overlap across source splits")
    return ids, joins


def seal() -> dict:
    ids, joins = read_ids()
    rng = random.Random(SEED)
    outputs = {}
    counts = {}
    for split in sorted(ids):
        dev = set(rng.sample(ids[split], DEV_COUNTS[split]))
        for partition, selected in (("dev", dev), ("test", set(ids[split]) - dev)):
            name = f"{partition}_{split}.txt"
            outputs[name] = ("\n".join(sorted(selected)) + "\n").encode("ascii")
            counts[name] = len(selected)
    manifest = {
        "dataset": REPO, "revision": REVISION, "seed": SEED,
        "selection": "random.Random(seed); sorted source split names; sample sorted trace IDs; dev quotas 12 gaia, 3 swe_bench",
        "hash_scope": "Exact ASCII bytes of sorted trace-ID lists, one ID per LF-terminated line; no trace/label content",
        "source_counts": EXPECTED, "partition_counts": counts, "join_audit": joins,
        "sha256": {name: hashlib.sha256(blob).hexdigest() for name, blob in outputs.items()},
    }
    outputs["manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    SPLITS.mkdir(parents=True, exist_ok=True)
    for name, blob in outputs.items():
        target = SPLITS / name
        if target.exists() and target.read_bytes() != blob:
            raise RuntimeError("Existing sealed split differs; refusing to overwrite")
        target.write_bytes(blob)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    git = ["git", "-c", f"safe.directory={ROOT.as_posix()}"]
    branch = subprocess.check_output(git + ["branch", "--show-current"], cwd=ROOT).decode().strip()
    if branch != "external-validation":
        raise RuntimeError("Must run on external-validation")
    subprocess.run(git + ["check-ignore", "-q", "data/external/trail/probe"], cwd=ROOT, check=True)
    if args.download:
        acquire()
    print(json.dumps(seal(), indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Hub errors can contain request details; never expose their messages.
        status = getattr(getattr(exc, "response", None), "status_code", None)
        print(json.dumps({"STOP": type(exc).__name__, "http_status": status}))
        raise SystemExit(1) from None
