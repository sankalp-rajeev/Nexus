"""Acquire only the 63 committed B IDs at the pinned dataset revision.

Acquisition precedes offline scoring. No model is fetched, no dataset JSON is
decoded, and no shared parquet is opened. Credentials are never printed.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import json
import logging
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
from scripts.external.prepare_trail import PRIVATE, REPO, REVISION

B_HASH = "7c100a724edd4faabf27ce4b5d84b469d72ae474d6645f496c998c806dbfc72f"


def main():
    from dotenv import dotenv_values
    from huggingface_hub import hf_hub_download
    logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
    git = ["git", "-c", f"safe.directory={ROOT.as_posix()}"]
    path = ROOT / "reports/external/trail_split/a2/trail_b.txt"
    blob = path.read_bytes()
    if hashlib.sha256(blob).hexdigest() != B_HASH or blob != subprocess.check_output(git + ["show", "999b28a:reports/external/trail_split/a2/trail_b.txt"], cwd=ROOT):
        raise RuntimeError("B manifest mismatch")
    ids = blob.decode("ascii").splitlines()
    if len(ids) != 63 or len(set(ids)) != 63:
        raise RuntimeError("B count mismatch")
    gaia = set((ROOT / "reports/external/trail_split/test_gaia.txt").read_text().splitlines())
    access = json.loads((PRIVATE / "access.json").read_text())
    if access["revision"] != REVISION:
        raise RuntimeError("Dataset revision mismatch")
    known = set(access["files"])
    token = dotenv_values(ROOT / ".env").get("HF_TOKEN")
    if not token:
        raise RuntimeError("Missing HF_TOKEN")
    entries, requests = {}, []
    for tid in ids:
        split = "gaia" if tid in gaia else "swe_bench"
        prefix = "GAIA" if split == "gaia" else "SWE Bench"
        paths = {"trace": f"{prefix}/{tid}.json", "labels": f"processed_annotations_{split}/{tid}.json"}
        if not all(name in known for name in paths.values()):
            raise RuntimeError("Pinned inventory missing B file")
        entries[tid] = {"split": split, "paths": paths}
        requests.extend(paths.values())
    target = PRIVATE / "b_source"
    catalog_path = PRIVATE / "trail_b_catalog.json"
    if catalog_path.exists():
        raise RuntimeError("B catalog already staged; do not replace it")
    def download(name):
        path = hf_hub_download(REPO, name, repo_type="dataset", revision=REVISION, token=token,
            local_dir=target, cache_dir=PRIVATE / "cache")
        with Path(path).open("rb") as stream:
            return name, hashlib.file_digest(stream, "sha256").hexdigest()
    hashes = {}
    with (PRIVATE / "b_staging_runtime.log").open("a", encoding="utf-8") as log:
        with redirect_stdout(log), redirect_stderr(log), ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(download, name) for name in requests]
            for future in as_completed(futures):
                name, digest = future.result()
                hashes[name] = digest
    catalog = {"cohort": "TRAIL-B", "revision": REVISION, "B_manifest_sha256": B_HASH,
        "entries": entries, "sha256": hashes}
    catalog_path.write_text(json.dumps(catalog, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"B_traces_staged": len(entries), "B_files_staged": len(hashes),
        "dataset_revision": REVISION, "dataset_JSON_decoded_during_staging": 0, "models_downloaded": 0}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"STOP": "B staging failed", "exception_type": type(exc).__name__,
            "http_status": getattr(getattr(exc, "response", None), "status_code", None)}))
        raise SystemExit(1) from None
