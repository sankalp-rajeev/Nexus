"""Pre-stage secret/dev-copy scan of explicit paths; never opens B or parquet."""
import argparse
import fnmatch
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = ROOT / "data/external/trail"


def scan(paths):
    from dotenv import dotenv_values
    blobs = []
    for name in paths:
        path = (ROOT / name).resolve()
        relative = path.relative_to(ROOT).as_posix()
        if (any(fnmatch.fnmatch(relative, pattern) for pattern in (".env*", "data/external/*", "data/*/runs/*", "*.jsonl"))
                or relative in {"README.md", "RESULTS.md"} or relative.startswith("dashboard/")):
            raise RuntimeError("Forbidden commit path")
        blobs.append(path.read_bytes())
    values = dotenv_values(ROOT / ".env")
    secrets = [v.encode() for k, v in values.items() if v and len(v) >= 8
               and any(part in k.upper() for part in ("TOKEN", "KEY", "SECRET", "PASSWORD"))]
    pattern = rb"hf_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    for blob in blobs:
        if any(s in blob for s in secrets) or re.search(pattern, blob):
            raise RuntimeError("Secret or credential pattern detected")
    catalog = json.loads((PRIVATE / "dev_scan_catalog.json").read_text())
    old = json.loads((ROOT / "reports/external/trail_split/manifest.json").read_text())
    dev_ids = set()
    for split in ("gaia", "swe_bench"):
        name = f"dev_{split}.txt"
        raw = (ROOT / "reports/external/trail_split" / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != old["sha256"][name]:
            raise RuntimeError("Dev ID digest mismatch")
        dev_ids.update(raw.decode().splitlines())
    if catalog["cohort"] != "dev-scan" or set(catalog["entries"]) != dev_ids:
        raise RuntimeError("Scan catalog is not exactly the 15 dev traces")
    strings = set()
    def collect(value):
        if isinstance(value, str) and len(value) >= 40:
            strings.add(value.encode())
            strings.add(json.dumps(value, ensure_ascii=False)[1:-1].encode())
        elif isinstance(value, dict):
            for item in value.values(): collect(item)
        elif isinstance(value, list):
            for item in value: collect(item)
    for entry in catalog["entries"].values():
        name = entry["paths"]["trace"]
        raw = (PRIVATE / "dev_scan_source" / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != catalog["sha256"][name]:
            raise RuntimeError("Dev scan source digest mismatch")
        collect(json.loads(raw))
    if any(value in blob for value in strings for blob in blobs):
        raise RuntimeError("Verbatim dev content detected")
    return {"secret_scan": "PASS", "dev_content_copy_scan": "PASS", "explicit_files": len(paths),
            "dev_traces_scanned": 15, "B_files_loaded": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+")
    try:
        print(json.dumps(scan(parser.parse_args().paths)))
    except Exception as exc:
        print(json.dumps({"STOP": "scan failed", "exception_type": type(exc).__name__}))
        raise SystemExit(1) from None
