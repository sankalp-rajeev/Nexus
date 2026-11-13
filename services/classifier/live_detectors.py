"""Live classifier built on the scored Phase 2 detectors (6.3b).

The legacy pipeline in ``classifier.py`` (rules + MiniLM + PatchCore + NLI + SVM) is not what
produced the Phase 2 numbers. This adapter runs the *frozen* detectors the way Phase 4 did
(``scripts/phase5/pipeline.py``): ``bench.detector_view`` -> ``services.detectors.pipeline``
(``compute_scores`` / ``label``) -> ``services.critic.detector_adapter.from_detector`` for the
failure span. No detector logic is copied or changed here.

Detector configuration (the one the Phase 2 TEST scoring used, ``pipeline`` variant, no LLM judge):
git tag ``phase2-detectors-frozen``; thresholds from ``services/detectors/thresholds.json``;
HALLUCINATION NLI model ``cross-encoder/nli-deberta-v3-base`` at the revision pinned in
``.github/model-revisions.json``.

Live-only behaviour, all outside the frozen files:

* A live trace id is replaced by the opaque view id for the detectors and mapped back.
* Content-missing guard: OpenTelemetry content capture is opt-in, so a run of identical tool
  calls whose arguments were never captured proves nothing. If every span in every loop run
  carries ``nexus.content_missing`` the loop verdict is dropped (the frozen rule is not edited:
  the remaining detectors are re-ranked with ``loop=False``), the reason is
  ``insufficient_content`` and ``insufficient_content_suppressed`` counts it.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from pathlib import Path

from bench.detector_view import detector_view
from nexus_agent.models import Classification, CompleteTrace, FailureType

from services.classifier.embedder import NLIModelUnavailable
from services.critic.detector_adapter import from_detector
from services.detectors import hallucination, pipeline, rules
from services.detectors.common import tool_calls

logger = logging.getLogger("nexus.classifier.detectors")

ROOT = Path(__file__).resolve().parents[2]
FROZEN_TAG = "phase2-detectors-frozen"
INSUFFICIENT_CONTENT = "insufficient_content"
CONTENT_MISSING_KEY = "nexus.content_missing"

# triggered_rule reported per fired detector (the legacy names stay with the legacy classifier).
RULE_NAMES = {
    "LOOP_DETECTED": "detectors:loop",
    "TOOL_MISFIRE": "detectors:misfire",
    "CONTEXT_BLEED": "detectors:bleed",
    "PLAN_DRIFT": "detectors:plan_drift",
    "HALLUCINATION": "detectors:hallucination_nli",
}
NO_DETECTOR_FIRED = "detectors:none"
# The loop and misfire rules are exact, the rest are thresholded scores with no calibrated
# probability, so only the rule detectors report a confidence.
RULE_CONFIDENCE = {"LOOP_DETECTED": 1.0, "TOOL_MISFIRE": 1.0}


def _pinned_revision() -> str:
    pins = json.loads((ROOT / ".github" / "model-revisions.json").read_text(encoding="utf-8"))
    return pins[hallucination.NLI_MODEL]


def detector_config() -> dict:
    """What a deployment is running, for health output and reports."""
    th = pipeline.load_thresholds()
    return {
        "detectors": "services/detectors (frozen)",
        "frozen_tag": FROZEN_TAG,
        "variant": "pipeline (no LLM judge)",
        "thresholds_file": "services/detectors/thresholds.json",
        "thresholds": {"HALLUCINATION": th["HALLUCINATION"]["threshold"],
                       "CONTEXT_BLEED": th["CONTEXT_BLEED"]["threshold"],
                       "PLAN_DRIFT": th["PLAN_DRIFT"]["variant"]},
        "precedence": list(pipeline.ORDER),
        "nli_model": hallucination.NLI_MODEL,
        "nli_revision": _pinned_revision(),
    }


def staged_revision() -> str | None:
    """Revision file written by the image build; None when the model comes from the HF cache."""
    marker = Path(hallucination.NLI_MODEL) / ".nexus-model-revision"
    return marker.read_text(encoding="utf-8").strip() if marker.is_file() else None


def loop_runs(view: CompleteTrace) -> list[list[str]]:
    """Span ids of every maximal run the frozen loop rule would count (>= LOOP_MIN_REPEATS).

    Localisation only. Detection stays ``rules.loop``; this just says *which* spans made it fire.
    It uses the frozen ``tool_calls`` and ``LOOP_MIN_REPEATS`` and the same equality the rule uses.
    """
    calls = tool_calls(view)
    runs: list[list[str]] = []
    current = calls[:1]
    for prev, cur in zip(calls, calls[1:]):
        if cur.ok and prev.ok and (cur.tool, cur.args_text) == (prev.tool, prev.args_text):
            current.append(cur)
        else:
            if len(current) >= rules.LOOP_MIN_REPEATS:
                runs.append([c.span.span_id for c in current])
            current = [cur]
    if len(current) >= rules.LOOP_MIN_REPEATS:
        runs.append([c.span.span_id for c in current])
    return runs


def loop_lacks_content(trace: CompleteTrace, view: CompleteTrace) -> bool:
    """True when the loop verdict rests only on spans flagged ``nexus.content_missing``.

    Fails open: if the localisation finds no run (it should always agree with ``rules.loop``) the
    alert is kept.
    """
    runs = loop_runs(view)
    if not runs:
        return False
    missing = {s.span_id for s in trace.spans if s.metadata.get(CONTENT_MISSING_KEY) is True}
    return all(span_id in missing for run in runs for span_id in run)


class DetectorClassifier:
    """Same ``classify(trace) -> Classification`` interface as ``FailureClassifier``."""

    mode = "detectors"

    def __init__(self) -> None:
        self.thresholds = pipeline.load_thresholds()
        self.config = detector_config()
        self.insufficient_content_suppressed = 0
        self.last_scores: pipeline.Scores | None = None  # for equivalence checks and profiling

    def require_models(self) -> None:
        """Load the HALLUCINATION NLI model now; refuse (no substitute) if it is not exactly pinned."""
        pinned = _pinned_revision()
        staged = staged_revision()
        if staged is not None and staged != pinned:
            raise NLIModelUnavailable(
                f"{hallucination.NLI_MODEL} staged at {staged}, but {pinned} is pinned")
        try:
            hallucination._nli()
        except Exception as exc:
            logger.error("detectors: NLI model %s could not load (%s)", hallucination.NLI_MODEL, exc)
            raise NLIModelUnavailable(
                f"Required NLI model {hallucination.NLI_MODEL} could not load offline; "
                "rebuild the classifier image with its pinned models") from exc

    def status(self) -> dict:
        return {"classifier": self.mode, "detector_config": self.config,
                "nli_staged_revision": staged_revision(),
                "insufficient_content_suppressed": self.insufficient_content_suppressed}

    def classify(self, trace: CompleteTrace) -> Classification:
        view = detector_view(trace.model_dump(mode="json"))
        scores = self.last_scores = pipeline.compute_scores(view)
        label = pipeline.label(scores, self.thresholds)
        guarded = False
        if label == FailureType.LOOP_DETECTED.value and loop_lacks_content(trace, view):
            guarded = True
            self.insufficient_content_suppressed += 1
            label = pipeline.label(dataclasses.replace(scores, loop=False), self.thresholds)
            logger.info("detectors: loop on content-less spans not alerted trace_id=%s -> %s",
                        trace.trace_id, label)
        failure_type = FailureType(label)
        if failure_type == FailureType.NORMAL:
            return Classification(
                trace_id=trace.trace_id, failure_type=failure_type,
                triggered_rule=INSUFFICIENT_CONTENT if guarded else NO_DETECTOR_FIRED)
        evidence = from_detector({"pred": label}, view)
        return Classification(
            trace_id=trace.trace_id, failure_type=failure_type,
            confidence=RULE_CONFIDENCE.get(label), triggered_rule=RULE_NAMES[label],
            failure_span_id=evidence.span_id if evidence else None)
