"""Scan explicit publication paths against secrets and dev+A content, never B."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.external.scan_external import ROOT, scan
from scripts.external.v2_data import trail_records


def check(paths):
    result = scan(paths)
    blobs = [(ROOT / path).read_bytes() for path in paths]
    strings = set()

    def collect(value):
        if isinstance(value, str) and len(value) >= 40:
            strings.add(value.encode())
            strings.add(json.dumps(value, ensure_ascii=False)[1:-1].encode())
        elif isinstance(value, dict):
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    count = 0
    for _, _, trace, labels in trail_records():
        collect(trace)
        collect(labels)
        count += 1
    if any(value in blob for value in strings for blob in blobs):
        raise RuntimeError("Verbatim development content detected")
    return {**result, "dev_plus_A_content_copy_scan": "PASS", "development_traces_scanned": count}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+")
    try:
        print(json.dumps(check(parser.parse_args().paths)))
    except Exception as exc:
        print(json.dumps({"STOP": "scan failed", "exception_type": type(exc).__name__}))
        raise SystemExit(1) from None
