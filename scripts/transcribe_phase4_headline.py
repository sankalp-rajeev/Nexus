"""Transcribe the Phase 4 headline numbers into results/phase4/headline_transcribed.json.

Reads ONLY the committed report reports/phase4/test_scoring.md (generated at the one-time TEST scoring).
No TEST data, no *_test* result file and no reports/phase4/test/ file is opened. Numbers are copied from
report table cells, never recomputed; the only computed values are the Wilson 95% intervals from k/n.

    python scripts/transcribe_phase4_headline.py          # write
    python scripts/transcribe_phase4_headline.py --check  # exit 1 if the JSON is stale
"""
from __future__ import annotations

import json
import math
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = "reports/phase4/test_scoring.md"
OUT = ROOT / "results/phase4/headline_transcribed.json"
STATEMENT = ("transcribed from committed Phase 4 reports at commit {commit}; not recomputed; "
             "TEST data not opened")
CB_NOTE = "CONTEXT_BLEED has n = 3 (2 scored patches): the report gives counts only, so no interval is shown"


def git(*args: str) -> str:
    return subprocess.check_output(["git", "-c", f"safe.directory={ROOT.as_posix()}", *args],
                                   cwd=ROOT, text=True).strip()


def wilson(k: int, n: int, z: float = 1.959964) -> list[float] | None:
    if n <= 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


class Report:
    def __init__(self) -> None:
        self.text = (ROOT / REPORT).read_text(encoding="utf-8").replace("\r\n", "\n")
        self.lines = self.text.split("\n")

    def section(self, heading: str) -> tuple[int, int]:
        starts = [i for i, line in enumerate(self.lines) if line.startswith(heading)]
        if len(starts) != 1:
            raise ValueError(f"heading not found exactly once: {heading!r}")
        end = next((i for i in range(starts[0] + 1, len(self.lines)) if self.lines[i].startswith("## ")),
                   len(self.lines))
        return starts[0], end

    def row(self, heading: str, prefix: str, nth: int = 0) -> tuple[int, list[str], str]:
        """(1-based line number, cells, line text) of the nth table row in the section starting with prefix."""
        start, end = self.section(heading)
        hits = [i for i in range(start, end) if self.lines[i].startswith(prefix)]
        if len(hits) <= nth:
            raise ValueError(f"row {prefix!r} (#{nth}) not found in section {heading!r}")
        line = self.lines[hits[nth]]
        cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
        return hits[nth] + 1, cells, line


def fraction(text: str) -> tuple[int, int]:
    match = re.match(r"(\d+)/(\d+)", text.strip())
    if not match:
        raise ValueError(f"not a k/n cell: {text!r}")
    return int(match.group(1)), int(match.group(2))


def number(
    rep: Report, nid: str, label: str, heading: str, prefix: str, column: int, *,
    split: str, k: int | None = None, n: int | None = None, cell_kind: str = "fraction",
    nth: int = 0, n_column: int | None = None, interval: bool = True, note: str | None = None,
    column_name: str = "",
) -> dict:
    line_no, cells, line = rep.row(heading, prefix, nth)
    cell = cells[column]
    if cell_kind == "fraction":
        k, n = fraction(cell)
    elif cell_kind == "count":  # a bare count; the denominator comes from another cell of the same row
        k = int(cell)
        n = int(cells[n_column])
    entry = {
        "id": nid, "label": label, "split": split, "k": k, "n": n,
        "wilson95": wilson(k, n) if interval else None,
        "source": {"path": REPORT, "line": line_no, "section": heading.lstrip("# ").strip(),
                   "row": prefix.strip("| ").replace(" | ", " / "), "column": column_name,
                   "cell": cell, "n_cell": cells[n_column] if n_column is not None else cell},
        "cited_text": line.strip(),
    }
    if note:
        entry["note"] = note
    return entry


H1 = "## 1. H1"
H2 = "## 2. Gate vs the old rule"
H3 = "## 3. Critic vs generic"
H5 = "## 5. Usable patches"
H6 = "## 6. CONTEXT_BLEED"
H7 = "## 7. Dev vs test"


def build() -> dict:
    rep = Report()
    commit = git("log", "-1", "--format=%H", "--", REPORT)
    blob = git("hash-object", "--", REPORT)
    out: dict = {
        "experiment_id": "P4-headline-transcribed",
        "summary": ("Phase 4 headline numbers transcribed from reports/phase4/test_scoring.md (critic v1_structured vs "
                    "generic vs no patch on the sealed TEST split, scored once): gate promoted 25/51 vs 12/51 vs 0/51; "
                    "old 'rerun improved' rule would promote 32/48, 6 falsely; 0 gate promotions failed fresh seeds."),
        "provenance": {
            "provider": "none (transcription)", "model": "none", "mock": False, "seed": None,
            "git_commit": commit, "date_utc": git("log", "-1", "--format=%cI", commit),
            "statement": STATEMENT.format(commit=commit),
            "source_report": {"path": REPORT, "last_commit": commit, "blob": blob,
                              "report_generated_at": "commit f2a4939 by python -m bench.heal.report_test (report header, line 6)"},
            "split_of_numbers": "TEST unless a record says dev (the report's section 7 repeats the dev result for comparison)",
            "interval_method": ("Wilson 95% computed here from k/n. The report itself prints Clopper-Pearson "
                                "intervals; they are quoted verbatim in each cited_text and differ slightly."),
        },
    }

    # Section 3's last cell holds "12/51 (...) vs 25/51 (...)": take both fractions from it explicitly.
    line_no, cells, line = rep.row(H3, "| **all** |")
    both = re.findall(r"(\d+)/(\d+) \(", cells[6])
    assert len(both) == 2, cells[6]
    generic_k, generic_n = map(int, both[0])
    v1_k, v1_n = map(int, both[1])
    lead = [
        {"id": "gate_promoted_v1_structured", "label": "Gate promoted, critic v1_structured, per eligible failure",
         "split": "test", "k": v1_k, "n": v1_n, "wilson95": wilson(v1_k, v1_n),
         "source": {"path": REPORT, "line": line_no, "section": H3.lstrip("# "), "row": "all",
                    "column": "Promoted per eligible failure: generic vs v1_structured (second fraction)",
                    "cell": cells[6], "n_cell": cells[6]}, "cited_text": line.strip()},
        {"id": "gate_promoted_generic", "label": "Gate promoted, generic templates, per eligible failure",
         "split": "test", "k": generic_k, "n": generic_n, "wilson95": wilson(generic_k, generic_n),
         "source": {"path": REPORT, "line": line_no, "section": H3.lstrip("# "), "row": "all",
                    "column": "Promoted per eligible failure: generic vs v1_structured (first fraction)",
                    "cell": cells[6], "n_cell": cells[6]}, "cited_text": line.strip()},
        number(rep, "gate_promoted_no_patch", "Gate promoted, no patch (51 patches = the 51 eligible failures)",
               H2, "| no patch | all |", 5, split="test", cell_kind="count", n_column=2,
               column_name="Gate promoted (patches in column 'Patches')"),
        number(rep, "no_patch_own_task_safe", "No patch: own task already safe at >= 2 of 3 seeds",
               H3, "| **all** |", 2, split="test", column_name="No patch: own task safe"),
        number(rep, "other_fix_v1_repaired", "v1_structured, other_fix patches: own task repaired (H1)",
               H1, "| v1_structured | **all** | other_fix |", 4, split="test", column_name="H1 repair (s0-2)"),
        number(rep, "other_fix_no_patch_same_failures", "No patch on the same 36 failures: own task already safe",
               H1, "| v1_structured | **all** | other_fix |", 5, split="test", column_name="No patch, same failures"),
        number(rep, "other_fix_h3_breaks", "v1_structured, other_fix patches: broke at least 1 passing task (H3)",
               H1, "| v1_structured | **all** | other_fix |", 9, split="test", column_name="H3 regress (>=1 break)"),
        number(rep, "other_fix_gate_promoted", "v1_structured, other_fix patches: gate promoted",
               H2, "| v1_structured | other_fix |", 5, split="test", cell_kind="count", n_column=2,
               column_name="Gate promoted (patches in column 'Patches')"),
        number(rep, "old_rule_promoted", "Old 'same input improved' rule: promoted (v1_structured, 48 scored patches)",
               H2, "| v1_structured | all |", 3, split="test", cell_kind="count", n_column=2,
               column_name="Old rule promoted (patches in column 'Patches')"),
        number(rep, "old_rule_false_promotions", "Old rule promoted but the gate rejected, out of the 32 the old rule promoted",
               H2, "| v1_structured | all |", 4, split="test", cell_kind="count", n_column=3,
               column_name="Old-rule false promotions (denominator: column 'Old rule promoted')",
               note=("The report calls these 'false promotions' (promoted by the old rule, rejected by the gate). "
                     "It does not use the word 'harmful'; the 6 are all other_fix patches (section 2, other_fix row).")),
        number(rep, "gate_false_promotions_fresh_seeds", "Gate-promoted patches that failed on fresh seeds 3-5 (out of 25)",
               H2, "| v1_structured | all |", 6, split="test", cell_kind="count", n_column=5,
               column_name="Gate false promotions (s3-5) (denominator: column 'Gate promoted')"),
        number(rep, "regression_breaks_test", "v1_structured regression breaks (>=1 passing task broken), TEST, per scored patch",
               H7, "| v1_structured | **test** (A2 set) |", 7, split="test", column_name="H3 regress"),
        number(rep, "regression_breaks_dev", "v1_structured regression breaks (>=1 passing task broken), DEV, per scored patch",
               H7, "| v1_structured | dev (A2 regression set) |", 7, split="dev", column_name="H3 regress"),
    ]

    # Derived, flagged: not a table cell. "Gate blocked 12/12" follows from the gate's definition.
    breakers = next(x for x in lead if x["id"] == "other_fix_h3_breaks")
    gate_def_line = next(i + 1 for i, text in enumerate(rep.lines) if text.startswith("Counts with 95% Clopper-Pearson"))
    gate_def_text = rep.lines[gate_def_line - 1]
    blocked_text = "Gate = own task repaired \u2227 held-out rate strictly above no patch \u2227 no break on the regression set."
    assert blocked_text in gate_def_text
    lead.append({
        "id": "other_fix_breakers_blocked_by_gate", "label": "Of the other_fix patches that broke a passing task, blocked by the gate",
        "split": "test", "k": breakers["k"], "n": breakers["k"], "wilson95": wilson(breakers["k"], breakers["k"]),
        "derived_from_definition": True,
        "source": {"path": REPORT, "line": gate_def_line, "section": "preamble (gate definition)",
                   "row": "definition", "column": "", "cell": blocked_text, "n_cell": breakers["source"]["cell"]},
        "cited_text": blocked_text,
        "note": ("NOT a number printed in the report. It follows from the gate definition quoted here (a patch that breaks "
                 "a regression-set task fails check 3) and from the 12/36 breaks cited in other_fix_h3_breaks (line "
                 f"{breakers['source']['line']}). The per-patch gate decisions are in the sealed TEST result file, which was "
                 "not opened, so this could not be confirmed against them."),
    })
    out["numbers"] = lead

    # Per-class table (section 3): counts transcribed from the row, intervals computed per k/n.
    classes = []
    for name in ("HALLUCINATION", "TOOL_MISFIRE", "CONTEXT_BLEED", "PLAN_DRIFT", "LOOP_DETECTED", "**all**"):
        line_no, cells, line = rep.row(H3, f"| {name} |")
        gen = [int(x) for x in re.findall(r"\d+", cells[3])]
        v1 = [int(x) for x in re.findall(r"\d+", cells[4])]
        eligible = int(cells[1])
        npk, npn = fraction(cells[2])
        promoted_pair = re.findall(r"(\d+)/(\d+)", cells[6])
        is_cb = name == "CONTEXT_BLEED"
        classes.append({
            "class": name.strip("*"), "split": "test",
            "eligible_failures": eligible,
            "no_patch_own_task_safe": {"k": npk, "n": npn, "wilson95": None if is_cb else wilson(npk, npn)},
            "generic": {"patches": gen[0], "repaired": gen[1], "promoted": gen[2], "h3_breaks": gen[3]},
            "v1_structured": {"patches": v1[0], "repaired": v1[1], "promoted": v1[2], "h3_breaks": v1[3]},
            "v1_structured_promoted_other_fix_only": int(cells[5]),
            "promoted_per_eligible_failure": {
                "generic": {"k": int(promoted_pair[0][0]), "n": int(promoted_pair[0][1]),
                            "wilson95": None if is_cb else wilson(int(promoted_pair[0][0]), int(promoted_pair[0][1]))},
                "v1_structured": {"k": int(promoted_pair[1][0]), "n": int(promoted_pair[1][1]),
                                  "wilson95": None if is_cb else wilson(int(promoted_pair[1][0]), int(promoted_pair[1][1]))},
            },
            "interval_note": CB_NOTE if is_cb else None,
            "source": {"path": REPORT, "line": line_no, "section": H3.lstrip("# "), "row": name.strip("*")},
            "cited_text": line.strip(),
        })
    out["per_class_critic_vs_generic"] = {
        "columns": ["Class", "Eligible failures", "No patch: own task safe",
                    "Generic: patches / repaired / promoted / H3 breaks",
                    "v1_structured: patches / repaired / promoted / H3 breaks",
                    "v1_structured promoted, other_fix only",
                    "Promoted per eligible failure: generic vs v1_structured"],
        "rows": classes,
    }

    # Denominators and reconciliation with the RESULTS.md row "A3 test v1_structured".
    a3 = {
        "H1": number(rep, "a3_h1", "v1_structured TEST H1 repair, per scored patch", H7,
                     "| v1_structured | **test** (A2 set) |", 4, split="test", column_name="H1 repair"),
        "H2": number(rep, "a3_h2", "v1_structured TEST H2 generalize, per scored patch", H7,
                     "| v1_structured | **test** (A2 set) |", 6, split="test", column_name="H2 generalize"),
        "H3": number(rep, "a3_h3", "v1_structured TEST H3 regress, per scored patch", H7,
                     "| v1_structured | **test** (A2 set) |", 7, split="test", column_name="H3 regress"),
        "gate": number(rep, "a3_gate", "v1_structured TEST gate promoted, per scored patch", H7,
                       "| v1_structured | **test** (A2 set) |", 8, split="test", column_name="Gate promoted"),
        "gate_false_promotions": number(rep, "a3_gate_false", "gate false promotions", H2, "| v1_structured | all |", 6,
                                        split="test", cell_kind="count", n_column=5, column_name="Gate false promotions (s3-5)"),
    }
    usable = next(i + 1 for i, text in enumerate(rep.lines) if text.startswith("**50/60 test failures got a usable"))
    left_out = next(i + 1 for i, text in enumerate(rep.lines) if text.startswith('"No proposal generated" is the failure'))
    eligible_line = next(i + 1 for i, text in enumerate(rep.lines) if text.startswith("Per eligible failure (the 9 no-observable-harm"))
    out["reconciliation_with_results_md_row_A3_test_v1_structured"] = {
        "row_in_results_md": ("per failure H1 32/48, H2 34, H3 12, gate 25, gate false promotions 0; "
                              "distinct patches 48 (H1 32, H3 12)"),
        "matches_report": {key: {"k": value["k"], "n": value["n"], "line": value["source"]["line"]} for key, value in a3.items()},
        "denominators": [
            {"n": 60, "what": "TEST failures the critic was run on", "line": usable,
             "cited_text": "**50/60 test failures got a usable `v1_structured` patch.**"},
            {"n": 51, "what": ("eligible failures: the 60 minus the 9 CONTEXT_BLEED failures with no observable harm. Denominator of "
                               "'gate promoted 25/51', 'generic 12/51', 'no patch 0/51' (a failure with no patch counts as not "
                               "repaired and not promoted)"), "line": eligible_line,
             "cited_text": "Per eligible failure (the 9 no-observable-harm CONTEXT_BLEED failures are left out)"},
            {"n": 50, "what": "usable v1_structured patches (10 failures got none: 7+1 CONTEXT_BLEED, 2 TOOL_MISFIRE)", "line": usable,
             "cited_text": "**50/60 test failures got a usable `v1_structured` patch.**"},
            {"n": 48, "what": ("scored patches = 50 minus 2 patches on no-observable-harm CONTEXT_BLEED failures. Denominator of the "
                               "RESULTS.md row (H1 32/48, gate 25) and of the 'distinct patches 48' (every v1 patch is distinct)"),
             "line": left_out, "cited_text": "That leaves 48 scored patches on 51 eligible failures."},
            {"n": 36, "what": "other_fix scored patches (TOOL_MISFIRE 10, CONTEXT_BLEED 2, PLAN_DRIFT 12, LOOP_DETECTED 12)",
             "line": breakers["source"]["line"], "cited_text": breakers["cited_text"]},
            {"n": 12, "what": "reverts_injection scored patches (HALLUCINATION: the patch removes the injected prompt)",
             "line": rep.row(H1, "| v1_structured | **all** | reverts_injection |")[0],
             "cited_text": rep.row(H1, "| v1_structured | **all** | reverts_injection |")[2].strip()},
        ],
        "arithmetic": ("36 other_fix + 12 reverts_injection = 48 scored patches; 51 eligible failures - 48 scored = 3 failures with "
                       "no scored patch (2 TOOL_MISFIRE failed the dry run, 1 CONTEXT_BLEED); 48 + 2 excluded CONTEXT_BLEED patches "
                       "= 50 usable. Gate 25 = 14 other_fix + 11 reverts_injection (section 2). 25/51 = 0.49 and 25/48 = 0.52 are "
                       "the same 25 promotions over the two denominators."),
        "flags": [
            ("'Gate blocked 12/12' (the 12 other_fix patches that broke a passing task) is not printed in the report; it is "
             "derived from the gate definition. See other_fix_breakers_blocked_by_gate."),
            ("'6 harmful': the report counts 6 old-rule FALSE PROMOTIONS (promoted by the old rule, rejected by the gate), not "
             "'harmful' patches. Whether each of the 6 broke a passing task is not stated in the report."),
            ("All 12 regression breaks are other_fix patches (12/36 in section 1; reverts_injection 0/12), so 12/36 (other_fix) "
             "and 12/48 (all scored patches) count the same 12 patches over two denominators."),
            ("The DEV 3/44 and the TEST 12/48 are both measured on the A2 regression set (report section 7), so they are "
             "comparable; the generic arm's 3-class dev result is not (section 7 preamble)."),
        ],
        "unreconciled": [],
    }
    return out


def render(doc: dict) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    text = render(build())
    if "--check" in sys.argv:
        current = OUT.read_text(encoding="utf-8").replace("\r\n", "\n") if OUT.exists() else ""
        if current != text:
            print("results/phase4/headline_transcribed.json is stale; run: python scripts/transcribe_phase4_headline.py")
            return 1
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
