"""Scoring only: exact class and citation matching, never a critic dependency.

Envelope failure_type is supplied by the alert: proposal_type_match reports it
separately from independent diagnosis type_match. Historical
text is scored only for explicit FAILURE_TYPE/FAILURE_SPAN_ID/FAILURE_STEP lines.
Missing/ambiguous citations fail; unknown truth locations have a separate count.
"""
from collections import defaultdict
import re

from pydantic import BaseModel, ConfigDict, Field, model_validator
from services.critic.dev_adapter import CLASSES


class GroundTruth(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    failure_type: str
    span_id: str | None = None
    step: int | None = Field(default=None, ge=0)
    # Span order resolves citations and rejects mutually inconsistent fields.
    span_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def consistent(self):
        if self.step is not None and self.span_ids:
            if self.step >= len(self.span_ids):
                raise ValueError("Ground-truth step outside trace")
            if self.span_id and self.span_ids[self.step] != self.span_id:
                raise ValueError("Ground-truth span/step disagree")
        return self


def _explicit(text, field):
    values = re.findall(rf"^{field}:\s*([^\s]+)\s*$", text, re.MULTILINE)
    return values[0] if len(set(values)) == 1 else None


def score_c3(proposal, truth: GroundTruth, *, detector_type: str):
    p = proposal.model_dump(mode="json") if hasattr(proposal, "model_dump") else proposal or {}
    text = p.get("root_cause_analysis", "")
    diagnosed = p.get("diagnosed_failure_type") or _explicit(text, "FAILURE_TYPE")
    cited_span = p.get("cited_span_id") or _explicit(text, "FAILURE_SPAN_ID")
    cited_step = p.get("cited_step")
    if cited_step is None:
        raw = _explicit(text, "FAILURE_STEP")
        cited_step = int(raw) if raw and re.fullmatch(r"[0-9]+", raw) else None
    well_formed = (cited_step is None or type(cited_step) is int and cited_step >= 0)
    if truth.span_ids:
        if cited_span is not None and cited_span not in truth.span_ids:
            well_formed = False
        if cited_step is not None:
            if not well_formed or cited_step >= len(truth.span_ids):
                well_formed = False
            elif cited_span is not None and truth.span_ids[cited_step] != cited_span:
                well_formed = False
            else:
                cited_span = truth.span_ids[cited_step]
    located = truth.span_id is not None or truth.step is not None
    checks = []
    if cited_span is not None and truth.span_id is not None:
        checks.append(cited_span == truth.span_id)
    if cited_step is not None and truth.step is not None:
        checks.append(cited_step == truth.step)
    source_ok = p.get("provenance", {}).get("source", "llm") != "fallback"
    type_match = source_ok and diagnosed == truth.failure_type
    location_match = source_ok and well_formed and bool(checks) and all(checks)
    return {"failure_type": truth.failure_type, "detector_wrong": detector_type != truth.failure_type,
            "proposal_type_match": source_ok and p.get("failure_type") == truth.failure_type,
            "diagnosis_present": diagnosed is not None,
            "type_match": type_match, "location_scorable": located,
            "step_span_match": location_match if located else None,
            "joint_match": type_match and location_match if located else None,
            "diagnosed_failure_type": diagnosed, "cited_span_id": cited_span, "cited_step": cited_step}


def summarize_c3(scores):
    def metrics(rows):
        located = [r for r in rows if r["location_scorable"]]
        def prop(key, pool):
            k, n = sum(bool(r[key]) for r in pool), len(pool)
            return {"successes": k, "total": n, "rate": k/n if n else None}
        return {"n": len(rows), "unknown_truth_location": len(rows)-len(located),
                "proposal_type_match": prop("proposal_type_match", rows),
                "diagnosis_coverage": prop("diagnosis_present", rows),
                "type_match": prop("type_match", rows),
                "step_span_match": prop("step_span_match", located),
                "joint_match": prop("joint_match", located)}
    groups = defaultdict(list)
    for row in scores:
        groups[row["failure_type"]].append(row)
    wrong = [r for r in scores if r["detector_wrong"]]
    return {"overall": metrics(scores),
            "per_class": {ft: metrics(groups[ft]) for ft in CLASSES},
            "detector_wrong": {"overall": metrics(wrong),
                "per_class": {ft: metrics([r for r in wrong if r["failure_type"] == ft]) for ft in CLASSES}}}
