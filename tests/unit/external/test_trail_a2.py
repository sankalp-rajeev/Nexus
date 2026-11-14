"""Synthetic ID-only A2 partition checks."""
import hashlib
import json
import pytest
from scripts.external.partition_trail_a2 import partition


def test_partition_is_stratified_deterministic_disjoint_and_immutable(tmp_path):
    original = tmp_path / "original"
    original.mkdir()
    manifest = {"revision": "synthetic", "sha256": {}, "join_audit": {}}
    for split, first, count in (("gaia", 1, 6), ("swe_bench", 20, 4)):
        filename = f"test_{split}.txt"
        blob = "".join(f"{i:032x}\n" for i in range(first, first+count)).encode()
        (original / filename).write_bytes(blob)
        manifest["sha256"][filename] = hashlib.sha256(blob).hexdigest()
        manifest["join_audit"][split] = {"traces_without_labels": [f"{1:032x}"] if split == "gaia" else []}
    (original / "manifest.json").write_text(json.dumps(manifest))
    dest = tmp_path / "a2"
    result = partition(original, dest)
    assert result == partition(original, dest)
    assert result["partition_counts"] == {"trail_a": {"gaia": 3, "swe_bench": 2}, "trail_b": {"gaia": 2, "swe_bench": 2}}
    a = set((dest / "trail_a.txt").read_text().splitlines())
    b = set((dest / "trail_b.txt").read_text().splitlines())
    assert not a & b and len(a | b) == 9 and f"{1:032x}" not in a | b
    (dest / "trail_a.txt").write_text("tampered\n")
    with pytest.raises(RuntimeError, match="refusing overwrite"):
        partition(original, dest)
