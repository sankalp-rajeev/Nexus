"""Aggregate-only TRAIL publication boundary shared by RESULTS and the dashboard.

Exact filenames, validated counts and selected numeric fields only. No raw
TRAIL/private path or NexusBench TEST result can be passed to this loader.
"""
import json
from pathlib import Path

A_RESULT = "results/external/trail_test.json"
B_RESULT = "results/external/trail_b_test.json"
DEV_SUMMARY = "results/external/trail_v2_dev_summary.json"
EXTERNAL_AGGREGATES = frozenset((A_RESULT, B_RESULT, DEV_SUMMARY))
CLASSES = ("LOOP_DETECTED", "TOOL_MISFIRE", "HALLUCINATION")
REASONS = frozenset(("no_successful_retrieval_text", "no_checkable_claims", "source_below_registered_readability_gate",
    "conversion_failure", "malformed_category_or_location", "invalid_label_json", "missing_label_trace_id"))
ROOT = Path(__file__).resolve().parents[1]


def load_aggregate(path, root=ROOT):
    if path not in EXTERNAL_AGGREGATES:
        raise ValueError("Not an approved committed TRAIL aggregate")
    return json.loads((Path(root) / path).read_text(encoding="utf-8"))


def _count(value):
    if type(value) is not int or value < 0:
        raise ValueError("Expected a nonnegative aggregate count")
    return value


def _metric(node, numerator, denominator):
    if node["numerator"] != numerator or node["denominator"] != denominator:
        raise ValueError("Metric denominator disagrees with confusion counts")
    estimate, ci = node["estimate"], node["wilson95"]
    if denominator == 0:
        if estimate is not None or ci is not None:
            raise ValueError("Undefined metric must stay undefined")
    elif estimate != numerator / denominator or not isinstance(ci, list) or len(ci) != 2 or not 0 <= ci[0] <= ci[1] <= 1:
        raise ValueError("Invalid recorded metric or interval")
    return {"numerator": numerator, "denominator": denominator, "estimate": estimate, "wilson95": ci}


def _reasons(node):
    if set(node) - REASONS:
        raise ValueError("Unregistered reason in publication")
    return {key: _count(value) for key, value in node.items()}


def row(node, cohort, version, cls, size, source, mapping="primary"):
    counts = {key: _count(node[key]) for key in ("tp", "fp", "fn", "tn")}
    evaluated = sum(counts.values())
    abstentions, exclusions = _reasons(node["abstentions"]), _reasons(node["exclusions"])
    if node["evaluated"] != evaluated or evaluated + sum(abstentions.values()) + sum(exclusions.values()) != size:
        raise ValueError("Aggregate cohort denominator mismatch")
    cohort_positive = node.get("gold_positive_in_cohort_assessable")
    if cohort_positive is not None and _count(cohort_positive) > size:
        raise ValueError("Cohort positive count exceeds cohort size")
    return {"cohort": cohort, "version": version, "class_name": cls, "mapping": mapping,
        "cohort_denominator": size, "evaluated": evaluated, **counts,
        "gold_positive": counts["tp"] + counts["fn"],
        "cohort_gold_positive": cohort_positive,
        "precision": _metric(node["precision"], counts["tp"], counts["tp"] + counts["fp"]),
        "recall": _metric(node["recall"], counts["tp"], counts["tp"] + counts["fn"]),
        "abstentions": abstentions, "exclusions": exclusions, "source": source}


def build_external_trail(root=ROOT):
    a, b, dev = (load_aggregate(p, root) for p in (A_RESULT, B_RESULT, DEV_SUMMARY))
    rows = [row(a["classes"][c], "TRAIL-A", "v1", c, a["cohort_flow"]["TRAIL_A"], A_RESULT) for c in CLASSES]
    for mapping in ("primary", "C3_secondary"):
        for version in ("v1", "v2"):
            rows += [row(b["mappings"][mapping][version]["classes"][c], "TRAIL-B", version, c,
                b["cohort_flow"]["TRAIL_B"], B_RESULT, mapping) for c in CLASSES]
    # Copy known fields only. Even a stray prompt/output in an input JSON cannot
    # enter the publication payload through a generic dictionary spread.
    dataset = dev["dataset"]
    guardrail = dev["guardrail"]
    claims = dev["claims"]
    return {"aggregate_only": True, "rows": rows,
        "dataset": {k: dataset[k] for k in ("name", "traces", "license", "gated", "card")},
        "guardrail": {k: guardrail[k] for k in ("independent_macro_v1", "independent_macro_v2", "priority_macro_v1",
            "priority_macro_v2", "priority_macro_drop", "drop_limit", "masked_misfires", "v2_live_candidate")},
        "claims": {k: claims[k] for k in ("primary_hypothesis", "loop_dev_precision", "loop_dev_recall", "misfire_min_positives",
            "hallucination_dev_precision", "hallucination_dev_recall", "hallucination_improvement_claim")},
        "sources": {"A": A_RESULT, "B": B_RESULT, "development": DEV_SUMMARY, "protocol": "reports/external/trail_prereg_a3.md"}}


def metric_text(value):
    if value["estimate"] is None:
        return "undefined (n=0)"
    lo, hi = value["wilson95"]
    return f"{100*value['estimate']:.2f}% [{100*lo:.2f}%, {100*hi:.2f}%]"


def reasons_text(values):
    return "; ".join(f"{key}: {value}" for key, value in values.items()) or "none (0)"
