"""DEV ground-truth localization, SCORING ONLY; never imported by critic/adapter.

Fault origin convention: third successful repeated call for loop; original error
for misfire (not its retry); first foreign read for bleed; first injected-ID call
for drift; final-answer root span for hallucination. Steps index trace.spans at 0.
Absent mechanical evidence stays unknown, never replaced with a detector span.
"""
from services.critic.c3 import GroundTruth
from services.critic.detector_adapter import _calls


def truth_from_dev(label, trace, *, allowed_owners=None, drift_id=None):
    if label.get("split") != "dev":
        raise ValueError("Scoring accepts DEV only")
    ft = label["label"]
    calls = _calls(trace)
    candidates = []
    if ft == "LOOP_DETECTED":
        for a, b, c in zip(calls, calls[1:], calls[2:]):
            if a[2] == b[2] == c[2] and all(x[1].error_type is None for x in (a, b, c)):
                candidates = [c[:2]]
                break
    elif ft == "TOOL_MISFIRE":
        for i, call in enumerate(calls):
            if call[1].error_type and any(n[2] == call[2] for n in calls[i+1:i+3]):
                candidates = [call[:2]]
                break
    elif ft == "CONTEXT_BLEED":
        for i, s, _ in calls:
            if s.span_type.value != "memory_read" or s.error_type:
                continue
            md = s.metadata
            if "item_owners" in md:
                if allowed_owners is None:
                    from bench.memory import build_memory
                    from bench.world import build_world
                    registry = build_memory(build_world())
                    allowed = registry.allowed_owners(md.get("user_id") or "u-anon")
                else:
                    allowed = allowed_owners.get(md.get("user_id"), set())
                foreign = any(o not in allowed for o in md["item_owners"])
            else:
                foreign = any(sess != md.get("session_id") for sess in md.get("item_sessions", []))
            if foreign:
                candidates = [(i, s)]
                break
    elif ft == "PLAN_DRIFT":
        if drift_id is None:
            from bench.tools import DRIFT_CUSTOMER
            drift_id = DRIFT_CUSTOMER
        candidates = [(i, s) for i, s, _ in calls if drift_id.casefold() in s.input.casefold()]
    elif ft == "HALLUCINATION":
        candidates = [(i, s) for i, s in enumerate(trace.spans)
                      if s.metadata.get("role") == "root" and s.output]
    step, span = candidates[0] if candidates else (None, None)
    return GroundTruth(failure_type=ft, step=step, span_id=span.span_id if span else None,
                       span_ids=tuple(s.span_id for s in trace.spans))
