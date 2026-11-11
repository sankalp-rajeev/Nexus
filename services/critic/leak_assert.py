"""Fail-closed, read-only check before constructing any generation provider.

Do not redact/rewrite evidence to pass this gate: a hit stops the run for review.
"""
import json
import re


class EvidenceLeakError(RuntimeError):
    def __init__(self, audit):
        self.audit = audit
        super().__init__(f"Detector evidence leak: {audit['evidence_with_leaks']}/{audit['evidence_checked']} evidence objects")


def audit_evidence(evidence, *, injection_texts):
    entries = []
    count = 0
    fields = ("dev_label", "item_users", "item_sessions", "item_owners")
    for tid, ev in evidence.items():
        if ev is None:
            continue
        count += 1
        text = ev.model_dump_json()
        hits = [f"forbidden_field:{key}" for key in fields if re.search(rf"\b{key}\b", text)]
        if re.search(r"\bCANARY-[A-Za-z0-9]+\b", text, re.I):
            hits.append("canary_token")
        for name, value in injection_texts.items():
            if value.casefold() in text.casefold():
                hits.append(f"injection_text:{name}")
        if hits:
            entries.append({"trace_id": tid, "span_id": ev.span_id, "hits": hits})
    return {"status": "failed" if entries else "passed", "traces_checked": len(evidence),
            "evidence_checked": count, "detector_arm_evidence_instances_checked": count*2,
            "detector_misses_without_evidence": len(evidence)-count,
            "evidence_with_leaks": len(entries), "leaks": entries,
            "field_rules": fields, "canary_rule": "CANARY-<alphanumeric>",
            "injection_text_rules": dict(injection_texts),
            "remediation": "Stop before generation; no redaction or silent evidence rewrite"}


def assert_no_evidence_leaks(evidence, output, *, injection_texts):
    audit = audit_evidence(evidence, injection_texts=injection_texts)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(audit, indent=2), encoding="utf-8")
    if audit["evidence_with_leaks"]:
        raise EvidenceLeakError(audit)
    return audit
