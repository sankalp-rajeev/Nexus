"""C1/C2/C5 only. DEV labels, full DEV traces, real model, fake trace store.

Run: python -m services.critic.experiments --preflight
     python -m services.critic.experiments
No TEST records are deserialized. No task is replayed and no repair is scored.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from scipy.stats import beta

# Allow module invocation without modifying the SDK installation or shared files.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "sdk") not in sys.path:
    sys.path.insert(0, str(ROOT / "sdk"))

from nexus_agent.models import Alert  # noqa: E402
from services.critic.accounting import CostLedger  # noqa: E402
from services.critic.dev_adapter import (  # noqa: E402
    CLASSES, current_config, dev_labels, dev_traces, evidence_from_dev,
)
from services.critic.graph import build_prompt, run_critic  # noqa: E402
from services.critic.llm import TEMPERATURE, DeepSeekProvider, OllamaProvider  # noqa: E402
from services.critic.proposal import PROMPT_VERSION  # noqa: E402

SEED = 20261110
OUT = ROOT / "results" / "critic_dev"


def interval(successes, total):
    if not 0 <= successes <= total:
        raise ValueError("Invalid binomial counts")
    return {"successes": successes, "total": total,
            "rate": successes / total if total else None,
            "ci95_clopper_pearson": ([float(beta.ppf(.025, successes, total-successes+1)) if successes else 0.0,
                                      float(beta.ppf(.975, successes+1, total-successes)) if successes < total else 1.0]
                                     if total else [None, None])}


def select_labels(rows):
    selected = []
    for failure_type in CLASSES:
        buckets = defaultdict(list)
        for row in rows:
            if row["label"] == failure_type:
                buckets[(row["provider"], row["model"])].append(row)
        rng = random.Random(f"{SEED}:{failure_type}")
        for pool in buckets.values():
            rng.shuffle(pool)
        sample, used_tasks = [], set()
        # Prefer distinct tasks, round-robin over all available source models.
        for unique in (True, False):
            while len(sample) < 12:
                before = len(sample)
                for key in sorted(buckets):
                    pool = buckets[key]
                    candidate = next((r for r in pool if not unique or r["task_id"] not in used_tasks), None)
                    if candidate is not None:
                        sample.append(candidate)
                        used_tasks.add(candidate["task_id"])
                        pool.remove(candidate)
                    if len(sample) == 12:
                        break
                if len(sample) == before:
                    break
        if len(sample) != 12:
            raise ValueError(f"Insufficient DEV failures for {failure_type}")
        selected.extend(sample)
    return selected


class FakeTraceStore:
    def __init__(self, traces, labels):
        self.traces = traces
        self.labels = {r["trace_id"]: r for r in labels}
        self.attempts = []
        self.stored = []

    def load_trace(self, trace_id):
        return self.traces[trace_id]

    def record_attempt(self, proposal):
        self.attempts.append(proposal)

    def write_patch(self, proposal):
        if proposal.provenance.source != "llm" or not proposal.dry_run_applied:
            raise ValueError("Unchecked proposal reached fake store")
        self.stored.append(proposal)


def git(*args):
    return subprocess.check_output(["git", "-c", f"safe.directory={ROOT.as_posix()}", *args],
                                   cwd=ROOT, text=True).strip()


def summarize(rows):
    def counts(items):
        valid = [r for r in items if r["proposal"]["valid_without_fallback"]]
        return {"C1": interval(len(valid), len(items)),
                "C2": interval(sum(r["proposal"]["dry_run_applied"] for r in valid), len(valid))}
    result = {"overall": counts(rows), "per_class": {}, "per_source_model": {}}
    for ft in CLASSES:
        result["per_class"][ft] = counts([r for r in rows if r["failure_type"] == ft])
    for source in sorted({r["source_model"] for r in rows}):
        subset = [r for r in rows if r["source_model"] == source]
        result["per_source_model"][source] = {"overall": counts(subset), "per_class": {
            ft: counts([r for r in subset if r["failure_type"] == ft]) for ft in CLASSES}}
    return result


def stability(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row["trace_id"]].append(row)
    outcomes = []
    for trace_id, trials in groups.items():
        valid = len(trials) == 3 and all(r["proposal"]["valid_without_fallback"] for r in trials)
        pairs = [(r["proposal"]["patch_type"], r["proposal"]["target_component"]) for r in trials]
        outcomes.append({"trace_id": trace_id, "failure_type": trials[0]["failure_type"],
                         "source_model": trials[0]["source_model"], "pairs": pairs,
                         "type_stable": valid and len({p[0] for p in pairs}) == 1,
                         "key_stable": valid and len({p[1] for p in pairs}) == 1,
                         "joint_stable": valid and len(set(pairs)) == 1})
    def counts(items):
        return {metric: interval(sum(r[metric] for r in items), len(items))
                for metric in ("type_stable", "key_stable", "joint_stable")}
    return {"overall": counts(outcomes), "per_class": {
        ft: counts([r for r in outcomes if r["failure_type"] == ft]) for ft in CLASSES},
        "per_source_model": {source: counts([r for r in outcomes if r["source_model"] == source])
                             for source in sorted({r["source_model"] for r in outcomes})},
        "traces": outcomes}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--provider", choices=["ollama", "deepseek"], default="ollama")
    parser.add_argument("--env-file")
    args = parser.parse_args()
    if git("branch", "--show-current") != "phase-3-critic" or ROOT.name != "nexus-phase3":
        raise RuntimeError("Wrong branch or worktree")
    subprocess.run(["git", "-c", f"safe.directory={ROOT.as_posix()}", "merge-base", "--is-ancestor",
                    "phase-1-nexusbench", "HEAD"], cwd=ROOT, check=True)
    rows = list(dev_labels(ROOT / "data/nexusbench/labels.csv"))
    labels = select_labels(rows)
    traces = dev_traces(ROOT / "data/nexusbench/traces.jsonl", {r["trace_id"] for r in labels})
    configs = {r["trace_id"]: current_config(r) for r in labels}
    evidences = {r["trace_id"]: evidence_from_dev(r, traces[r["trace_id"]], allow_oracle=True) for r in labels}
    prompt_sizes = [len(build_prompt({"trace": traces[r["trace_id"]], "current_config": configs[r["trace_id"]],
                                     "evidence": evidences[r["trace_id"]]})) for r in labels]
    print(json.dumps({"selected": len(labels), "per_class": {ft: sum(r["label"] == ft for r in labels) for ft in CLASSES},
                      "max_prompt_characters": max(prompt_sizes), "min_prompt_characters": min(prompt_sizes)}), flush=True)
    if args.preflight:
        return
    dirty = git("status", "--porcelain", "--", "services/critic", "tests/unit/critic")
    if dirty:
        raise RuntimeError("Commit implementation before generating evidence")
    OUT.mkdir(parents=True, exist_ok=True)
    trials_path = OUT / "trials.jsonl"
    if trials_path.exists():
        raise RuntimeError("Refusing to overwrite an existing run; preserve all calls and trials")
    os.environ["NEXUS_LLM"] = args.provider
    if args.env_file:
        from bench.llm import load_env
        load_env(args.env_file)
    ledger = CostLedger(OUT / "calls.jsonl")
    ledger.check()
    provider = (OllamaProvider if args.provider == "ollama" else DeepSeekProvider)(ledger=ledger)
    provenance = {"provider": provider.provider, "model": provider.model, "model_version": provider.version,
                  "temperature": TEMPERATURE, "prompt_version": PROMPT_VERSION, "mock": False,
                  "seed": SEED, "sampling_seed": None, "git_commit": git("rev-parse", "HEAD"),
                  "date_utc": datetime.now(timezone.utc).isoformat(), "dataset": "NexusBench DEV only"}
    manifest = [{k: r[k] for k in ("trace_id", "task_id", "label", "provider", "model")} for r in labels]
    (OUT / "selection.json").write_text(json.dumps({"provenance": provenance, "selection": manifest,
                        "selection_sha256": hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()}, indent=2), encoding="utf-8")
    store = FakeTraceStore(traces, labels)
    trials = []
    def run(row, experiment, rep):
        tid = row["trace_id"]
        alert = Alert(trace_id=tid, agent_name=traces[tid].agent_name, failure_type=row["label"])
        p = run_critic(alert, store, llm_factory=lambda **_: provider,
                       current_config=configs[tid], evidence=evidences[tid])
        if p.provenance.mock:
            raise RuntimeError("Mock output cannot enter experiment results")
        provenance["model_version"] = p.provenance.model_version
        record = {"experiment": experiment, "repeat": rep, "trace_id": tid,
                  "task_id": row["task_id"], "failure_type": row["label"],
                  "source_model": f'{row["provider"]}/{row["model"]}',
                  "provenance": provenance, "date_utc": datetime.now(timezone.utc).isoformat(),
                  "config_keys": list(configs[tid]), "proposal": p.model_dump(mode="json")}
        with trials_path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        trials.append(record)
        print(f"{experiment} {len(trials):02d}/90 {row['label']} {tid} "
              f"source={p.provenance.source} valid={p.valid_without_fallback} apply={p.dry_run_applied} "
              f"tokens={p.provenance.input_tokens}+{p.provenance.output_tokens} cost=${p.provenance.cost_usd:.6f}", flush=True)
    for row in labels:
        run(row, "C1_C2", 0)
    # Two traces per class. All C5 calls are new, uncached, unseeded samples.
    stable_labels = [r for ft in CLASSES for r in [x for x in labels if x["label"] == ft][:2]]
    for rep in range(3):
        for row in stable_labels:
            run(row, "C5", rep)
    metrics = summarize([r for r in trials if r["experiment"] == "C1_C2"])
    for experiment in ("C1", "C2"):
        content = {"experiment_id": experiment, "provenance": provenance, "total_spend_usd": ledger.spent,
                   "definition": ("Schema + unchanged validator pass, source=llm, no fallback; applicability measured separately by C2."
                                  if experiment == "C1" else "Clean copy dry run among C1-valid model proposals; rejected candidates are audited, never stored."),
                   "overall": metrics["overall"][experiment],
                   "per_class": {k: v[experiment] for k, v in metrics["per_class"].items()},
                   "per_source_model": {k: {"overall": v["overall"][experiment],
                       "per_class": {c: m[experiment] for c, m in v["per_class"].items()}}
                       for k, v in metrics["per_source_model"].items()}}
        (OUT / f"{experiment.lower()}.json").write_text(json.dumps(content, indent=2), encoding="utf-8")
    (OUT / "c5.json").write_text(json.dumps({"experiment_id": "C5", "provenance": provenance,
           "definition": "A trace succeeds only when all 3 fresh outputs are C1-valid and their type/key agree; fallback is failure.",
           "total_spend_usd": ledger.spent, **stability([r for r in trials if r["experiment"] == "C5"])}, indent=2), encoding="utf-8")
    print(f"Complete: {len(trials)} trials, {len(ledger.rows())} calls, ${ledger.spent:.6f}", flush=True)


if __name__ == "__main__":
    main()
