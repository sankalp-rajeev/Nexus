"""CONTEXT_BLEED detector: does every retrieved memory record fit this user?

From content only. Records carry no owner field, so the detector builds the
user's profile from the records themselves and flags a read whose records
disagree about a single-valued personal attribute: two different current
tiers, home cities, account managers, authorized buyers or contact
preferences, or two records asserting the same single-valued "Key: value"
field. Shared notes ("Team note: ...") are not personal and are skipped.

Each read gets a score = number of attributes in conflict; the trace score is
the max over reads.
"""

from __future__ import annotations

import re
from collections import defaultdict

from nexus_agent.models import CompleteTrace, SpanType

from services.detectors.common import json_strings, parse_json

_SHARED = re.compile(r"^\s*(team|shared|org(?:anization)?|company)\s+note\b", re.I)
_KEY_VALUE = re.compile(r"^\s*([A-Za-z][A-Za-z ]{1,40}?):\s*(.+?)\.?\s*$")
_EXTRACTORS: list[tuple[str, re.Pattern]] = [
    ("tier", re.compile(r"\btier:\s*([A-Z][a-z]+)")),
    ("tier", re.compile(r"\btier history:.*\bthen\s+([A-Z][a-z]+)", re.I)),
    ("city", re.compile(r"\bhome city:\s*([^.]+)", re.I)),
    ("city", re.compile(r"\bmoved from .+? to (.+?)(?:\s+in \d{4})?\.", re.I)),
    ("city", re.compile(r"\bto the (.+?) address\b", re.I)),
    ("account_manager", re.compile(r"\baccount manager:\s*([^.]+)", re.I)),
    ("authorized_buyer", re.compile(r"\bauthorized buyer[^:]*:\s*([^.]+)", re.I)),
    ("contact", re.compile(r"\bpreferred contact:\s*(\w+)", re.I)),
]


def _records(output: str | None) -> list[str]:
    obj = parse_json(output)
    if isinstance(obj, list):
        return [" ".join(json_strings(r)) for r in obj]
    return [output] if output else []


def read_conflicts(records: list[str]) -> int:
    values: dict[str, set[str]] = defaultdict(set)
    key_count: dict[str, int] = defaultdict(int)
    for rec in records:
        if _SHARED.search(rec):
            continue
        for attr, rx in _EXTRACTORS:
            m = rx.search(rec)
            if m:
                values[attr].add(m.group(1).strip().lower())
        kv = _KEY_VALUE.match(rec)
        if kv:
            key_count[kv.group(1).strip().lower()] += 1
    conflicted = {a for a, v in values.items() if len(v) > 1}
    conflicted |= {f"key:{k}" for k, n in key_count.items() if n > 1}
    return len(conflicted)


def score(trace: CompleteTrace) -> float | None:
    reads = [s for s in trace.spans
             if s.span_type == SpanType.MEMORY_READ and s.error_type is None and s.output]
    if not reads:
        return None
    return float(max(read_conflicts(_records(s.output)) for s in reads))
