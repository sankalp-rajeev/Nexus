"""Scan explicit publication paths against secrets and dev+A content, never B."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.external.scan_external import ROOT, scan
from scripts.external.v2_data import trail_records

# Part 3 explicitly authorizes counts by exception type. These are schema
# identifiers, not exception messages. Permit only the two observed identifiers,
# only in the diagnosis's integer-count table cells; never elsewhere or as prose.
ERROR_TYPE_COUNT_LABEL_SHA256 = frozenset((
    "dbaee736f8483b4f9ca2835372989048a045272e5966dc7830b50366b733a15b",
    "da9f469c5fdf6ef9190625e794da04e129300587bd2cd35010003a2113bda92a",
))


def unapproved_copy(blob, strings, relative):
    for value in strings:
        if value not in blob:
            continue
        if (relative == "reports/external/trail_diagnosis.md"
                and hashlib.sha256(value).hexdigest() in ERROR_TYPE_COUNT_LABEL_SHA256
                and re.fullmatch(rb"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+", value)):
            count_row = rb"^\| `" + re.escape(value) + rb"` \| [0-9]+ \|\r?$"
            if value not in re.sub(count_row, b"", blob, flags=re.M):
                continue
        return True
    return False


def check(paths, *, allow_publication=False):
    result = scan(paths, allow_publication=allow_publication)
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
    if any(unapproved_copy(blob, strings, path) for path, blob in zip(paths, blobs)):
        raise RuntimeError("Verbatim development content detected")
    return {**result, "dev_plus_A_content_copy_scan": "PASS", "development_traces_scanned": count}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-publication", action="store_true",
                        help="allow explicitly requested README/RESULTS/dashboard publication; data/env paths remain forbidden")
    parser.add_argument("paths", nargs="+")
    try:
        args = parser.parse_args()
        print(json.dumps(check(args.paths, allow_publication=args.allow_publication)))
    except Exception as exc:
        print(json.dumps({"STOP": "scan failed", "exception_type": type(exc).__name__}))
        raise SystemExit(1) from None
