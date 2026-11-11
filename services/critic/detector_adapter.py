"""Label-blind adapter for Phase 2 predictions['id']['pred'] + detector_view.

Phase 2 stores no span attribution. Locations below are deterministic candidate
heuristics, not detector attribution or ground truth. NORMAL has no evidence.
No filesystem, benchmark, labeler, world registry, or injection imports here.
"""
import json
import re

from nexus_agent.models import CompleteTrace, FailureType
from services.critic.evidence import FailureEvidence

VIEW_ID = re.compile(r"v-[0-9a-f]{16}")
# Projection deliberately omits even extra fields attached to a view. Read only
# these deployment-visible metadata values; never enumerate unknown values.
VISIBLE_METADATA = ("tool_name", "role", "plan_steps", "session_id", "user_id")


def critic_view(view: CompleteTrace) -> CompleteTrace:
    if not VIEW_ID.fullmatch(view.trace_id):
        raise ValueError("Expected bench.detector_view with an opaque view ID")
    spans = []
    for span in view.spans:
        if span.trace_id != view.trace_id:
            raise ValueError("Span does not belong to detector view")
        metadata = {key: span.metadata[key] for key in VISIBLE_METADATA if key in span.metadata}
        spans.append(span.model_copy(update={"metadata": metadata}))
    return view.model_copy(update={"spans": spans})


def _calls(view):
    result = []
    for i, span in enumerate(view.spans):
        if span.span_type.value not in {"tool_call", "memory_read"}:
            continue
        try:
            args = json.dumps(json.loads(span.input), sort_keys=True)
        except ValueError:
            args = span.input
        result.append((i, span, (span.metadata.get("tool_name"), args)))
    return result


def from_detector(prediction, view: CompleteTrace) -> FailureEvidence | None:
    # Only this key is read: label_v1/model/judge fields in the Phase 2 result
    # are neither traversed nor copied. Labels are never an adapter argument.
    failure_type = FailureType(prediction["pred"])
    view = critic_view(view)
    if failure_type == FailureType.NORMAL:
        return None
    calls = _calls(view)
    candidates = []
    method = "candidate heuristic; Phase 2 has no span attribution"
    if failure_type == FailureType.LOOP_DETECTED:
        for a, b, c in zip(calls, calls[1:], calls[2:]):
            if a[2] == b[2] == c[2] and all(x[1].error_type is None for x in (a, b, c)):
                candidates = [c[:2]]
                break
    elif failure_type == FailureType.TOOL_MISFIRE:
        for i, call in enumerate(calls):
            if call[1].error_type and any(n[2] == call[2] for n in calls[i+1:i+3]):
                candidates = [call[:2]]
                break
    elif failure_type == FailureType.CONTEXT_BLEED:
        candidates = [(i, s) for i, s in enumerate(view.spans)
                      if s.span_type.value == "memory_read" and not s.error_type]
    elif failure_type == FailureType.PLAN_DRIFT:
        plan = next((s.metadata.get("plan_steps") for s in view.spans
                     if s.metadata.get("role") == "planner"), None)
        candidates = [(i, s) for i, s, _ in calls
                      if plan is not None and s.metadata.get("tool_name") not in plan]
        if not candidates:
            candidates = [(i, s) for i, s, _ in calls]
    else:
        candidates = [(i, s) for i, s in enumerate(view.spans) if s.metadata.get("role") == "root"]
    if not candidates:
        candidates = list(enumerate(view.spans[-1:], start=max(len(view.spans)-1, 0)))
        method = "last-span fallback; Phase 2 has no span attribution"
    if not candidates:
        raise ValueError("Failure prediction has no observed spans")
    step, span = candidates[0]
    return FailureEvidence(failure_type=failure_type, span_id=span.span_id, step=step,
        supporting_text=json.dumps({"input": span.input, "output": span.output,
            "error": span.error_message, "metadata": span.metadata,
            "localization": method}, ensure_ascii=False))
