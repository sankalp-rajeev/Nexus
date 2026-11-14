"""C1 wrapper around the unchanged OpenInference/A1 adapter."""
import json
import re

from nexus_agent.models import SpanType
from services.collector import openinference as v1


def error_output(output: str | None) -> bool:
    if not output:
        return False
    try:
        obj = json.loads(output)
    except (ValueError, TypeError):
        obj = None
    if isinstance(obj, dict):
        keys = {str(k).casefold().replace("_", ""): v for k, v in obj.items()}
        if keys.get("iserror") is True or keys.get("success") is False:
            return True
        if str(keys.get("status", "")).casefold() in {"error", "failed", "failure"}:
            return True
        if keys.get("error") not in (None, False, "", [], {}):
            return True
    return bool(re.match(r"^\s*(?:error\s*:|tool error\s*:|traceback \(most recent call last\)\s*:|[A-Za-z_][\w.]*(?:Error|Exception)\s*:)", output, re.I))


def adapt(trace):
    spans = []
    for span in trace.spans:
        raw = span.metadata.get("otel.attributes", {})
        kind = str(raw.get("openinference.span.kind", "")).upper()
        matched = kind == "RETRIEVER" or (kind == "TOOL" and raw.get("tool.name") in v1.RETRIEVAL_TOOL_NAMES)
        if matched and span.span_type == SpanType.RETRIEVAL and (span.error_type is not None or error_output(span.output)):
            metadata = dict(span.metadata)
            metadata["v2.retrieval_error_kept_as_tool"] = True
            span = span.model_copy(update={"span_type": SpanType.TOOL_CALL,
                "error_type": span.error_type or "ToolOutputError", "metadata": metadata})
        spans.append(span)
    return trace.model_copy(update={"spans": spans})


def complete_trace(source):
    return adapt(v1.complete_trace(source))
