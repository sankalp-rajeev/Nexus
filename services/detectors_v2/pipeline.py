"""Explicit opt-in detectors-v2. No live classifier imports or default changes."""
from dataclasses import dataclass
import json
from pathlib import Path

from services.detectors import bleed, drift, pipeline as v1, rules
from services.detectors_v2 import hallucination, repetition


@dataclass
class Scores:
    loop: bool
    misfire: bool
    bleed: float | None
    drift: dict
    halluc: float | None
    hallucination_reason: str | None


def load_config():
    return json.loads(Path(__file__).with_name("config.json").read_text())


def compute_scores(trace, *, scope=None, entailments=None):
    scope = scope or load_config()["c5_scope"]
    h = hallucination.score(trace, scope, entailments)
    return Scores(repetition.loop(trace), rules.misfire(trace), bleed.score(trace), drift.flags(trace), h.score, h.reason)


def fired(scores, thresholds=None):
    return v1.fired(scores, thresholds or v1.load_thresholds())


def label(scores, thresholds=None):
    flags = fired(scores, thresholds)
    return next((c for c in v1.ORDER if flags[c]), "NORMAL")
