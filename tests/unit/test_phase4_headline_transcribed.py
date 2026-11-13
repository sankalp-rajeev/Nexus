"""results/phase4/headline_transcribed.json must be a faithful transcription of reports/phase4/test_scoring.md.

Opens only the committed report, RESULTS.md and the JSON: no TEST data and no *_test* result file.
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JSON_PATH = ROOT / "results/phase4/headline_transcribed.json"
REPORT = ROOT / "reports/phase4/test_scoring.md"


def _script():
    spec = importlib.util.spec_from_file_location("transcribe_phase4_headline",
                                                  ROOT / "scripts/transcribe_phase4_headline.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def doc():
    return json.loads(JSON_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def report_lines():
    return REPORT.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")


def test_provenance_statement_and_report_identity(doc):
    commit = doc["provenance"]["source_report"]["last_commit"]
    assert doc["provenance"]["statement"] == (
        f"transcribed from committed Phase 4 reports at commit {commit}; not recomputed; TEST data not opened")
    blob = subprocess.check_output(["git", "hash-object", "--", "reports/phase4/test_scoring.md"], cwd=ROOT, text=True).strip()
    assert doc["provenance"]["source_report"]["blob"] == blob, "the report changed since it was transcribed"


def test_every_number_appears_verbatim_in_its_cited_report_line(doc, report_lines):
    derived = []
    for item in doc["numbers"]:
        source = item["source"]
        assert source["path"] == "reports/phase4/test_scoring.md"
        line = report_lines[source["line"] - 1].strip()
        assert source["cell"] in line, item["id"]
        assert source["n_cell"] in line or item.get("derived_from_definition"), item["id"]
        if item.get("derived_from_definition"):
            assert item["cited_text"] in line  # the gate definition, quoted from the preamble line
            derived.append(item["id"])
            assert item["note"].startswith("NOT a number printed in the report")
            continue
        assert item["cited_text"] == line, item["id"]
        if re.match(r"\d+/\d+", source["cell"]):  # a k/n cell: both numbers are in the cell text
            assert f"{item['k']}/{item['n']}" in source["cell"], item["id"]
        else:  # a bare count whose denominator is another cell of the same row
            assert source["cell"] == str(item["k"]) and source["n_cell"] == str(item["n"]), item["id"]
    assert derived == ["other_fix_breakers_blocked_by_gate"]


def test_wilson_intervals_are_recomputed_from_k_over_n(doc):
    wilson = _script().wilson
    for item in doc["numbers"]:
        assert item["wilson95"] == wilson(item["k"], item["n"]), item["id"]
    # spot-check the formula against a hand value: 25/51 -> 0.3586 .. 0.6232
    assert wilson(25, 51) == [0.3586, 0.6232]


def test_the_requested_lead_numbers(doc):
    got = {item["id"]: (item["k"], item["n"]) for item in doc["numbers"]}
    assert got["gate_promoted_v1_structured"] == (25, 51)
    assert got["gate_promoted_generic"] == (12, 51)
    assert got["gate_promoted_no_patch"] == (0, 51)
    assert got["other_fix_v1_repaired"] == (21, 36)
    assert got["other_fix_no_patch_same_failures"] == (4, 36)
    assert got["other_fix_h3_breaks"] == (12, 36)
    assert got["old_rule_promoted"] == (32, 48)
    assert got["old_rule_false_promotions"] == (6, 32)
    assert got["gate_false_promotions_fresh_seeds"] == (0, 25)
    assert got["regression_breaks_dev"] == (3, 44)
    assert got["regression_breaks_test"] == (12, 48)


def test_per_class_table_rows_match_the_report(doc, report_lines):
    for row in doc["per_class_critic_vs_generic"]["rows"]:
        line = report_lines[row["source"]["line"] - 1].strip()
        assert row["cited_text"] == line
        for arm in ("generic", "v1_structured"):
            values = row[arm]
            text = f"{values['patches']} / {values['repaired']} / {values['promoted']} / {values['h3_breaks']}"
            assert text in line, (row["class"], arm)
        assert f"{row['no_patch_own_task_safe']['k']}/{row['no_patch_own_task_safe']['n']}" in line
        promoted = row["promoted_per_eligible_failure"]
        for arm in ("generic", "v1_structured"):
            assert f"{promoted[arm]['k']}/{promoted[arm]['n']}" in line
    classes = {row["class"] for row in doc["per_class_critic_vs_generic"]["rows"]}
    assert classes == {"HALLUCINATION", "TOOL_MISFIRE", "CONTEXT_BLEED", "PLAN_DRIFT", "LOOP_DETECTED", "all"}
    cb = next(r for r in doc["per_class_critic_vs_generic"]["rows"] if r["class"] == "CONTEXT_BLEED")
    assert cb["promoted_per_eligible_failure"]["v1_structured"]["wilson95"] is None and cb["interval_note"]


def test_reconciles_with_the_results_md_row(doc):
    results = (ROOT / "RESULTS.md").read_text(encoding="utf-8")
    row = next(line for line in results.splitlines() if line.startswith("| A3 test v1_structured |"))
    match = re.search(r"H1 (\d+)/(\d+), H2 (\d+), H3 (\d+), gate (\d+), gate false promotions (\d+)", row)
    assert match, row
    h1k, h1n, h2, h3, gate, false = map(int, match.groups())
    rec = doc["reconciliation_with_results_md_row_A3_test_v1_structured"]["matches_report"]
    assert (rec["H1"]["k"], rec["H1"]["n"]) == (h1k, h1n) == (32, 48)
    assert rec["H2"]["k"] == h2 and rec["H3"]["k"] == h3 and rec["gate"]["k"] == gate
    assert rec["gate_false_promotions"]["k"] == false == 0
    assert 36 + 12 == 48 and 51 - 48 == 3
    denominators = {d["n"] for d in doc["reconciliation_with_results_md_row_A3_test_v1_structured"]["denominators"]}
    assert {60, 51, 50, 48, 36, 12} <= denominators
    assert doc["reconciliation_with_results_md_row_A3_test_v1_structured"]["flags"], "unreconciled items must be flagged"


def test_json_is_current_with_the_generator():
    script = _script()
    assert JSON_PATH.read_text(encoding="utf-8").replace("\r\n", "\n") == script.render(script.build())
