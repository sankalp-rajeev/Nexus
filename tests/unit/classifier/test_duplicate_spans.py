"""A retried (duplicate) batch must not change what the classifier sees or alerts on."""
import json
from unittest.mock import MagicMock

from nexus_agent.models import Span
from services.classifier.main import load_classifier
from services.classifier.consumer import ClassifierService, TOPIC_ALERTS, TOPIC_CLASSIFIED
from services.common.trace_buffer import TraceBuffer
from tests.unit.common.test_trace_buffer import batch


def run(deliveries, classifier):
    service = ClassifierService(classifier, buffer=TraceBuffer())
    service._producer = MagicMock()
    for spans in deliveries:
        for s in spans:
            service._handle(s.model_dump_json().encode())
    calls = service._producer.produce.call_args_list
    return service, [(c.args[0], json.loads(c.kwargs["value"])) for c in calls]


def comparable(classification):
    return {k: classification[k] for k in
            ("trace_id", "failure_type", "anomaly_score", "confidence", "triggered_rule", "failure_span_id")}


def test_duplicate_batch_gives_identical_classification_and_no_extra_alert(required_classifier_nli):
    classifier = load_classifier()  # the tracked trained model, as the service loads it
    first, final = batch("dup-trace")
    once_service, once = run([first, final], classifier)
    twice_service, twice = run([first, first, final], classifier)  # retried batch delivered twice
    late_service, late = run([first, final, first, final], classifier)  # ... and again after completion

    # Two legitimate identical tool calls are below the 3x loop threshold: not a loop.
    assert [t for t, _ in once] == [TOPIC_CLASSIFIED]
    assert once[0][1]["failure_type"] != "LOOP_DETECTED"
    for service, got in ((twice_service, twice), (late_service, late)):
        assert [t for t, _ in got] == [t for t, _ in once]  # exactly one classification
        assert TOPIC_ALERTS not in [t for t, _ in got]  # and no extra alert
        assert comparable(got[0][1]) == comparable(once[0][1])
    assert twice_service.buffer.duplicate_spans_dropped == 2
    assert late_service.buffer.duplicate_spans_dropped == 3
    assert twice_service.health()["duplicate_spans_dropped"] == 2


def test_without_dedup_the_same_duplicates_would_have_raised_a_loop_alert(required_classifier_nli):
    """Regression guard: show the failure mode the buffer now prevents (4 > 3 identical calls)."""
    from services.classifier.rules import apply_rules
    from nexus_agent.models import CompleteTrace

    first, final = batch("naive")
    naive = first + first + final  # what a buffer that only appends would assemble
    trace = CompleteTrace(trace_id="naive", agent_name="agent", started_at=naive[0].client_timestamp,
                          spans=naive)
    assert apply_rules(trace).failure_type.value == "LOOP_DETECTED"
