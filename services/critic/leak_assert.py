"""Corrected evidence invariant: observed substrings, no registry/label metadata.

Observed injection text is allowed. All wire string values, including the complete
supporting_text excerpt, must be literal substrings of a canonical official view.
Embedded JSON is additionally traversed for forbidden keys and label field values.
The privileged checker gets injection registry tokens; the adapter never does.
"""
import hashlib
import json

from nexus_agent.models import FailureType

FORBIDDEN_KEYS = frozenset({"dev_label", "item_users", "item_sessions", "item_owners",
                            "source", "task_id", "family", "model", "provider"})
LABEL_VALUES = frozenset({ft.value for ft in FailureType} | {"OTHER_FAILURE", "RUN_ERROR"})
INVARIANT_VERSION = "observed-substrings-no-label-metadata-v2"


class EvidenceLeakError(RuntimeError):
    def __init__(self, audit):
        self.audit = audit
        super().__init__(f"Detector evidence leak: {audit['evidence_with_leaks']}/{audit['evidence_checked']} evidence objects")


def serialize_view(view):
    value = view.model_dump(mode="json") if hasattr(view, "model_dump") else view
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def audit_evidence(evidence, views, *, raw_canaries=(), raw_drift_target=None):
    entries, hashes = [], {}
    count = 0
    string_count = 0
    for tid, ev in evidence.items():
        if ev is None:
            continue
        count += 1
        hits = []
        view_text = serialize_view(views[tid]) if tid in views else ""
        hashes[tid] = hashlib.sha256(view_text.encode()).hexdigest()
        payload = ev.model_dump(mode="json")

        def walk(obj, path, *, check_substrings=True, hits=hits, view_text=view_text):
            nonlocal string_count
            if isinstance(obj, dict):
                for key, val in obj.items():
                    if key in FORBIDDEN_KEYS:
                        hits.append({"rule": "forbidden_key", "path": f"{path}.{key}"})
                    walk(val, f"{path}.{key}", check_substrings=check_substrings)
            elif isinstance(obj, list):
                for i, val in enumerate(obj):
                    walk(val, f"{path}[{i}]", check_substrings=check_substrings)
            elif isinstance(obj, str):
                if check_substrings:
                    string_count += 1
                    if not obj or obj not in view_text:
                        hits.append({"rule": "string_not_in_detector_view", "path": path})
                if obj in LABEL_VALUES:
                    hits.append({"rule": "label_field_value", "path": path})
                if any(token and token in obj for token in raw_canaries):
                    hits.append({"rule": "raw_canary", "path": path})
                if raw_drift_target and raw_drift_target in obj:
                    hits.append({"rule": "raw_drift_target", "path": path})
                try:
                    nested = json.loads(obj)
                except (ValueError, TypeError):
                    return
                # Wire strings have already been matched byte-for-byte above.
                # Decode nested JSON only for key/value bans; do not confuse JSON
                # escaping with adding unobserved content to a complete excerpt.
                if isinstance(nested, (dict, list, str)) and nested != obj:
                    walk(nested, path+"<json>", check_substrings=False)
        walk(payload, "FailureEvidence")
        if hits:
            entries.append({"trace_id": tid, "span_id": ev.span_id, "hits": hits})
    return {"invariant_version": INVARIANT_VERSION,
            "status": "failed" if entries else "passed", "traces_checked": len(evidence),
            "evidence_checked": count, "string_values_checked": string_count,
            "detector_arm_evidence_instances_checked": count*2,
            "detector_misses_without_evidence": len(evidence)-count,
            "evidence_with_leaks": len(entries), "leaks": entries,
            "forbidden_keys": sorted(FORBIDDEN_KEYS), "forbidden_label_values": sorted(LABEL_VALUES),
            "raw_canaries_checked": len(raw_canaries), "raw_drift_target_checked": raw_drift_target is not None,
            "detector_view_sha256": hashes,
            "observed_injection_text": "allowed only as a literal detector_view substring",
            "serialization": "UTF-8 JSON; sort_keys=True; ensure_ascii=False; separators=(',', ':')"}


def assert_no_evidence_leaks(evidence, views, output, *, raw_canaries=(), raw_drift_target=None):
    audit = audit_evidence(evidence, views, raw_canaries=raw_canaries, raw_drift_target=raw_drift_target)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(audit, indent=2)+"\n", encoding="utf-8")
    if audit["evidence_with_leaks"]:
        raise EvidenceLeakError(audit)
    return audit
