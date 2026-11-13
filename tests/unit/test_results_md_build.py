"""RESULTS.md generation is sealed-TEST safe, complete and honest about misses."""

from __future__ import annotations

import builtins
import importlib.util
import os
import re

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "build_results_md", os.path.join(REPO, "scripts", "build_results_md.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod():
    return _load_module()


@pytest.fixture(scope="module")
def text():
    with open(os.path.join(REPO, "RESULTS.md"), encoding="utf-8") as fh:
        return fh.read().replace("\r\n", "\n")


def _rows(text: str) -> dict[str, list[str]]:
    out = {}
    for ln in text.splitlines():
        if ln.startswith("| ") and not ln.startswith("| ID "):
            cells = [c.strip() for c in ln.strip().strip("|").split(" | ")]
            out[cells[0]] = cells
    return out


def test_generator_never_opens_a_sealed_file(mod):
    opened: list[str] = []
    real_open = builtins.open

    def spy(file, *a, **k):
        opened.append(str(file).replace("\\", "/"))
        return real_open(file, *a, **k)

    builtins.open = spy
    try:
        mod.render()
    finally:
        builtins.open = real_open
    bad = [p for p in opened
           if "_test" in os.path.basename(p).lower() or "/reports/phase4/test/" in p
           or any(p.endswith(s) for s in mod.SEALED_FILES)]
    assert not bad, bad
    assert any(p.endswith("results/phase4/headline_transcribed.json") for p in opened)


def test_load_refuses_sealed_paths(mod):
    for rel in ("results/detect_test.json", "results/heal_critic_v1_structured_test.json",
                "reports/phase4/test/x.json", "results/detect_false_alerts.json"):
        with pytest.raises(RuntimeError):
            mod.load(rel)


def test_results_md_has_ci_columns_and_every_row_has_nine_cells(text):
    rows = _rows(text)
    assert len(rows) >= 40
    for rid, cells in rows.items():
        assert len(cells) == 9, (rid, len(cells))


def test_ci_present_where_a_source_has_one(text):
    rows = _rows(text)
    for rid in ("B1", "D-dev", "D3", "D1", "D5", "A2 critic new", "A2 critic v1_structured",
                "A2 generic", "H5", "H6", "A2 seed noise", "C1", "C2", "C3", "C4", "C5",
                "P4-gate", "P4-other_fix", "P4-old-rule", "P4-regression", "P4-per-class",
                "P6-equivalence", "P6-false-alerts", "P6-otel"):
        assert re.search(r"\d\.\d\d-\d\.\d\d", rows[rid][7]), (rid, rows[rid][7])


def test_phase3_and_phase6_rows_exist(text):
    rows = _rows(text)
    for rid in ("C1", "C2", "C3", "C4", "C5", "P6-L4", "P6-stack", "P6-equivalence",
                "P6-false-alerts", "P6-otel", "P6-time-to-alert", "P6-lite-limits"):
        assert rid in rows, rid
    assert "359/359" in rows["P6-equivalence"][1]
    assert "118/118 -> 1/118" in rows["P6-false-alerts"][1]
    assert "round3.md" in rows["C3"][6] and "no results/*.json row" in rows["C3"][8]


def test_d1_d5_are_marked_missed_and_sensitivity_is_adjacent(text):
    rows = _rows(text)
    assert "TARGET MISSED" in rows["D1"][8]
    assert "TARGET MISSED" in rows["D5"][8]
    order = [ln.split(" | ")[0] for ln in text.splitlines() if ln.startswith("| ")]
    assert order.index("| S-v1.1-test") == order.index("| D5") + 1
    note = rows["S-v1.1-test"][8]
    for needle in ("D39", "20:34:39", "bd6a318", "20:43:30", "f6dc644", "SENSITIVITY"):
        assert needle in note
    # primary first, sensitivity after
    assert order.index("| D1") < order.index("| D5") < order.index("| S-v1.1-test")


def test_b1_is_unchanged_from_the_published_row(mod):
    pub = {c[0]: c for c in mod.published_rows()}
    row = mod.existing_row(pub["B1"], {})
    assert row["result"] == pub["B1"][1] and row["commit"] == pub["B1"][5]


def test_dirty_limitations_lists_every_dirty_row(text):
    rows = _rows(text)
    dirty = {rid for rid, c in rows.items() if "+dirty" in c[5]}
    section = text.split("## Limitations: results with a `+dirty`")[1]
    assert dirty
    for rid in dirty:
        assert rid in section, rid


def test_denominator_reconciliation_is_in_results_md(text):
    assert "Phase 4 denominators" in text
    for needle in ("**51**", "**48**", "**36**", "Unreconciled numbers: none."):
        assert needle in text
