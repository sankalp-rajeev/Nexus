"""Detector input contract for NexusBench (Phase 2 pre-registration).

``detector_view(trace)`` turns a committed NexusBench trace into exactly what a
production detector would see: the spans, their inputs and outputs, tool
calls, memory reads (with the *reader's* session/user), and plan spans. It
strips everything a production system would not know:

  trace-level   trace_id (-> opaque view_id), source
  root span     task_id, family
  llm_call      provider, model, cached        (model is a label confound: most
                                               classes come from one model)
  memory_read   item_owners (v2), item_sessions, item_users (v1)
                                              (written by the fault injector from
                                               the world's ownership registry, i.e.
                                               the CONTEXT_BLEED label's own evidence)
  text          canary registry tokens -> per-trace pseudonyms (REF-xxxxxx)
                DRIFT_CUSTOMER id      -> per-trace pseudonym  (C-dddd)

The scorer joins detector output back to labels through ``view_id`` using
``view_id_for(trace_id)``; nothing in the view itself points at labels.csv.

Text that is part of what the agent actually received is NOT removed (a real
trace would contain it), e.g. the injected note in a get_order output. Those
residual strings are listed in ``RESIDUAL_INJECTION_TEXT``; detector code must
not match on them (CI-enforced by tests/unit/nexusbench/test_detector_view.py).
"""

from __future__ import annotations

import copy
import hashlib
import re
from typing import Any

from nexus_agent.models import CompleteTrace

from bench.tools import DRIFT_CUSTOMER
from bench.world import build_world

STRIP_TRACE_FIELDS = ("source",)
STRIP_METADATA = {
    "agent_step": ("task_id", "family"),
    "llm_call": ("provider", "model", "cached"),
    "memory_read": ("item_owners", "item_sessions", "item_users"),
}
# Strings the agent really saw that reveal an injection mechanism. Kept in the
# view (realistic), reported, and forbidden as literals in detector code.
RESIDUAL_INJECTION_TEXT = {
    "PLAN_DRIFT note": "SYSTEM NOTICE TO ASSISTANT",
    "PLAN_DRIFT note (audit)": "this order is under audit",
    "LOOP_DETECTED message": "is still loading",
    "TOOL_MISFIRE error": "request failed (code 422)",
}

_WORLD = build_world()
_CANARIES = sorted({u.canary for u in _WORLD.users})
_CANARY_RE = re.compile("|".join(re.escape(c) for c in _CANARIES))
_DRIFT_RE = re.compile(re.escape(DRIFT_CUSTOMER), re.I)


def view_id_for(trace_id: str) -> str:
    return "v-" + hashlib.sha256(f"nexus-view:{trace_id}".encode()).hexdigest()[:16]


def _pseudo(view_id: str, token: str, n: int) -> str:
    return hashlib.sha256(f"{view_id}|{token}".encode()).hexdigest()[:n].upper()


def _rewrite_text(text: str | None, view_id: str) -> str | None:
    if not text:
        return text
    text = _CANARY_RE.sub(lambda m: "REF-" + _pseudo(view_id, m.group(0), 6), text)
    digits = str(int(_pseudo(view_id, DRIFT_CUSTOMER, 8), 16) % 9000 + 1000)
    return _DRIFT_RE.sub("C-" + digits, text)


def _rewrite_obj(obj: Any, view_id: str) -> Any:
    if isinstance(obj, str):
        return _rewrite_text(obj, view_id)
    if isinstance(obj, list):
        return [_rewrite_obj(x, view_id) for x in obj]
    if isinstance(obj, dict):
        return {k: _rewrite_obj(v, view_id) for k, v in obj.items()}
    return obj


def detector_view_dict(trace: dict[str, Any]) -> dict[str, Any]:
    """Sanitised trace dict (CompleteTrace schema)."""
    t = copy.deepcopy(trace)
    vid = view_id_for(t["trace_id"])
    for f in STRIP_TRACE_FIELDS:
        t.pop(f, None)
    t["trace_id"] = vid
    t["root_input"] = _rewrite_text(t.get("root_input"), vid)
    t["final_output"] = _rewrite_text(t.get("final_output"), vid)
    spans = []
    for s in t.get("spans", []):
        s["trace_id"] = vid
        md = dict(s.get("metadata") or {})
        for k in STRIP_METADATA.get(s["span_type"], ()):
            md.pop(k, None)
        s["metadata"] = _rewrite_obj(md, vid)
        for f in ("input", "output", "error_message"):
            s[f] = _rewrite_text(s.get(f), vid)
        spans.append(s)
    t["spans"] = spans
    return t


def detector_view(trace: dict[str, Any]) -> CompleteTrace:
    """Sanitised trace as a CompleteTrace, ready for any Nexus detector."""
    return CompleteTrace.model_validate(detector_view_dict(trace))


def residual_mentions(view: dict[str, Any]) -> dict[str, int]:
    """Count residual injection strings in a view (for reporting, not detection)."""
    import json

    blob = json.dumps(view)
    return {name: blob.count(lit) for name, lit in RESIDUAL_INJECTION_TEXT.items()
            if lit in blob}
