"""Stage 1 — rule-based pre-filter (Section 8.2).

Fast, zero-ML deterministic checks. If any rule fires we classify immediately
and skip embedding entirely.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from nexus_agent.models import CompleteTrace, FailureType, SpanType

from services.classifier.features import input_hash, tool_key

LOOP_THRESHOLD = 3  # same (tool, input) >= 3 times -> LOOP_DETECTED
RETRY_WINDOW = 3  # look ahead N spans for an identical retry after an error


@dataclass
class RuleResult:
    failure_type: FailureType
    failure_span_id: str | None
    triggered_rule: str


def loop_detector(trace: CompleteTrace) -> RuleResult | None:
    """Fire LOOP_DETECTED if any (tool_name, input_hash) repeats >= 3x."""
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for span in trace.spans:
        groups[(tool_key(span), input_hash(span))].append(span.span_id)
    for (_, _), span_ids in groups.items():
        if len(span_ids) >= LOOP_THRESHOLD:
            return RuleResult(FailureType.LOOP_DETECTED, span_ids[0], "loop_detector")
    return None


def tool_error_retry(trace: CompleteTrace) -> RuleResult | None:
    """Fire TOOL_MISFIRE: a tool_call errors, then an identical call recurs
    within the next RETRY_WINDOW spans of the same trace."""
    spans = trace.spans
    for i, span in enumerate(spans):
        if span.span_type != SpanType.TOOL_CALL or span.error_type is None:
            continue
        target = (tool_key(span), input_hash(span))
        for follower in spans[i + 1 : i + 1 + RETRY_WINDOW]:
            if (tool_key(follower), input_hash(follower)) == target:
                return RuleResult(FailureType.TOOL_MISFIRE, span.span_id, "tool_error_retry")
    return None


RULES = (loop_detector, tool_error_retry)


def apply_rules(trace: CompleteTrace) -> RuleResult | None:
    """Run all Stage 1 rules in order; return the first that fires."""
    for rule in RULES:
        result = rule(trace)
        if result is not None:
            return result
    return None
