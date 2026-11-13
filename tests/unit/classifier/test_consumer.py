"""Synthetic traffic retains classifications without reaching paid consumers."""
from datetime import datetime, timezone
import json
from unittest.mock import MagicMock

import pytest

from nexus_agent.models import CompleteTrace, Span, SpanType
from services.classifier.classifier import FailureClassifier
from services.classifier.consumer import ClassifierService, TOPIC_ALERTS, TOPIC_CLASSIFIED


def failing_trace():
    now = datetime.now(timezone.utc)
    return CompleteTrace(trace_id="synthetic-boundary", agent_name="demo", started_at=now,
                         spans=[Span(span_id=str(i), trace_id="synthetic-boundary", agent_name="demo",
                                     span_type=SpanType.TOOL_CALL, input="same", output="ok",
                                     duration_ms=1, client_timestamp=now, sdk_version="test",
                                     metadata={"tool_name": "search"}) for i in range(3)])


@pytest.mark.parametrize("marker", ["flag", "trace_agent_name", "trace_environment", "span_agent_name", "span_environment"])
def test_synthetic_failures_are_classified_without_alerts(marker, required_classifier_nli, caplog):
    trace = failing_trace()
    if marker == "flag":
        trace.spans[-1].metadata["nexus.synthetic"] = True
    elif marker.startswith("trace_"):
        setattr(trace, marker.removeprefix("trace_"), "phase5-load-dev")
    else:
        setattr(trace.spans[-1], marker.removeprefix("span_"), "phase5-load-dev")
    service = ClassifierService(FailureClassifier())
    service._producer = MagicMock()
    with caplog.at_level("INFO"):
        assert service.process_trace(trace) is None
    calls = service._producer.produce.call_args_list
    assert len(calls) == 1 and calls[0].args[0] == TOPIC_CLASSIFIED
    assert json.loads(calls[0].kwargs["value"])["failure_type"] == "LOOP_DETECTED"
    assert service.synthetic_suppressed == 1
    assert "synthetic_suppressed=1" in caplog.text


@pytest.mark.parametrize("marker", [None, False, "true"])
def test_same_failure_without_boolean_synthetic_flag_alerts(marker, required_classifier_nli):
    trace = failing_trace()
    if marker is not None:
        trace.spans[-1].metadata["nexus.synthetic"] = marker
    service = ClassifierService(FailureClassifier())
    service._producer = MagicMock()
    alert = service.process_trace(trace)
    assert alert is not None and alert.failure_type.value == "LOOP_DETECTED"
    assert [call.args[0] for call in service._producer.produce.call_args_list] == [TOPIC_CLASSIFIED, TOPIC_ALERTS]
    assert service.synthetic_suppressed == 0
