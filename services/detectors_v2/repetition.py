"""C2: a pairwise-similar three-call group in a six-tool-call window."""
from itertools import combinations

from nexus_agent.models import SpanType
from services.detectors.common import tool_calls as frozen_tool_calls
from services.detectors_v2.normalization import argument_tokens, jaccard

MIN_CALLS = 3
WINDOW = 6
MIN_JACCARD = 0.8


def tool_calls(trace):
    # Retrieval remains an executed tool operation when named or TOOL-origin.
    # This projection is for repetition only; successful retrieval is not an
    # errored TOOL_CALL for the unchanged misfire rule.
    spans = []
    for span in trace.spans:
        raw = span.metadata.get("otel.attributes", {})
        if span.span_type == SpanType.RETRIEVAL and (span.metadata.get("tool_name") or raw.get("openinference.span.kind") == "TOOL"):
            span = span.model_copy(update={"span_type": SpanType.TOOL_CALL})
        spans.append(span)
    return frozen_tool_calls(trace.model_copy(update={"spans": spans}))


def loop(trace) -> bool:
    calls = tool_calls(trace)
    tokens = [argument_tokens(c.args_text) for c in calls]
    for end in range(MIN_CALLS, len(calls) + 1):
        for indices in combinations(range(max(0, end - WINDOW), end), MIN_CALLS):
            if indices[-1] != end - 1:
                continue
            if len({calls[i].tool for i in indices}) != 1:
                continue
            if all(jaccard(tokens[a], tokens[b]) >= MIN_JACCARD for a, b in combinations(indices, 2)):
                return True
    return False
