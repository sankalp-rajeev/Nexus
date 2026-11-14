"""Structural development-only loaders; no TRAIL B or NexusBench TEST decode."""
import csv
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = ROOT / "data/external/trail"


def trail_catalog():
    catalog = json.loads((PRIVATE / "v2_development_catalog.json").read_text())
    expected = set()
    for name in ("dev_gaia.txt","dev_swe_bench.txt","a2/trail_a.txt"):
        expected.update((ROOT / "reports/external/trail_split" / name).read_text().splitlines())
    if set(catalog["entries"]) != expected or len(expected) != 79:
        raise RuntimeError("Catalog is not exactly dev plus A")
    if catalog["revision"] != "b424ce63d5973d5dcd7169b1bc3c07ccdee276d1":
        raise RuntimeError("Dataset revision mismatch")
    return catalog


def trail_records(requested=None):
    catalog = trail_catalog()
    requested = set(catalog["entries"]) if requested is None else set(requested)
    if not requested <= set(catalog["entries"]):
        raise RuntimeError("Non-development TRAIL ID requested")
    for tid,row in sorted(catalog["entries"].items()):
        if tid not in requested:
            continue
        objects = {}
        for key in ("trace","labels"):
            path = (PRIVATE / row["paths"][key]).resolve()
            path.relative_to(PRIVATE.resolve())
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != row["sha256"][key]:
                raise RuntimeError("Development source checksum changed")
            objects[key] = json.loads(raw)
            if objects[key].get("trace_id") != tid:
                raise RuntimeError("Trace-ID join mismatch")
        yield tid,row,objects["trace"],objects["labels"]


def nexus_dev_rows(path=None):
    path = path or ROOT / "data/nexusbench/labels.csv"
    rows = []
    with Path(path).open(encoding="utf-8",newline="") as stream:
        reader = csv.reader(stream)
        header = next(reader)
        split_column = header.index("split")
        for fields in reader:
            if fields[split_column] != "dev":
                continue  # Do not construct or inspect a TEST label record.
            rows.append(dict(zip(header,fields)))
    return rows


def nexus_dev_traces(ids, path=None, *, decode=json.loads):
    path = path or ROOT / "data/nexusbench/traces.jsonl"
    found = {}
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            match = re.search(r'"trace_id"\s*:\s*"([^"\\]+)"',line)
            if not match or match[1] not in ids:
                continue  # Same ID-first structural filter as the existing DEV adapter.
            obj = decode(line)
            found[obj["trace_id"]] = obj
    if set(found) != set(ids):
        raise RuntimeError("NexusBench DEV IDs incomplete")
    return found
