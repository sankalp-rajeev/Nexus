"""Stage only committed TRAIL-A files at the immutable dataset revision.

Acquisition only, before offline scoring. Never opens the shared parquet files,
B files, or annotation contents. Tokens and runtime diagnostics stay private.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"


def main(dev_scan_only=False):
    from dotenv import dotenv_values
    from huggingface_hub import hf_hub_download
    from scripts.external.prepare_trail import PRIVATE, REVISION, REPO

    logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
    a2 = ROOT / "reports/external/trail_split/a2"
    manifest = json.loads((a2 / "manifest.json").read_text())
    blob = (a2 / "trail_a.txt").read_bytes()
    if hashlib.sha256(blob).hexdigest() != manifest["sha256"]["trail_a.txt"]:
        raise RuntimeError("A ID digest mismatch")
    ids = blob.decode("ascii").splitlines()
    if dev_scan_only:
        ids = []
        old = json.loads((a2.parent / "manifest.json").read_text())
        for split in ("gaia", "swe_bench"):
            name = f"dev_{split}.txt"
            dev_blob = (a2.parent / name).read_bytes()
            if hashlib.sha256(dev_blob).hexdigest() != old["sha256"][name]:
                raise RuntimeError("Dev ID digest mismatch")
            ids.extend(dev_blob.decode("ascii").splitlines())
    gaia = set((a2.parent / ("dev_gaia.txt" if dev_scan_only else "test_gaia.txt")).read_text().splitlines())
    known = set(json.loads((PRIVATE / "access.json").read_text())["files"])
    token = dotenv_values(ROOT / ".env").get("HF_TOKEN")
    if not token:
        raise RuntimeError("Missing HF_TOKEN")
    requests, entries = [], {}
    for tid in ids:
        split = "gaia" if tid in gaia else "swe_bench"
        prefix = "GAIA" if split == "gaia" else "SWE Bench"
        paths = {"trace": f"{prefix}/{tid}.json", "labels": f"processed_annotations_{split}/{tid}.json"}
        if dev_scan_only:
            paths.pop("labels")
        if not all(p in known for p in paths.values()):
            raise RuntimeError("Pinned dataset does not contain an expected A file")
        entries[tid] = {"split": split, "paths": paths}
        requests.extend(paths.values())
    target = PRIVATE / ("dev_scan_source" if dev_scan_only else "a2_source")
    def download(filename):
        path = hf_hub_download(REPO, filename, repo_type="dataset", revision=REVISION,
            token=token, local_dir=target, cache_dir=PRIVATE / "cache")
        with Path(path).open("rb") as stream:
            return filename, hashlib.file_digest(stream, "sha256").hexdigest()
    hashes = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(download, filename) for filename in requests]
        for future in as_completed(futures):
            name, digest = future.result()
            hashes[name] = digest
            if len(hashes) % 16 == 0:
                print(json.dumps({"A_files_staged": len(hashes), "expected": len(requests)}), flush=True)
    catalog = {"cohort": "dev-scan" if dev_scan_only else "TRAIL-A", "revision": REVISION,
        "a2_manifest_sha256": hashlib.sha256((a2 / "manifest.json").read_bytes()).hexdigest(),
        "entries": entries, "sha256": hashes}
    name = "dev_scan_catalog.json" if dev_scan_only else "trail_a_catalog.json"
    (PRIVATE / name).write_text(json.dumps(catalog, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"cohort": catalog["cohort"], "traces_staged": len(entries), "files_staged": len(hashes), "B_files_accessed": 0}))


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--dev-scan-only", action="store_true")
        main(parser.parse_args().dev_scan_only)
    except Exception as exc:
        print(json.dumps({"STOP": "A-only staging failed", "exception_type": type(exc).__name__,
            "http_status": getattr(getattr(exc, "response", None), "status_code", None)}))
        raise SystemExit(1) from None
