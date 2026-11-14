"""A2 partitioning reads committed ID lists only, never dataset rows/labels."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import random

ROOT = Path(__file__).resolve().parents[2]
ORIGINAL = ROOT / "reports/external/trail_split"
DEST = ORIGINAL / "a2"
SEED = 20261114


def partition(original: Path = ORIGINAL, dest: Path = DEST) -> dict:
    old_blob = (original / "manifest.json").read_bytes()
    old = json.loads(old_blob)
    rng = random.Random(SEED)
    partitions = {"trail_a": set(), "trail_b": set()}
    counts = {"trail_a": {}, "trail_b": {}}
    excluded = set()
    for split in sorted(old["join_audit"]):
        excluded.update(old["join_audit"][split]["traces_without_labels"])
    for split in sorted(old["join_audit"]):
        filename = f"test_{split}.txt"
        blob = (original / filename).read_bytes()
        if hashlib.sha256(blob).hexdigest() != old["sha256"][filename]:
            raise RuntimeError("Original ID-list digest mismatch")
        ids = sorted(set(blob.decode("ascii").splitlines()) - excluded)
        chosen = set(rng.sample(ids, (len(ids) + 1) // 2))
        for name, values in (("trail_a", chosen), ("trail_b", set(ids) - chosen)):
            if partitions[name] & values:
                raise RuntimeError("Duplicate cross-source trace IDs")
            partitions[name].update(values)
            counts[name][split] = len(values)
    if partitions["trail_a"] & partitions["trail_b"]:
        raise RuntimeError("A/B overlap")
    files = {name + ".txt": ("\n".join(sorted(values)) + "\n").encode("ascii")
             for name, values in partitions.items()}
    manifest = {"amendment": "A2", "seed": SEED, "dataset_revision": old["revision"],
        "original_manifest_sha256": hashlib.sha256(old_blob).hexdigest(),
        "selection": "random.Random(seed); sorted source names and eligible IDs; sample ceil(n/2) into A per source; complement into B",
        "partition_counts": counts, "excluded_trace_ids": sorted(excluded),
        "sha256": {name: hashlib.sha256(blob).hexdigest() for name, blob in files.items()}}
    files["manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    files["manifest.sha256"] = "".join(f"{hashlib.sha256(blob).hexdigest()}  {name}\n"
                                      for name, blob in sorted(files.items())).encode("ascii")
    dest.mkdir(parents=True, exist_ok=True)
    for name, blob in files.items():
        path = dest / name
        if path.exists() and path.read_bytes() != blob:
            raise RuntimeError("Existing A2 partition differs; refusing overwrite")
        path.write_bytes(blob)
    return manifest


if __name__ == "__main__":
    print(json.dumps(partition(), indent=2, sort_keys=True))
