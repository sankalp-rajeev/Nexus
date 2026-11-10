"""Integrity of the committed NexusBench data (runs in CI).

* The test-set manifest matches the committed traces + labels byte for byte
  (the test set is frozen; any change must be deliberate and visible).
* labels.csv is exactly what the labeler computes from traces.jsonl.
"""

from __future__ import annotations

import os

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DATA = os.path.join(REPO, "data", "nexusbench")
HAVE = all(os.path.exists(os.path.join(DATA, f))
           for f in ("traces.jsonl", "labels.csv", "manifest.sha256"))

pytestmark = pytest.mark.skipif(not HAVE, reason="NexusBench data not generated")


def test_manifest_matches_committed_test_set():
    import hashlib

    from bench.generate import compute_manifest_lines

    lines = compute_manifest_lines(DATA)
    with open(os.path.join(DATA, "manifest.sha256"), encoding="utf-8") as fh:
        content = fh.read().splitlines()
    recorded = [ln for ln in content if ln and not ln.startswith("#")]
    assert recorded == lines, "test set changed since the manifest was frozen"
    digest = hashlib.sha256("\n".join(lines).encode()).hexdigest()
    assert any(digest in ln for ln in content if ln.startswith("# digest"))


def test_labels_recompute_from_traces():
    from bench.relabel import relabel

    assert relabel(DATA, check=True) == 0
