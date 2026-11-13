"""Stage only 15 dev labels; reuse private dev/A traces. Never opens B/parquet."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"


def main():
    from dotenv import dotenv_values
    from huggingface_hub import hf_hub_download
    from scripts.external.prepare_trail import PRIVATE, REVISION, REPO
    old = json.loads((ROOT / "reports/external/trail_split/manifest.json").read_text())
    dev = json.loads((PRIVATE / "dev_scan_catalog.json").read_text())
    a = json.loads((PRIVATE / "trail_a_catalog.json").read_text())
    ids = set()
    for split in ("gaia", "swe_bench"):
        name = f"dev_{split}.txt"
        blob = (ROOT / "reports/external/trail_split" / name).read_bytes()
        if hashlib.sha256(blob).hexdigest() != old["sha256"][name]:
            raise RuntimeError("Dev ID digest mismatch")
        ids.update(blob.decode().splitlines())
    if set(dev["entries"]) != ids:
        raise RuntimeError("Dev catalog membership mismatch")
    a_ids = set((ROOT / "reports/external/trail_split/a2/trail_a.txt").read_text().splitlines())
    if set(a["entries"]) != a_ids or a_ids & ids:
        raise RuntimeError("A membership mismatch")
    token = dotenv_values(ROOT / ".env").get("HF_TOKEN")
    if not token:
        raise RuntimeError("Missing HF_TOKEN")
    target = PRIVATE / "v2_dev_source"
    def download(tid):
        split = dev["entries"][tid]["split"]
        name = f"processed_annotations_{split}/{tid}.json"
        path = hf_hub_download(REPO, name, repo_type="dataset", revision=REVISION, token=token,
            local_dir=target, cache_dir=PRIVATE / "cache")
        return tid, name, hashlib.sha256(Path(path).read_bytes()).hexdigest()
    labels = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for tid, name, digest in pool.map(download, sorted(ids)):
            labels[tid] = name, digest
    entries = {}
    for cohort, catalog, trace_base, label_base in (("dev",dev,"dev_scan_source","v2_dev_source"),("A",a,"a2_source","a2_source")):
        for tid, row in catalog["entries"].items():
            trace_name = row["paths"]["trace"]
            label_name, label_hash = labels[tid] if cohort == "dev" else (row["paths"]["labels"],catalog["sha256"][row["paths"]["labels"]])
            entries[tid] = {"cohort":cohort,"split":row["split"],
                "paths":{"trace":f"{trace_base}/{trace_name}","labels":f"{label_base}/{label_name}"},
                "sha256":{"trace":catalog["sha256"][trace_name],"labels":label_hash}}
    (PRIVATE / "v2_development_catalog.json").write_text(json.dumps({"revision":REVISION,"entries":entries},indent=2,sort_keys=True)+"\n")
    print(json.dumps({"staged_dev_labels":len(labels),"development_traces":len(entries),"A":64,"dev":15,"B_files_accessed":0}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"STOP":"dev staging failed","type":type(exc).__name__,
            "http_status":getattr(getattr(exc,"response",None),"status_code",None)}))
        raise SystemExit(1) from None
