"""Combine the Phase 2 detectors into one label per trace.

Thresholds come from services/detectors/thresholds.json, chosen on dev by the
pre-registered rule (max dev recall subject to dev precision >= 0.90) and
frozen at tag phase2-detectors-frozen.

Precedence when several fire: LOOP_DETECTED, TOOL_MISFIRE, CONTEXT_BLEED,
PLAN_DRIFT, HALLUCINATION (the labeler's natural order).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

from nexus_agent.models import CompleteTrace

from services.detectors import bleed, drift, hallucination, rules

THRESHOLDS_PATH = os.path.join(os.path.dirname(__file__), "thresholds.json")
ORDER = ["LOOP_DETECTED", "TOOL_MISFIRE", "CONTEXT_BLEED", "PLAN_DRIFT", "HALLUCINATION"]


@dataclass
class Scores:
    loop: bool
    misfire: bool
    bleed: float | None
    drift: dict[str, bool]
    halluc: float | None
    seconds: float = 0.0
    extra: dict = field(default_factory=dict)


def compute_scores(trace: CompleteTrace) -> Scores:
    t0 = time.perf_counter()
    s = Scores(rules.loop(trace), rules.misfire(trace), bleed.score(trace), drift.flags(trace),
               hallucination.score(trace))
    s.seconds = time.perf_counter() - t0
    return s


def load_thresholds(path: str = THRESHOLDS_PATH) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def fired(s: Scores, th: dict) -> dict[str, bool]:
    return {
        "LOOP_DETECTED": s.loop,
        "TOOL_MISFIRE": s.misfire,
        "CONTEXT_BLEED": s.bleed is not None and s.bleed >= th["CONTEXT_BLEED"]["threshold"],
        "PLAN_DRIFT": s.drift.get(th["PLAN_DRIFT"]["variant"], False),
        "HALLUCINATION": s.halluc is not None and s.halluc >= th["HALLUCINATION"]["threshold"],
    }


def label(s: Scores, th: dict) -> str:
    f = fired(s, th)
    return next((c for c in ORDER if f[c]), "NORMAL")
