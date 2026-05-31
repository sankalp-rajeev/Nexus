"""Deterministic PatchProposal validator (Section 9.5).

Rejects proposals that are structurally incomplete or semantically vague.
Two retries then fallback — all decided by the LangGraph graph edges.
"""

from __future__ import annotations

from nexus_agent.models import PatchType

VAGUE_PHRASES = [
    "try improving",
    "consider changing",
    "might help",
    "could be better",
    "should be improved",
    "look into",
    "possibly fix",
]

_MIN_FIELD_LEN = 10


def validate_patch_proposal(proposal: dict) -> tuple[bool, str]:
    """Returns (is_valid, rejection_reason).

    Required fields must exist and be at least 10 characters long.
    patch_type must be a known PatchType value.
    confidence must be HIGH | MEDIUM | LOW.
    explanation must not contain vague hedge phrases.
    """
    required_fields = [
        "patch_type",
        "target_component",
        "explanation",
        "patch_content",
        "estimated_impact",
    ]
    for field in required_fields:
        val = proposal.get(field)
        if not val or len(str(val).strip()) < _MIN_FIELD_LEN:
            return False, f"Field '{field}' is missing or too short (< {_MIN_FIELD_LEN} chars)"

    if proposal.get("confidence") not in ("HIGH", "MEDIUM", "LOW"):
        return False, f"Invalid confidence: {proposal.get('confidence')!r}"

    if proposal.get("patch_type") not in PatchType.__members__:
        return False, f"Invalid patch_type: {proposal.get('patch_type')!r}"

    explanation_lc = proposal.get("explanation", "").lower()
    for phrase in VAGUE_PHRASES:
        if phrase in explanation_lc:
            return False, f"Explanation too vague: contains '{phrase}'"

    return True, ""


def format_trace_for_prompt(trace) -> str:
    """Render a CompleteTrace as a numbered list of span summaries."""
    lines = []
    for i, span in enumerate(trace.spans, 1):
        inp = (span.input or "")[:500]
        out = (span.output or "")[:500]
        err = f"  error_type: {span.error_type}\n  error_message: {span.error_message}" if span.error_type else ""
        lines.append(
            f"[{i}] span_id={span.span_id}\n"
            f"  span_type: {span.span_type.value.upper()}\n"
            f"  input: {inp}\n"
            f"  output: {out}\n"
            f"  duration_ms: {span.duration_ms:.1f}"
            + (f"\n{err}" if err else "")
        )
    return "\n\n".join(lines)


def format_failure_span(trace, failure_span_id: str | None) -> str:
    """Return the content of the failure span, or the last span if unknown."""
    span = None
    if failure_span_id:
        span = next((s for s in trace.spans if s.span_id == failure_span_id), None)
    if span is None and trace.spans:
        span = trace.spans[-1]
    if span is None:
        return "No span available."
    return (
        f"span_id: {span.span_id}\n"
        f"span_type: {span.span_type.value}\n"
        f"input: {(span.input or '')[:500]}\n"
        f"output: {(span.output or '')[:500]}\n"
        f"error_type: {span.error_type}\n"
        f"duration_ms: {span.duration_ms:.1f}"
    )
