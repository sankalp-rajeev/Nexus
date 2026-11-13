"""6.3b: the scored Phase 2 detectors are the classifier service's default; legacy is a flag.

No model is loaded here: the traces have no retrieved context, so the frozen HALLUCINATION detector
returns None without touching the NLI model, and model loading is stubbed where it is exercised.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bench.detector_view import detector_view
from nexus_agent.models import CompleteTrace, FailureType, Span, SpanType

from services.classifier import live_detectors
from services.classifier.classifier import FailureClassifier
from services.classifier.consumer import TOPIC_ALERTS, ClassifierService
from services.classifier.embedder import NLIModelUnavailable
from services.classifier.live_detectors import (
    INSUFFICIENT_CONTENT, DetectorClassifier, detector_config, loop_runs,
)
from services.classifier.main import build_classifier, classifier_mode
from services.detectors import hallucination, pipeline

ROOT = Path(__file__).resolve().parents[3]
MISSING = "nexus.content_missing"
_clock = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _span(i, *, tool="lookup", args="{}", error=False, missing=False, trace_id="t-live") -> Span:
    md = {"tool_name": tool}
    if missing:
        md[MISSING] = True
    return Span(
        span_id=f"s{i:03d}", trace_id=trace_id, agent_name="agent", span_type=SpanType.TOOL_CALL,
        input=args, output=None if error else ("" if missing else "ok"), duration_ms=1.0,
        error_type="ToolError" if error else None, error_message="boom" if error else None,
        metadata=md, client_timestamp=_clock.replace(second=i), sdk_version="1.0.0")


def _trace(spans) -> CompleteTrace:
    return CompleteTrace(trace_id="t-live", agent_name="agent", started_at=_clock,
                         span_count=len(spans), spans=spans)


def _view(trace: CompleteTrace) -> CompleteTrace:
    return detector_view(trace.model_dump(mode="json"))


# ── flag and wiring ──────────────────────────────────────────────────────────

def test_default_is_detectors_and_legacy_is_explicit(monkeypatch):
    monkeypatch.delenv("NEXUS_CLASSIFIER", raising=False)
    assert classifier_mode() == "detectors"
    assert isinstance(build_classifier(), DetectorClassifier)
    monkeypatch.setenv("NEXUS_CLASSIFIER", "legacy")
    assert classifier_mode() == "legacy"
    assert isinstance(build_classifier(), FailureClassifier)
    monkeypatch.setenv("NEXUS_CLASSIFIER", " Detectors ")
    assert classifier_mode() == "detectors"


def test_unknown_classifier_value_refuses_instead_of_guessing(monkeypatch):
    monkeypatch.setenv("NEXUS_CLASSIFIER", "patchcore")
    with pytest.raises(ValueError, match="NEXUS_CLASSIFIER"):
        classifier_mode()


def test_detector_config_names_the_phase2_scoring_configuration():
    config = detector_config()
    th = json.loads((ROOT / "services/detectors/thresholds.json").read_text(encoding="utf-8"))
    pins = json.loads((ROOT / ".github/model-revisions.json").read_text(encoding="utf-8"))
    assert config["frozen_tag"] == "phase2-detectors-frozen"
    assert config["thresholds"] == {"HALLUCINATION": th["HALLUCINATION"]["threshold"],
                                    "CONTEXT_BLEED": th["CONTEXT_BLEED"]["threshold"],
                                    "PLAN_DRIFT": th["PLAN_DRIFT"]["variant"]}
    assert config["nli_model"] == hallucination.NLI_MODEL == "cross-encoder/nli-deberta-v3-base"
    assert config["nli_revision"] == pins[hallucination.NLI_MODEL]
    assert config["precedence"] == pipeline.ORDER
    assert "no LLM judge" in config["variant"]


def test_service_requires_the_detector_nli_model_not_the_legacy_one(monkeypatch):
    called = []
    monkeypatch.setattr(hallucination, "_nli", lambda: called.append("deberta"))
    service = ClassifierService(DetectorClassifier())
    service.require_nli()
    assert called == ["deberta"]
    service._running = True  # health is "ok" only while the consumer runs
    state = service.health()
    assert state["classifier"] == "detectors" and state["nli_ready"]
    assert state["detector_config"]["frozen_tag"] == "phase2-detectors-frozen"
    assert state["insufficient_content_suppressed"] == 0
    json.dumps(state)


def test_missing_detector_model_refuses_with_the_nli_error(monkeypatch):
    def broken():
        raise OSError("no such file")

    monkeypatch.setattr(hallucination, "_nli", broken)
    service = ClassifierService(DetectorClassifier())
    with pytest.raises(NLIModelUnavailable, match="nli-deberta-v3-base"):
        service.require_nli()
    state = service.health()
    assert state["status"] == "unhealthy" and not state["nli_ready"]


def test_staged_revision_that_is_not_the_pin_is_refused(monkeypatch):
    monkeypatch.setattr(live_detectors, "staged_revision", lambda: "0" * 40)
    monkeypatch.setattr(hallucination, "_nli", lambda: pytest.fail("must not load an unpinned model"))
    with pytest.raises(NLIModelUnavailable, match="pinned"):
        DetectorClassifier().require_models()


def test_legacy_service_still_requires_the_legacy_nli_model(monkeypatch):
    from services.classifier.embedder import NLIScorer

    monkeypatch.setattr(NLIScorer, "_instance", None)
    monkeypatch.setattr(NLIScorer, "MODEL_NAME", "does/not-exist-offline")
    service = ClassifierService(MagicMock())
    with pytest.raises(NLIModelUnavailable):
        service.require_nli()
    assert service.health()["classifier"] == "legacy"


# ── detectors are called as Phase 4 called them ─────────────────────────────

def test_classification_equals_the_frozen_pipeline_label_and_maps_back_the_real_trace_id():
    trace = _trace([_span(i, args=json.dumps({"q": "same"})) for i in range(3)])
    result = DetectorClassifier().classify(trace)
    assert result.trace_id == "t-live"  # the opaque view id never leaks out
    assert result.failure_type == FailureType.LOOP_DETECTED
    assert result.triggered_rule == "detectors:loop" and result.confidence == 1.0
    assert result.failure_span_id == "s002"  # from_detector: third call of the first identical triple


def test_clean_trace_is_normal_with_no_rule_fired():
    trace = _trace([_span(0, tool="a", args='{"q": 1}'), _span(1, tool="b", args='{"q": 2}')])
    result = DetectorClassifier().classify(trace)
    assert (result.failure_type, result.triggered_rule, result.failure_span_id) == (
        FailureType.NORMAL, "detectors:none", None)


def test_retried_error_is_a_misfire():
    trace = _trace([_span(0, args='{"q": 1}', error=True), _span(1, args='{"q": 1}', error=True)])
    result = DetectorClassifier().classify(trace)
    assert (result.failure_type, result.triggered_rule) == (FailureType.TOOL_MISFIRE, "detectors:misfire")


# ── content-missing guard ────────────────────────────────────────────────────

def test_loop_of_content_less_spans_is_not_alerted_and_is_counted():
    """The 3-span case from 6.3: identical-looking calls whose arguments were never captured."""
    classifier = DetectorClassifier()
    trace = _trace([_span(i, missing=True, args="") for i in range(3)])
    assert pipeline.compute_scores(_view(trace)).loop is True  # the frozen rule does fire
    service = ClassifierService(classifier)
    service._producer = MagicMock()
    service.require_nli = lambda: None
    assert service.process_trace(trace) is None  # no alert
    topics = [c.args[0] for c in service._producer.produce.call_args_list]
    assert TOPIC_ALERTS not in topics
    published = json.loads(service._producer.produce.call_args_list[0].kwargs["value"])
    assert published["failure_type"] == "NORMAL" and published["triggered_rule"] == INSUFFICIENT_CONTENT
    assert classifier.insufficient_content_suppressed == 1
    assert service.health()["insufficient_content_suppressed"] == 1


def test_same_loop_with_captured_arguments_still_alerts():
    classifier = DetectorClassifier()
    trace = _trace([_span(i, args=json.dumps({"q": "same"})) for i in range(3)])
    result = classifier.classify(trace)
    assert result.failure_type == FailureType.LOOP_DETECTED
    assert classifier.insufficient_content_suppressed == 0


def test_guard_needs_every_looping_span_to_be_content_less():
    # Two flagged no-argument calls and one real no-argument call: the run is not all content-less.
    classifier = DetectorClassifier()
    trace = _trace([_span(0, missing=True, args=""), _span(1, missing=True, args=""), _span(2, args="")])
    runs = loop_runs(_view(trace))
    assert runs == [["s000", "s001", "s002"]]
    assert classifier.classify(trace).failure_type == FailureType.LOOP_DETECTED
    assert classifier.insufficient_content_suppressed == 0


def test_flagged_spans_elsewhere_do_not_hide_a_real_loop():
    classifier = DetectorClassifier()
    spans = [_span(0, tool="other", missing=True, args=""), *[_span(i, args='{"q": "x"}') for i in (1, 2, 3)]]
    assert classifier.classify(_trace(spans)).failure_type == FailureType.LOOP_DETECTED
    assert classifier.insufficient_content_suppressed == 0


def test_guard_drops_only_the_loop_verdict_other_detectors_still_fire():
    classifier = DetectorClassifier()
    spans = [*[_span(i, tool="lookup", missing=True, args="") for i in range(3)],
             _span(3, tool="pay", args='{"id": 7}', error=True), _span(4, tool="pay", args='{"id": 7}', error=True)]
    result = classifier.classify(_trace(spans))
    assert (result.failure_type, result.triggered_rule) == (FailureType.TOOL_MISFIRE, "detectors:misfire")
    assert classifier.insufficient_content_suppressed == 1


def test_native_spans_without_the_flag_are_never_guarded():
    # SDK spans carry content (or genuinely empty content) and never set the OTLP-only flag.
    classifier = DetectorClassifier()
    trace = _trace([_span(i, args="") for i in range(3)])
    assert classifier.classify(trace).failure_type == FailureType.LOOP_DETECTED
    assert classifier.insufficient_content_suppressed == 0
