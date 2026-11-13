"""Synthetic A1 eligibility/abstention checks; no TRAIL or model inference."""
import pytest

from scripts.external.trail_dev_check_a1 import applicability
from services.collector.openinference import RETRIEVAL_TOOL_NAMES, complete_trace


def synthetic_trace(*, source=None, answer="The synthetic measurement is forty units.", failed=False):
    trace_id = "ab" * 16
    root = {"trace_id": trace_id, "span_id": "01" * 8, "timestamp": "2025-01-01T00:00:00Z",
            "duration": "PT2S", "status_code": "Ok", "span_attributes": {
                "openinference.span.kind": "AGENT", "input.value": "What is the synthetic measurement?",
                "output.value": answer}, "child_spans": []}
    if source is not None:
        root["child_spans"].append({"trace_id": trace_id, "span_id": "02" * 8,
            "timestamp": "2025-01-01T00:00:00Z", "duration": "PT1S",
            "status_code": "Error" if failed else "Ok", "span_attributes": {
                "openinference.span.kind": "TOOL", "tool.name": "visit_page", "output.value": source}})
    return complete_trace({"trace_id": trace_id, "spans": [root]})


def test_retrieval_list_is_exact_a1_schema_contract():
    assert RETRIEVAL_TOOL_NAMES == {"web_search", "visit_page", "page_down", "page_up",
                                    "find_on_page_ctrl_f", "inspect_file_as_text"}


@pytest.mark.parametrize("kwargs,expected", [
    ({}, (False, "no_successful_retrieval_text")),
    ({"source": "Synthetic external source text.", "failed": True}, (False, "no_successful_retrieval_text")),
    ({"source": "Synthetic external source text.", "answer": ""}, (False, "no_checkable_claims")),
    ({"source": "12345"}, (True, "source_below_registered_readability_gate")),
    ({"source": "Synthetic external source text."}, (True, None)),
])
def test_applicability_separates_frozen_abstentions_from_readability_exclusion(kwargs, expected):
    assert applicability(synthetic_trace(**kwargs)) == expected
