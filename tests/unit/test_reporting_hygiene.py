"""Credibility guards (Improvement Plan, Phase 0).

* Every docs/*report*.md and docs/history/*report*.md states provider, model and whether it is a mock.
* Every results/*.json result carries full provenance.
* RESULTS.md is regenerated from results/, never hand-edited.
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import sys

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
REPORTS = sorted(glob.glob(os.path.join(REPO, "docs", "*report*.md"))
                 + glob.glob(os.path.join(REPO, "docs", "history", "*report*.md"))
                 + glob.glob(os.path.join(REPO, "reports", "**", "baseline*.md"), recursive=True))
RESULTS = sorted(glob.glob(os.path.join(REPO, "results", "*.json")))


def test_there_are_reports_to_check():
    assert REPORTS, "expected at least one docs/*report*.md"


@pytest.mark.parametrize("path", REPORTS, ids=os.path.basename)
def test_report_has_provenance_header(path):
    head = "\n".join(open(path, encoding="utf-8").read().splitlines()[:15])
    for field in ("**Provider:**", "**Model:**", "**Mock:**"):
        assert field in head, f"{os.path.basename(path)} is missing {field} in its header"


@pytest.mark.parametrize("path", RESULTS, ids=os.path.basename)
def test_result_file_has_provenance(path):
    doc = json.load(open(path, encoding="utf-8"))
    if "experiment_id" not in doc:
        pytest.skip("auxiliary file")
    prov = doc["provenance"]
    for key in ("provider", "model", "mock", "seed", "date_utc", "git_commit"):
        assert key in prov, f"{os.path.basename(path)} provenance missing {key}"
    assert doc.get("summary"), "result needs a one-line summary"


def test_results_md_is_up_to_date():
    proc = subprocess.run(
        [sys.executable, os.path.join(REPO, "scripts", "build_results_md.py"), "--check"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
