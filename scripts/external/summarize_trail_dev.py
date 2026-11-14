"""Publish existing development aggregates only; no trace access or scoring."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    private = ROOT / "data/external/trail/v2_development"
    nexus_path, trail_path = private / "nexus_aggregate.json", private / "trail_aggregate.json"
    nexus, trail = (json.loads(p.read_text()) for p in (nexus_path, trail_path))
    manifest = json.loads((ROOT / "reports/external/trail_split/manifest.json").read_text())
    chosen = trail["tables"]["v1"]["v2_final"]
    if nexus["frozen_v2_commit"] != "5660480673c8a4b3b1f2dbbd0dad6b2438ea3284" or trail["selection"]["scope"] != "final":
        raise RuntimeError("Development freeze differs")
    summary = {
        "scope": "development, not a result",
        "dataset": {"name": "PatronusAI/TRAIL", "traces": sum(manifest["source_counts"].values()),
            "source_counts": manifest["source_counts"], "revision": manifest["revision"], "license": "MIT", "gated": True,
            "card": "https://huggingface.co/datasets/PatronusAI/TRAIL"},
        "guardrail": {"independent_macro_v1": nexus["v1"]["macro_recall_five_flags"],
            "independent_macro_v2": nexus["v2"]["macro_recall_five_flags"],
            "priority_macro_v1": nexus["v1"]["macro_recall_five_priority"],
            "priority_macro_v2": nexus["v2"]["macro_recall_five_priority"],
            "priority_macro_drop": -nexus["macro_recall_deltas"]["macro_recall_five_priority"],
            "drop_limit": .02,
            "masked_misfires": nexus["v1"]["priority_classes"]["TOOL_MISFIRE"]["tp"] - nexus["v2"]["priority_classes"]["TOOL_MISFIRE"]["tp"],
            "false_alert_increase": nexus["false_alert_increase"], "v2_live_candidate": False},
        "claims": {"primary_hypothesis": "LOOP_DETECTED",
            "loop_dev_precision": chosen["LOOP_DETECTED"]["precision"]["estimate"],
            "loop_dev_recall": chosen["LOOP_DETECTED"]["recall"]["estimate"],
            "misfire_min_positives": 5, "hallucination_improvement_claim": False,
            "hallucination_dev_precision": chosen["HALLUCINATION"]["precision"]["estimate"],
            "hallucination_dev_recall": chosen["HALLUCINATION"]["recall"]["estimate"]},
        "c5": {"chosen": "final", "final_f1": trail["selection"]["final"]["f1"],
            "all_llm_f1": trail["selection"]["all_llm"]["f1"]},
        "provenance": {"frozen_v2_commit": nexus["frozen_v2_commit"],
            "report": "reports/external/trail_v2_dev.md", "protocol": "reports/external/trail_prereg_a3.md",
            "private_aggregate_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (nexus_path, trail_path)},
            "statement": "Transcribed from existing aggregate development records; no detectors rerun; no trace content"}}
    target = ROOT / "results/external/trail_v2_dev_summary.json"
    text = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    if target.exists() and target.read_text() != text:
        raise RuntimeError("Refusing to replace changed development summary")
    target.write_text(text, encoding="utf-8")
    print("Wrote aggregate-only TRAIL development summary; no trace files opened")


if __name__ == "__main__":
    main()
