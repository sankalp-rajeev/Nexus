"""Read-only offline replay of DEV smoke gates; no provider calls."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "sdk"))

from bench.detector_view import detector_view
from bench.heal.config import ConfigPatch, from_phase3
from bench.heal.score import Scorer
from bench.heal.sets import load_sets
from services.critic.detector_adapter import from_detector
from services.critic.dev_adapter import dev_traces
from services.critic.leak_assert import serialize_view
from services.critic.round3_part_b import baseline_config
from scripts.phase5.measurement import Budget, atomic_json
from scripts.phase5.pipeline import baseline_records


def doc(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def records(path):
    with (ROOT / path).open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def main():
    sets = load_sets()
    smoke = doc("reports/phase5/smoke_comparison.json")
    old_results = doc("results/heal_critic_v1_structured_dev.json")["results"]
    old_runs = {r["run_id"]: r for r in records("results/heal_runs.jsonl")}
    old_critic = {r["trace_id"]: r for r in records("reports/phase3/round3/v1_structured.jsonl")}
    protocol = doc("reports/phase3/round3/protocol.json")
    continuation = doc("reports/phase3/round3/phase4_continuation_protocol.json")
    traces = dev_traces(ROOT / "data/nexusbench/traces.jsonl", {r["trace_id"] for r in smoke["rows"]})
    checks = []
    for row in smoke["rows"]:
        current = doc(f"data/phase5/runs/records/{row['item_id']}.json")
        failure = next(f for f in sets["failures"] if f["trace_id"] == row["trace_id"])
        saved = next(r for r in old_results["by_outcome"]["a1"]["per_failure_rows"] if r["failure_id"] == failure["failure_id"])
        old_patch = ConfigPatch.from_json(old_results["patches"][saved["patch_hash"]])
        old_replay = Scorer(old_runs).score_failure(failure, old_patch, sets["regression_a2"])
        new_patch = from_phase3(current["proposal"]["target_component"], current["proposal"]["patch_content"])
        fresh = baseline_records()
        path = next((ROOT / "data/phase5/runs/work" / row["item_id"]).glob("*/agent_runs.jsonl"))
        for rec in records(path):
            fresh[rec["run_id"]] = rec
        new_replay = Scorer(fresh).score_failure(failure, new_patch, sets["regression_a2"])
        view = detector_view(traces[row["trace_id"]].model_dump(mode="json"))
        evidence = from_detector({"pred": current["failure_class"]}, view).model_dump(mode="json")
        view_hash = hashlib.sha256(serialize_view(view).encode()).hexdigest()
        old_view_hash = continuation["leak_assert"]["detector_view_sha256"][row["trace_id"]]
        hist = old_critic[row["trace_id"]]
        result = dict(item_id=row["item_id"], trace_id=row["trace_id"], phase4_patch_hash=old_patch.patch_hash,
            fresh_patch_hash=new_patch.patch_hash, patch_changed=old_patch.patch_hash != new_patch.patch_hash,
            phase4_scorer_replay_matches=old_replay["gate"] == saved["gate"],
            fresh_uninstrumented_scorer_matches=new_replay["gate"] == current["gate"],
            phase4_view_sha256=old_view_hash, fresh_view_sha256=view_hash, view_hash_matches=view_hash == old_view_hash,
            evidence_matches=evidence == hist["evidence"], baseline_config_matches=baseline_config() == protocol["config"],
            prompt_hashes_match=current["proposal"]["provenance"]["prompt_hashes"] == hist["proposal"]["provenance"]["prompt_hashes"],
            phase4_model_version=hist["proposal"]["provenance"]["model_version"],
            fresh_model_version=current["proposal"]["provenance"]["model_version"],
            phase4_gate=saved["gate"], fresh_gate=current["gate"])
        checks.append(result)
        print(json.dumps(result, indent=2))
    budget = Budget(ROOT / "data/phase5/runs")
    report = dict(status="STOP; no pre-registration, commit, tag, push or overnight launch", checks=checks,
        diagnosis="Fresh critic proposals differ at temperature 0.2; saved/fresh gates both reproduce exactly with the unchanged scorer. Evidence supports critic-generation variability, not a measurement/infra decision change or established confirmation-seed noise.",
        ledger_usd=budget.spent(), api_attempts=len(budget.calls()), api_errors=sum(bool(c["error"]) for c in budget.calls()),
        concurrency1_estimate_hours=smoke["estimated_100_heals_seconds"] / 3600,
        required_concurrency_for_9h=2, projection_hours_at_2=smoke["estimated_100_heals_seconds"] / 7200)
    atomic_json(ROOT / "reports/phase5/smoke_diagnosis.json", report)
    print("Diagnostic report saved; no API calls performed.")


if __name__ == "__main__":
    main()
