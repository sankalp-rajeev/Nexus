"""Span/trace feature extraction (Section 8.2)."""

from __future__ import annotations

import hashlib
import json

from nexus_agent.models import Span


def input_hash(span: Span) -> str:
    """Stable 16-char hash of a span's input (Section 8.2 rule logic)."""
    try:
        payload = json.dumps(span.input, sort_keys=True)
    except (TypeError, ValueError):
        payload = str(span.input)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def tool_key(span: Span) -> str:
    """Identifier used to group repeated calls: tool_name if present else type."""
    name = span.metadata.get("tool_name") if span.metadata else None
    return str(name) if name else span.span_type.value


def span_feature_string(span: Span) -> str:
    """The per-span feature string embedded in Stage 2 (Section 8.2 step 1)."""
    md = span.metadata or {}
    return (
        f"type: {span.span_type.value}\n"
        f"model: {md.get('model', 'none')}\n"
        f"input_summary: {(span.input or '')[:200]}\n"
        f"output_summary: {(span.output or '')[:200]}\n"
        f"duration_ms: {span.duration_ms}\n"
        f"has_error: {span.error_type is not None}\n"
        f"token_count: {md.get('tokens_used', 0)}"
    )
