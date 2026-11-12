"""DEV-only orchestration around unchanged Phase 4 functions."""
import json
from pathlib import Path
import sys
import subprocess
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "sdk"))

import portalocker
from bench.detector_view import detector_view
from bench.heal.config import ConfigPatch
from bench.heal.critic import _one
from bench.heal.harness import Harness
from bench.heal.score import Scorer, SEEDS, failure_specs
from bench.heal.sets import assert_dev
from bench.llm import LLMClient, load_env
from nexus_agent.models import Alert
from services.critic.accounting import CostLedger
from services.critic.detector_adapter import critic_view, from_detector
from services.critic.dev_adapter import dev_labels, dev_traces
from services.critic.graph import run_critic
from services.critic.llm import DeepSeekProvider
from services.critic.round2 import Store
from services.critic.round3_part_b import baseline_config
from services.detectors import pipeline as detector
from scripts.phase5.measurement import Budget, BudgetExceeded, Measurement, atomic_json, observed_client


def completed(path, item):
    if not path.exists():
        return None
    rec = json.loads(path.read_text(encoding="utf-8"))
    if not rec.get("complete") or rec.get("trace_id") != item["trace_id"] or rec.get("item_id") != item["item_id"]:
        raise ValueError("Existing heal record has incomplete or inconsistent identity")
    return rec


def baseline_records():
    none = ConfigPatch.none().patch_hash
    with (ROOT / "results/heal_runs.jsonl").open(encoding="utf-8") as stream:
        return {r["run_id"]: r for line in stream if line.strip()
                if (r := json.loads(line))["patch_hash"] == none and r["provider"] == "deepseek"}


def execute(item, root, *, critic_factory=None):
    root = Path(root)
    record_path = root / "records" / f"{item['item_id']}.json"
    (root / "locks").mkdir(parents=True, exist_ok=True)
    with portalocker.Lock(str(root / "locks" / f"{item['item_id']}.lock"), timeout=5):
        previous = completed(record_path, item)
        if previous is not None:
            return previous
        budget = Budget(root)
        measure = Measurement(item["item_id"], item["trace_id"])
        rec = measure.record
        attempt = root / "work" / item["item_id"] / uuid4().hex
        rec.update(attempt_id=attempt.name, fault=item["fault"], task_id=item["task_id"],
                   gate_decision="not_evaluated", baseline_reused=0,
                   critic_arm="v1_structured", seed=list(SEEDS), split="dev")
        rec["git_commit"] = subprocess.check_output(["git", "-c", f"safe.directory={ROOT.as_posix()}", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        rec["frozen_reference"] = "phase4-test-scored"
        try:
            load_env(str(ROOT / ".env"))
            allowed = {r["trace_id"]: r for r in dev_labels(ROOT / "data/nexusbench/labels.csv")}
            label = allowed.get(item["trace_id"])
            if label is None or label["provider"] != "deepseek" or label["label"] != label["fault"] or label["label"] == "NORMAL":
                raise ValueError("Only DEV DeepSeek effective failures are permitted")
            if any(item[k] != label[k] for k in ("task_id", "fault", "provider")):
                raise ValueError("Manifest item differs from the authoritative DEV row")
            assert_dev([item["task_id"], *item["heldout"], *item["regression"]])
            raw = dev_traces(ROOT / "data/nexusbench/traces.jsonl", {item["trace_id"]})[item["trace_id"]]
            with measure.stage("detect"):
                view = detector_view(raw.model_dump(mode="json"))
                scores = detector.compute_scores(view)
            with measure.stage("classify"):
                predicted = detector.label(scores, detector.load_thresholds())
                evidence = from_detector({"pred": predicted}, view)
            rec["failure_class"] = predicted
            rec["critic_failure_class"] = None
            proposal = None
            with measure.stage("critic_call"):
                if evidence is not None:
                    attempt.mkdir(parents=True, exist_ok=True)
                    ledger = CostLedger(attempt / "critic_calls.jsonl", cap_usd=budget.cap)
                    with observed_client(budget, item["item_id"], 120) as http:
                        provider = (critic_factory(ledger=ledger) if critic_factory is not None
                                    else DeepSeekProvider(ledger=ledger, client=http))
                        visible = critic_view(view)
                        proposal = run_critic(Alert(trace_id=visible.trace_id, agent_name=visible.agent_name,
                            failure_type=predicted), Store({visible.trace_id: visible}),
                            llm_factory=lambda **kw: provider, current_config=baseline_config(),
                            evidence=evidence, config={"critic_arm": "v1_structured"})
                if budget.stopped():
                    raise BudgetExceeded("stopped: cap reached")
            if proposal is None:
                rec.update(status="ok", gate_decision="rejected", outcome=False, reason="detector predicted NORMAL")
            else:
                rec["critic_failure_class"] = proposal.diagnosed_failure_type.value if proposal.diagnosed_failure_type else None
                exported = dict(trace_id=item["trace_id"], proposal=proposal.model_dump(mode="json"),
                    c1_valid=proposal.valid_without_fallback, dry_run_applied=proposal.dry_run_applied)
                adapted = _one(exported, "v1_structured", item["fault"])
                rec["proposal_status"] = adapted.status
                rec["proposal"] = exported["proposal"]
                if adapted.status != "patch":
                    rec.update(status="ok", gate_decision="rejected", outcome=False, reason=adapted.reason)
                else:
                    rec["patch_hash"] = adapted.patch.patch_hash
                    rec.update(_evaluate(item, adapted.patch, attempt, budget, measure))
        except BaseException as exc:
            # Store only exception class names: messages can contain credentials/bodies.
            capped = isinstance(exc, BudgetExceeded) or budget.stopped()
            rec.update(status="capped" if capped else "error", error=type(exc).__name__,
                       reason="stopped: cap reached" if capped else "heal failed; retained in denominator",
                       gate_decision="not_evaluated", outcome=None)
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
        final = measure.finish(budget)
        atomic_json(record_path, final)
        return final


def _evaluate(item, patch, attempt, budget, measure):
    # Baseline outcomes are the unchanged Phase 4 seed-0..2 no-patch references.
    # Patched task executions are fresh on each heal; no Phase 4 patch result is reused.
    harness = Harness(runs_path=str(attempt / "agent_runs.jsonl"), state_dir=str(attempt / "state"),
                      cap_usd=budget.cap, workers={"deepseek": 1}, split="dev")
    client = LLMClient("deepseek", "deepseek-flash", ledger=harness.ledger, cache=harness.cache)
    client._http.close()
    client._http = observed_client(budget, item["item_id"], 90)
    harness._clients["deepseek"] = client
    refs = baseline_records()
    all_specs = failure_specs(item, patch, item["regression"])
    no_specs = failure_specs(item, ConfigPatch.none(), item["regression"])
    groups = (
        ("gate_repair", [s for s in all_specs if s.task_id == item["task_id"] and s.env_fault != "NONE"]),
        ("gate_heldout", [s for s in [*all_specs, *no_specs] if s.task_id in item["heldout"] and s.env_fault != "NONE"]),
        ("gate_regression", [s for s in [*all_specs, *no_specs] if s.env_fault == "NONE"]),
    )
    try:
        for stage, specs in groups:
            with measure.stage(stage):
                for spec in specs:
                    if harness.store.check(spec, spec.intended_hash()):
                        continue
                    baseline = refs.get(spec.run_id)
                    if baseline is not None:
                        harness.store.by_id[spec.run_id] = baseline
                        measure.record["baseline_reused"] += 1
                    else:
                        harness.store.add(harness.execute(spec))
                    if budget.stopped():
                        raise BudgetExceeded("stopped: cap reached")
                # Include the unchanged per-task outcome calculations in each
                # stage; the final decision still comes from score_failure().
                scorer = Scorer(harness.records())
                if stage == "gate_repair":
                    scorer.task(patch, item["fault"], item["fault"], item["task_id"], "deepseek", SEEDS, "a1")
                else:
                    tasks = item["heldout"] if stage == "gate_heldout" else item["regression"]
                    env = item["fault"] if stage == "gate_heldout" else "NONE"
                    for candidate in (patch, ConfigPatch.none()):
                        for task in tasks:
                            scorer.task(candidate, item["fault"], env, task, "deepseek", SEEDS, "a1")
        scorer = Scorer(harness.records())
        result = scorer.score_failure(item, patch, item["regression"])
        errors = sum(r["status"] != "ok" for r in harness.records().values())
        return dict(status="ok" if not errors else "agent_errors", outcome=result["gate"]["check1_own_task"],
                    gate_decision="promoted" if result["gate"]["promoted"] else "rejected",
                    gate=result["gate"], own_runs=result["own_runs"], agent_run_errors=errors,
                    actor_runs=len(harness.records()))
    finally:
        client._http.close()
