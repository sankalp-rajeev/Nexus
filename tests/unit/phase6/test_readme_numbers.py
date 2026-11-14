"""Every number in the README's results section links to its source, and matches it.

The section is the part of README.md between `<!-- readme-numbers:start -->` and
`<!-- readme-numbers:end -->`. Each table row or bullet that holds a number must carry at least one
source link, and every number in it must be found in what those links point at:

* `RESULTS.md?plain=1#L<n>`: the numbers printed on that line of RESULTS.md;
* `reports/phase4/test_scoring.md?plain=1#L<n>`: the counts and Wilson intervals that
  results/phase4/headline_transcribed.json records for that report line (the report itself is not
  opened here);
* `results/...json#L<n>`: any numeric value in that JSON file, plus a few quantities derived from it
  (seconds as minutes, cost per promoted heal);
* any other text file: the numbers printed on the linked line.

A number matches a source value when they agree at the precision the README prints. Sums of two linked
counts (and their computed Wilson interval) are allowed, for rows that combine two classes. Nothing here
is a hard-coded expected value.
"""

from __future__ import annotations

import json
import re
import sys
from itertools import combinations
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
README = ROOT / "README.md"
TRANSCRIBED = ROOT / "results" / "phase4" / "headline_transcribed.json"
sys.path.insert(0, str(ROOT / "scripts"))
from transcribe_phase4_headline import wilson  # noqa: E402

LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")
FRACTION = re.compile(r"(?<![\d.])(\d+)/(\d+)(?![\d.])")
NUMBER = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(?![\w.]|/\d)")
# Words that contain digits but are labels, not results: the interval's confidence level, percentile
# names and the "per 1,000" unit.
NOT_RESULTS = re.compile(r"95% (?:interval|Wilson intervals?|CI)|\bp(?:50|90|95|99)\b|per 1,000")


def _section() -> str:
    text = README.read_text(encoding="utf-8")
    start, end = text.index("<!-- readme-numbers:start -->"), text.index("<!-- readme-numbers:end -->")
    return text[start:end]


def _units() -> list[str]:
    """Table rows and bullets; a bullet's wrapped lines are joined to it."""
    units: list[str] = []
    for line in _section().splitlines():
        if line.startswith("|") and not re.fullmatch(r"\|[-| ]+\|", line):
            units.append(line)
        elif line.startswith("- "):
            units.append(line)
        elif line.startswith("  ") and units and units[-1].startswith("- "):
            units[-1] += " " + line.strip()
        elif re.search(r"\d", NOT_RESULTS.sub("", LINK.sub("", line))):
            units.append(line)  # a prose line with a number must be sourced too
    return units


def _numbers(unit: str) -> tuple[list[tuple[int, int]], list[str]]:
    text = NOT_RESULTS.sub("", LINK.sub("", unit))
    fractions = [(int(k), int(n)) for k, n in FRACTION.findall(text)]
    return fractions, NUMBER.findall(FRACTION.sub(" ", text))


def _flatten(value, path=""):
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        yield path, float(value)
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _flatten(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _flatten(item, f"{path}[{index}]")


class Source:
    """What one link points at: counts with intervals, and plain numbers."""

    def __init__(self, target: str):
        path, _, anchor = target.partition("#")
        self.path = path.split("?")[0]
        self.line = int(anchor[1:]) if anchor.startswith("L") else None
        self.counts: list[dict] = []   # {"k", "n", "wilson95"}
        self.values: list[float] = []
        file = ROOT / self.path
        assert file.is_file(), f"README links to a missing file: {self.path}"
        if self.path == "reports/phase4/test_scoring.md":
            self._transcribed()
        elif self.path.endswith(".json"):
            self._json(json.loads(file.read_text(encoding="utf-8")))
        else:
            if self.line is None:
                return  # Context/protocol link, not a numeric citation.
            lines = file.read_text(encoding="utf-8").splitlines()
            assert self.line and 1 <= self.line <= len(lines), f"{target}: no such line"
            text = lines[self.line - 1]
            self.counts = [{"k": int(k), "n": int(n), "wilson95": None} for k, n in FRACTION.findall(text)]
            self.values = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", text)]

    def _transcribed(self) -> None:
        doc = json.loads(TRANSCRIBED.read_text(encoding="utf-8"))
        for number in doc["numbers"]:
            if number["source"]["line"] == self.line:
                self.counts.append(number)
        for row in doc["per_class_critic_vs_generic"]["rows"]:
            if row["source"]["line"] == self.line:
                self.counts += list(row["promoted_per_eligible_failure"].values())
        assert self.counts, f"headline_transcribed.json records nothing for test_scoring.md line {self.line}"

    def _json(self, doc) -> None:
        def ratios(value):
            if isinstance(value, dict):
                if {"numerator", "denominator", "estimate", "wilson95"} <= value.keys():
                    self.counts.append({"k": value["numerator"], "n": value["denominator"], "wilson95": value["wilson95"]})
                    if value["estimate"] is not None:
                        self.values.append(100 * value["estimate"])
                for child in value.values():
                    ratios(child)
            elif isinstance(value, list):
                for child in value:
                    ratios(child)
        ratios(doc)
        for path, value in _flatten(doc):
            self.values.append(value)
            if path.endswith(("_s.p50", "_s.p90", "_s.p95")):
                self.values.append(value / 60)  # seconds printed as minutes
        decisions = doc.get("gate_decisions", {}).get("by_detector_failure_class")
        provider = doc.get("L2", {}).get("provider_usd")
        if decisions and provider:
            promoted = sum(v.get("promoted", 0) for v in decisions.values())
            self.values += [promoted, provider["total"] / promoted]


def _printed_places(token: str) -> int:
    return len(token.split(".")[1]) if "." in token else 0


def _matches(token: str, candidates: list[float]) -> bool:
    places, wanted = _printed_places(token), float(token)
    return any(abs(round(c, places) - wanted) < 1e-9 for c in candidates)


def _allowed(sources: list[Source]) -> tuple[set[tuple[int, int]], list[float]]:
    counts = [c for s in sources for c in s.counts]
    fractions = {(c["k"], c["n"]) for c in counts}
    values = [v for s in sources for v in s.values]
    for c in counts:
        values += [c["k"], c["n"]]
        if c.get("wilson95"):
            values += [100 * c["wilson95"][0], 100 * c["wilson95"][1]]
    for a, b in combinations(counts, 2):  # two classes reported together
        k, n = a["k"] + b["k"], a["n"] + b["n"]
        fractions.add((k, n))
        values += [k, n]
        if n:
            low, high = wilson(k, n)
            values += [100 * low, 100 * high]
    return fractions, values


UNITS = [u for u in _units() if any(_numbers(u))]


def test_the_results_section_has_numbers():
    assert len(UNITS) >= 20


@pytest.mark.parametrize("unit", UNITS, ids=lambda u: LINK.sub(r"\1", u)[:60])
def test_every_number_is_sourced_and_matches(unit):
    targets = [t for _, t in LINK.findall(unit) if not t.startswith("http")]
    sources = [Source(t) for t in targets]
    assert any(s.counts or s.values for s in sources), f"no source link with numbers: {unit}"
    fractions, numbers = _numbers(unit)
    allowed_fractions, allowed_values = _allowed(sources)
    for fraction in fractions:
        assert fraction in allowed_fractions, f"{fraction[0]}/{fraction[1]} not found in {targets}"
    for token in numbers:
        assert _matches(token, allowed_values), f"{token} not found in {targets}"


def test_a_changed_number_is_caught():
    """The check is not vacuous: a wrong count or a wrong interval fails."""
    row = next(u for u in UNITS if u.startswith("| 12/48"))
    sources = [Source(t) for _, t in LINK.findall(row)]
    fractions, values = _allowed(sources)
    assert (13, 48) not in fractions
    assert not _matches("16", values) and _matches("15", values)


def test_external_trail_numbers_are_inside_the_checked_section():
    section = _section()
    assert "### External check (TRAIL)" in section
    rows = [u for u in UNITS if "results/external/trail_b_test.json" in u]
    assert len(rows) >= 3
    source = Source("results/external/trail_b_test.json")
    fractions, values = _allowed([source])
    assert (6, 14) in fractions and (6, 9) in fractions
    assert (6, 100003) not in fractions and not _matches("12345.67", values)


def test_external_trail_hierarchy_and_default_are_explicit():
    section = _section()
    assert "descriptive only" in section and "no improvement claim" in section
    assert "v1 stays live" in section and "guardrail" in section
