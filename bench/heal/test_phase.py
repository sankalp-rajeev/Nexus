"""Amendment A3: the one-time Phase 4 test scoring (reports/phase4/amendment_a3.md).

    python -m bench.heal.test_phase --evidence             # A3 §2, before the freeze
    python -m bench.heal.test_phase --critic  --env-file F # A3 §3, after the freeze
    python -m bench.heal.test_phase --plan                 # A3 §5 spend estimate
    python -m bench.heal.test_phase --run main --env-file F
    python -m bench.heal.test_phase --run confirm --env-file F
    python -m bench.heal.test_phase --score

Everything here reads the A3 test sets (``reports/phase4/prereg_sets_test.json``).
Every step after ``--evidence`` refuses to start before the dev freeze
(``bench.heal.freeze.assert_frozen``). Test runs go to ``results/heal_runs_test.jsonl``
with their own ledger; the critic's calls go to ``reports/phase4/test/critic_calls.jsonl``.
The two ledgers together stay under ``TEST_CAP_USD``.

Detector evidence uses the frozen Phase 2 detectors on the selected test traces only,
to build ``FailureEvidence``. No Phase 2 metric is computed, written or reported here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from bench.generate import MODELS, SEED
from bench.heal import a2
from bench.heal.baselines import arms as baseline_arms
from bench.heal.config import ConfigPatch
from bench.heal.critic import Proposal
from bench.heal.freeze import FROZEN_TAG, assert_frozen
from bench.heal.harness import STATE_DIR, Harness, RunSpec, RunStore
from bench.heal.score import CONFIRM_SEEDS, PRIMARY, failure_specs
from bench.heal.sets import REPO, TEST_SETS_PATH, load_sets
from services.common.results import provenance, write_result

ARM = "v1_structured"                 # selected on dev (D73)
TEST_CAP_USD = 5.50                   # user decision (D75): critic calls + all test runs
CRITIC_CAP_USD = 0.60                 # sub-cap for the 60 critic proposals (~$0.39 on dev rates)
TEST_DIR = os.path.join(REPO, "reports", "phase4", "test")
EVIDENCE_PATH = os.path.join(TEST_DIR, "evidence.json")
LEAK_PATH = os.path.join(TEST_DIR, "leak_assert.json")
PROPOSALS_PATH = os.path.join(TEST_DIR, f"{ARM}.jsonl")
CRITIC_CALLS = os.path.join(TEST_DIR, "critic_calls.jsonl")
TEST_RUNS_PATH = os.path.join(REPO, "results", "heal_runs_test.jsonl")
TEST_LEDGER = "cost_ledger_test.jsonl"
DEV_RUNS_PATH = os.path.join(REPO, "results", "heal_runs.jsonl")


def test_sets() -> dict[str, Any]:
    return load_sets(TEST_SETS_PATH)


def _raw_traces(trace_ids: set[str]) -> dict[str, dict]:
    from bench.scoring import load_traces
    raw = load_traces(trace_ids)
    if set(raw) != trace_ids:
        raise ValueError(f"missing test traces: {sorted(trace_ids - set(raw))[:3]}")
    return raw


def _views(raw: dict[str, dict]):
    """The critic's view, built as Phase 3 round 3 built it (validated, then dumped)."""
    from nexus_agent.models import CompleteTrace

    from bench.detector_view import detector_view
    return {t: detector_view(CompleteTrace.model_validate(d).model_dump(mode="json"))
            for t, d in raw.items()}


# -- A3 §2: detector evidence --------------------------------------------------------

def build_evidence() -> dict[str, Any]:
    """Frozen Phase 2 detectors -> predicted class -> ``from_detector`` evidence, for the
    selected test failures only. The detectors see the detector view, never the label."""
    from bench.detector_view import detector_view
    from bench.tools import DRIFT_CUSTOMER
    from bench.world import build_world
    from services.critic.detector_adapter import from_detector
    from services.critic.leak_assert import assert_no_evidence_leaks
    from services.detectors import pipeline

    sets = test_sets()
    tids = sorted(f["trace_id"] for f in sets["failures"])
    raw = _raw_traces(set(tids))
    th = pipeline.load_thresholds()
    views = _views(raw)
    pred, evidence = {}, {}
    for t in tids:
        p2_view = detector_view(raw[t])          # as Phase 2 scored it (audit_dev.py)
        if p2_view.trace_id != views[t].trace_id:
            raise ValueError(f"{t}: detector views disagree")
        pred[t] = pipeline.label(pipeline.compute_scores(p2_view), th)
        evidence[t] = from_detector({"pred": pred[t]}, views[t])
    os.makedirs(TEST_DIR, exist_ok=True)
    audit = assert_no_evidence_leaks(
        {t: e for t, e in evidence.items()}, views, Path(LEAK_PATH),
        raw_canaries=tuple(u.canary for u in build_world().users),
        raw_drift_target=DRIFT_CUSTOMER)
    doc = {"note": "A3 §2: FailureEvidence for the critic from the frozen Phase 2 detectors "
                   "(tag phase2-detectors-frozen), test failures only. Not a Phase 2 result: "
                   "no detector metric is computed from it.",
           "thresholds_sha256": hashlib.sha256(
               open(pipeline.THRESHOLDS_PATH, "rb").read()).hexdigest(),
           "sets_selection_sha256": sets["selection_sha256"],
           "leak_assert": {k: audit[k] for k in ("invariant_version", "status",
                                                  "evidence_checked", "evidence_with_leaks")},
           "traces": {t: {"view_id": views[t].trace_id, "detector_type": pred[t],
                          "trace_sha256": hashlib.sha256(
                              json.dumps(raw[t], sort_keys=True).encode()).hexdigest(),
                          "evidence": evidence[t].model_dump(mode="json")
                          if evidence[t] else None} for t in tids}}
    with open(EVIDENCE_PATH, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, indent=1, sort_keys=True)
        fh.write("\n")
    return doc


def load_evidence() -> dict[str, Any]:
    with open(EVIDENCE_PATH, encoding="utf-8") as fh:
        return json.load(fh)


# -- A3 §3: critic proposals ---------------------------------------------------------

def _critic_ledger():
    from services.critic.accounting import CostLedger

    class TestCriticLedger(CostLedger):
        def __init__(self, path, cap, commit):
            super().__init__(path, cap_usd=cap)
            self.lock = threading.RLock()
            self.commit = commit
            self.arm = ARM

        def append(self, row):
            with self.lock:
                if row.get("status") == "reserved":
                    self.check(row["cost_usd"])
                super().append({**row, "arm": self.arm, "git_commit": self.commit,
                                "evidence_mode": "detector", "split": "test"})
    return TestCriticLedger


def critic_spent() -> float:
    from services.critic.accounting import CostLedger
    return CostLedger(CRITIC_CALLS, cap_usd=CRITIC_CAP_USD).spent if os.path.exists(
        CRITIC_CALLS) else 0.0


def generate_proposals(env_file: str | None) -> dict[str, Any]:
    """One v1_structured proposal per test failure, generated as Phase 3 round 3 part B
    generated the dev ones: same ``run_critic`` call, provider, deployment snapshot
    (``baseline_config``) and detector evidence. Resumable: a failure that already has
    a record is skipped; nothing is regenerated."""
    commit = assert_frozen()
    from nexus_agent.models import Alert

    from bench.llm import load_env
    from services.critic.detector_adapter import critic_view
    from services.critic.evidence import FailureEvidence
    from services.critic.graph import run_critic
    from services.critic.llm import DeepSeekProvider
    from services.critic.round2 import Store
    from services.critic.round3_part_b import baseline_config

    sets, ev = test_sets(), load_evidence()
    tids = [f["trace_id"] for f in sets["failures"]]
    labels = {f["trace_id"]: f["fault"] for f in sets["failures"]}
    views = _views(_raw_traces(set(tids)))
    done = set()
    if os.path.exists(PROPOSALS_PATH):
        done = {json.loads(x)["trace_id"] for x in open(PROPOSALS_PATH, encoding="utf-8")
                if x.strip()}
    load_env(env_file or os.path.join(REPO, ".env"))
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise RuntimeError("DEEPSEEK_API_KEY is not set (pass --env-file)")
    ledger = _critic_ledger()(CRITIC_CALLS, CRITIC_CAP_USD, commit)
    provider = DeepSeekProvider(ledger=ledger)
    config = baseline_config()
    n = 0
    for tid in tids:
        if tid in done:
            continue
        e = ev["traces"][tid]
        view = critic_view(views[tid])
        if view.trace_id != e["view_id"]:
            raise ValueError(f"{tid}: view id differs from the frozen evidence")
        before = {r["call_id"] for r in ledger.rows()}
        started = time.perf_counter()
        proposal, valid, applied = None, False, False
        if e["evidence"] is not None:
            evidence = FailureEvidence.model_validate(e["evidence"])
            alert = Alert(trace_id=view.trace_id, agent_name=view.agent_name,
                          failure_type=e["detector_type"])
            proposal = run_critic(alert, Store({view.trace_id: view}),
                                  llm_factory=lambda chosen=provider, **_: chosen,
                                  evidence=evidence, current_config=config,
                                  config={"critic_arm": ARM})
            valid, applied = proposal.valid_without_fallback, proposal.dry_run_applied
        calls = [r for r in ledger.rows() if r["call_id"] not in before]
        if proposal:
            proposal.provenance.cost_usd = sum(c["cost_usd"] for c in calls)
            for field in ("input_tokens", "output_tokens", "latency_ms"):
                vals = [c.get(field) for c in calls]
                setattr(proposal.provenance, field,
                        sum(vals) if all(v is not None for v in vals) else None)
        rec = {"trace_id": tid, "view_id": view.trace_id, "arm": ARM, "split": "test",
               "failure_type": labels[tid], "detector_type": e["detector_type"],
               "evidence_mode": "detector", "evidence": e["evidence"],
               "proposal": proposal.model_dump(mode="json") if proposal else None,
               "c1_valid": valid, "dry_run_applied": applied,
               "wall_latency_ms": (time.perf_counter() - started) * 1000 if proposal else None,
               "call_ids": [c["call_id"] for c in calls], "git_commit": commit}
        with open(PROPOSALS_PATH, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        n += 1
        print(f"[critic] {len(done) + n}/{len(tids)} spend ${ledger.spent:.4f}", flush=True)
    return {"generated": n, "already_done": len(done), "critic_usd": round(ledger.spent, 4)}


def critic_patches(sets) -> tuple[dict[str, ConfigPatch], dict[str, Proposal]]:
    return a2.critic_arm(sets, ARM, PROPOSALS_PATH)


# -- arms and run sets ---------------------------------------------------------------

def arm_patches(sets) -> dict[str, dict[str, ConfigPatch]]:
    noise, generic, _ = baseline_arms(sets)
    out = {"no_patch": noise, "generic": generic}
    if os.path.exists(PROPOSALS_PATH):
        out[ARM] = critic_patches(sets)[0]
    return out


def main_specs(sets) -> dict[str, RunSpec]:
    """Seeds 0-2: no-patch references, generic and critic, on own, held-out and A2
    regression tasks."""
    ss: list[RunSpec] = []
    for patches in arm_patches(sets).values():
        ss += a2.specs(sets, patches)
    return a2.unique(ss)


def confirm_specs(sets, records) -> dict[str, RunSpec]:
    """Seeds 3-5 for every gate-promoted generic and critic patch (A1 outcome)."""
    fx, ss = a2.by_failure(sets), []
    for name, patches in arm_patches(sets).items():
        if name == "no_patch":
            continue
        b = a2.score_arm(sets, records, patches)["by_outcome"][PRIMARY]
        ss += [x for r in b["per_failure_rows"] if r["gate"]["promoted"]
               for x in failure_specs(fx[r["failure_id"]], patches[r["failure_id"]],
                                      a2.reg(sets), CONFIRM_SEEDS)]
    return a2.unique(ss)


# -- A3 §5: spend estimate -----------------------------------------------------------

def _cell(rec_or_spec) -> tuple:
    fam = rec_or_spec.task_id.split("-")[0] if hasattr(rec_or_spec, "task_id") else \
        rec_or_spec["task_id"].split("-")[0]
    env = rec_or_spec.env_fault if hasattr(rec_or_spec, "env_fault") else rec_or_spec["env_fault"]
    base = (rec_or_spec.base_fault == "HALLUCINATION") if hasattr(rec_or_spec, "base_fault") \
        else rec_or_spec["base"] != "clean"
    return fam, env, base


def dev_cost_model() -> dict[tuple, float]:
    """Mean measured $ per DeepSeek run on dev, by (family, env fault, hallucination base)."""
    tot, n = defaultdict(float), Counter()
    for rec in RunStore(DEV_RUNS_PATH).by_id.values():
        if rec["provider"] != "deepseek" or rec["status"] != "ok":
            continue
        k = _cell(rec)
        tot[k] += rec["cost_usd"]
        n[k] += 1
    return {k: tot[k] / n[k] for k in n}


def estimate(ss: dict[str, RunSpec], done: set[str], model: dict[tuple, float]
             ) -> dict[str, Any]:
    usd, runs = 0.0, Counter()
    fallback = max(model.values())
    for s in ss.values():
        if s.run_id in done:
            continue
        runs[s.provider] += 1
        if s.provider == "deepseek":
            usd += model.get(_cell(s), fallback)
    return {"to_run": dict(runs), "est_deepseek_usd": round(usd, 3),
            "est_qwen_hours_2_workers": round(runs["ollama"] * 4.4 / 3600, 1)}


def plan() -> dict[str, Any]:
    sets = test_sets()
    model = dev_cost_model()
    done = set(RunStore(TEST_RUNS_PATH).by_id) if os.path.exists(TEST_RUNS_PATH) else set()
    noise, generic, inapp = baseline_arms(sets)
    out: dict[str, Any] = {"cap_usd": TEST_CAP_USD, "critic_spent_usd": round(critic_spent(), 4)}
    ref = a2.unique(a2.specs(sets, noise))
    gen = {k: v for k, v in a2.unique(a2.specs(sets, generic)).items() if k not in ref}
    out["no_patch_s0_2"] = estimate(ref, done, model)
    out["generic_s0_2"] = estimate(gen, done, model)
    out["generic_inapplicable"] = len(inapp)
    fx = a2.by_failure(sets)
    gconf = a2.unique([x for k, p in generic.items()
                       for x in failure_specs(fx[k], p, a2.reg(sets), CONFIRM_SEEDS)])
    out["generic_confirm_worst_case"] = estimate(gconf, done, model)
    if os.path.exists(PROPOSALS_PATH):
        patches, props = critic_patches(sets)
        crit = {k: v for k, v in a2.unique(a2.specs(sets, patches)).items()
                if k not in ref and k not in gen}
        out["critic_patches"] = len(patches)
        out["critic_no_patch"] = dict(Counter(p.reason for p in props.values()
                                              if p.status != "patch"))
        out["critic_s0_2"] = estimate(crit, done, model)
        cconf = a2.unique([x for k, p in patches.items()
                           for x in failure_specs(fx[k], p, a2.reg(sets), CONFIRM_SEEDS)])
        out["critic_confirm_worst_case"] = estimate(cconf, done, model)
    else:
        # Before proposals exist: dev-scaled ($ per patch failure on dev, v1_structured).
        dev = load_sets()
        dp, _ = a2.critic_arm(dev, ARM)
        recs = RunStore(DEV_RUNS_PATH).by_id
        dref = {s.run_id for s in a2.specs(dev, {k: ConfigPatch.none() for k in dp})}
        dcrit = [s for s in a2.unique(a2.specs(dev, dp)).values() if s.run_id not in dref]
        usd = sum(recs[s.run_id]["cost_usd"] for s in dcrit if s.run_id in recs)
        out["critic_s0_2"] = {"est_deepseek_usd": round(usd * 60 / len(dev["failures"]), 3),
                              "basis": "dev v1_structured runs, scaled to 60 failures"}
        out["critic_proposals_est_usd"] = round(60 * a2.CRITIC_USD_PER_PROPOSAL[ARM], 3)
        out["critic_confirm_worst_case"] = {"est_deepseek_usd": out["critic_s0_2"][
            "est_deepseek_usd"], "basis": "every patch promoted"}
    keys = [k for k in out if isinstance(out[k], dict) and "est_deepseek_usd" in out[k]]
    expected = sum(out[k]["est_deepseek_usd"] for k in keys if "confirm" not in k)
    worst = sum(out[k]["est_deepseek_usd"] for k in keys)
    crit_usd = out["critic_spent_usd"] or out.get("critic_proposals_est_usd", 0.0)
    out["est_total_expected_usd"] = round(expected + crit_usd
                                          + 0.66 * sum(out[k]["est_deepseek_usd"]
                                                       for k in keys if "confirm" in k), 2)
    out["est_total_worst_case_usd"] = round(worst + crit_usd, 2)
    out["note"] = ("expected = s0-2 runs + critic + confirmations at the dev promotion rate "
                   "(29/44 ~ 0.66); worst case = every applicable patch promoted")
    return out


# -- runs ----------------------------------------------------------------------------

def run(which: str, env_file: str | None) -> dict[str, Any]:
    assert_frozen()
    sets = test_sets()
    if ARM not in arm_patches(sets):
        raise RuntimeError("critic proposals are missing; run --critic first")
    cap = TEST_CAP_USD - critic_spent()
    h = Harness(split="test", runs_path=TEST_RUNS_PATH, state_dir=STATE_DIR, cap_usd=cap,
                ledger_file=TEST_LEDGER, env_file=env_file)
    ss = main_specs(sets) if which == "main" else confirm_specs(sets, h.records())
    stats = h.run_all(ss.values())
    stats["ledger_runs_usd"] = round(h.ledger.total(), 4)
    stats["critic_usd"] = round(critic_spent(), 4)
    return stats


# -- scoring -------------------------------------------------------------------------

def score() -> dict[str, Any]:
    tag_commit = assert_frozen()
    sets = test_sets()
    records = RunStore(TEST_RUNS_PATH).by_id
    patches = arm_patches(sets)
    _, props = critic_patches(sets)
    prov = provenance(provider="deepseek+ollama",
                      model=f"{MODELS['deepseek']}+{MODELS['ollama']}", mock=False, seed=SEED)
    common = {"amendment": "A3 (test scoring; protocol A1+A2+A3)", "split": "test",
              "frozen_tag": FROZEN_TAG, "frozen_commit": tag_commit,
              "regression_set": a2.REG_KEY, "regression": a2.reg(sets),
              "seeds": list(a2.SEEDS), "confirm_seeds": list(CONFIRM_SEEDS),
              "primary_outcome": PRIMARY, "cap_usd_test": TEST_CAP_USD}
    out = {}
    names = {"no_patch": ("heal_nopatch_test.json", "no patch (H5)"),
             "generic": ("heal_generic_test.json", "generic templates"),
             ARM: (f"heal_critic_{ARM}_test.json", f"critic {ARM} (detector evidence)")}
    for arm, (fname, label) in names.items():
        s = a2.score_arm(sets, records, patches[arm], props if arm == ARM else None)
        if arm == ARM:
            s["proposals"] = {k: {"status": p.status, "reason": p.reason,
                                  "patch_hash": p.patch.patch_hash if p.patch else None}
                              for k, p in props.items()}
        if arm == "generic":
            s["inapplicable"] = baseline_arms(sets)[2]
        write_result(f"A3 test {arm}", fname, {**common, "arm": label, **s},
                     provenance_info=prov, summary=a2._line(f"TEST {label}", s))
        out[arm] = s
    spend = {"critic_usd": round(critic_spent(), 4),
             "runs_usd": round(sum(r["cost_usd"] for r in records.values()), 4)}
    spend["total_usd"] = round(spend["critic_usd"] + spend["runs_usd"], 4)
    out["spend"] = spend
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--evidence", action="store_true")
    g.add_argument("--critic", action="store_true")
    g.add_argument("--plan", action="store_true")
    g.add_argument("--run", choices=["main", "confirm"])
    g.add_argument("--score", action="store_true")
    ap.add_argument("--env-file", default=None)
    args = ap.parse_args()
    if args.evidence:
        doc = build_evidence()
        print({"traces": len(doc["traces"]),
               "with_evidence": sum(v["evidence"] is not None for v in doc["traces"].values())})
    elif args.critic:
        print(generate_proposals(args.env_file))
    elif args.plan:
        print(json.dumps(plan(), indent=1))
    elif args.run:
        print(args.run, run(args.run, args.env_file))
    else:
        print(json.dumps(score()["spend"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
