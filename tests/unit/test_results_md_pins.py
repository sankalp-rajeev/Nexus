"""RESULTS.md must build byte-identically with or without git history, tags, CRLF checkouts or a UTC clock.

The builder reads no git state. Its two git facts are pinned in committed files; these tests compare the
pins with git whenever git can answer, and skip with the reason when it cannot (a shallow CI clone).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import build_results_md as builder  # noqa: E402


def _git_ok(*args: str) -> bool:
    proc = subprocess.run(["git", "-c", f"safe.directory={REPO.replace(os.sep, '/')}", *args],
                          cwd=REPO, capture_output=True, text=True)
    return proc.returncode == 0


def _shallow() -> bool:
    proc = subprocess.run(["git", "rev-parse", "--is-shallow-repository"], cwd=REPO, capture_output=True, text=True)
    return proc.returncode != 0 or proc.stdout.strip() == "true"


def test_sealed_rows_file_records_its_provenance():
    doc = json.load(open(builder.SEALED_ROWS, encoding="utf-8"))
    prov = doc["provenance"]
    assert prov["tag"] == builder.TAG and prov["tag_commit"] == builder.TAG_COMMIT
    assert prov["source_file"] == "RESULTS.md"
    assert "TEST data not opened" in prov["statement"]
    assert doc["rows"] and all(len(row) == 7 for row in doc["rows"])


def test_sealed_rows_match_the_tag_exactly():
    if not _git_ok("rev-parse", "--verify", "--quiet", f"{builder.TAG}^{{commit}}"):
        pytest.skip(f"tag {builder.TAG} is not in this checkout (e.g. a --no-tags or shallow clone)")
    tag_commit = subprocess.check_output(["git", "rev-parse", f"{builder.TAG}^{{commit}}"], cwd=REPO,
                                         text=True).strip()
    assert tag_commit == builder.TAG_COMMIT
    committed = json.load(open(builder.SEALED_ROWS, encoding="utf-8"))["rows"]
    assert committed == builder.git_published_rows(), \
        "sealed_rows_from_tag.json differs from the tag; run: python scripts/build_results_md.py --refresh-pins"


def test_pinned_file_commits_match_git_history():
    if _shallow():
        pytest.skip("shallow clone or no git: per-file last commits are not knowable here")
    pinned = json.load(open(builder.FILE_COMMITS, encoding="utf-8"))["files"]
    assert pinned
    for rel, pin in pinned.items():
        assert builder.git_last_commit(rel) == pin, \
            f"{rel} changed since it was pinned; run: python scripts/build_results_md.py --refresh-pins"


def test_render_reads_no_git_and_writes_lf_only(monkeypatch):
    def no_git(*args):
        raise AssertionError(f"render() must not call git: {args}")

    monkeypatch.setattr(builder, "_git", no_git)
    text = builder.render()
    assert "\r" not in text
    committed = open(builder.OUT, encoding="utf-8", newline="").read()
    assert builder.normalise(committed) == text
