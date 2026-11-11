"""Before/after and C4; oracle evidence (dev labels); no C3 or task replay."""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "sdk") not in sys.path:
    sys.path.insert(0, str(ROOT / "sdk"))

from nexus_agent.models import Alert  # noqa: E402
from services.critic.accounting import BudgetExceeded  # noqa: E402
from services.critic.dev_adapter import CLASSES, current_config, dev_labels, dev_traces, evidence_from_dev  # noqa: E402
from services.critic.experiments import git, interval  # noqa: E402
from services.critic.graph import run_critic  # noqa: E402
from services.critic.llm import DeepSeekProvider, OllamaProvider, ProviderError  # noqa: E402
from services.critic.registry import ConfigRegistry  # noqa: E402
from services.critic.round2_legacy import OriginalCritic  # noqa: E402
from services.critic.round2_providers import GeminiStructured, LABEL, OriginalDeepSeek, Round2Ledger  # noqa: E402
from services.critic.round2_specificity import (  # noqa: E402
    COSINE_THRESHOLD, EMBED_MODEL, EMBED_REVISION, MiniLMEmbeddings, distinctness, evidence_anchors, grounding,
)

OUT = ROOT / "results/critic_dev/round2"
ARMS = ("old_deepseek", "new_deepseek", "new_gemini", "new_qwen")


class Store:
    def __init__(self, traces):
        self.traces = traces
        self.proposals = []

    def load_trace(self, trace_id):
        return self.traces[trace_id]

    def write_patch(self, proposal):
        self.proposals.append(proposal)  # fake sink, including original critic's unchecked proposals

    def record_attempt(self, proposal):
        pass


def load_selection():
    selected = json.loads((ROOT / "results/critic_dev/selection.json").read_text(encoding="utf-8"))
    ids = [r["trace_id"] for r in selected["selection"]]
    if len(ids) != 60 or len(set(ids)) != 60:
        raise ValueError("Expected the exact recorded 60 DEV traces")
    dev = {r["trace_id"]: r for r in dev_labels(ROOT / "data/nexusbench/labels.csv") if r["trace_id"] in set(ids)}
    if set(dev) != set(ids):
        raise ValueError("Selection is no longer entirely in DEV")
    rows = [dev[tid] for tid in ids]
    for original, row in zip(selected["selection"], rows):
        if any(original[key] != row[key] for key in ("trace_id", "task_id", "label", "provider", "model")):
            raise ValueError("Selected DEV labels changed; freeze this round before regeneration")
    traces = dev_traces(ROOT / "data/nexusbench/traces.jsonl", set(ids))
    evidence = {r["trace_id"]: evidence_from_dev(r, traces[r["trace_id"]], allow_oracle=True) for r in rows}
    return selected, rows, traces, evidence


def summarize_arm(records, vectors):
    def metrics(subset):
        indices = [i for i, r in enumerate(records) if r in subset]
        valid = [r for r in subset if r["c1_valid"]]
        reasons = collections.Counter(reason for r in subset for reason in r["validator_failures"])
        texts = [r["proposal"]["patch_content"] for r in subset]
        distinct = distinctness(texts, vectors[indices])
        llm_indices = [i for i in indices if records[i]["source"] == "llm"]
        return {
            "trace_ids": [r["trace_id"] for r in subset],
            "completed": len(subset), "C1": interval(len(valid), len(subset)),
            "C2": interval(sum(r["dry_run_applied"] for r in valid), len(valid)),
            "fallback": interval(sum(r["source"] == "fallback" for r in subset), len(subset)),
            "validator_failure_reasons": dict(reasons),
            "specificity_all_sources": distinct,
            "specificity_llm_only": distinctness([records[i]["proposal"]["patch_content"] for i in llm_indices], vectors[llm_indices]),
            "grounding_patch_content": interval(sum(r["grounding"]["grounded"] for r in subset), len(subset)),
            "grounding_content_and_explanation": interval(sum(r["grounding_with_explanation"]["grounded"] for r in subset), len(subset)),
            "grounding_identifiers_only": interval(sum(bool({"identifier", "span_or_step"} & r["grounding"]["matches"].keys()) for r in subset), len(subset)),
            "latency_ms": {"p50": float(np.percentile([r["wall_latency_ms"] for r in subset], 50)),
                           "p90": float(np.percentile([r["wall_latency_ms"] for r in subset], 90))} if subset else None,
            "total_cost_usd": sum(r["cost_usd"] for r in subset),
            "cost_per_proposal_usd": sum(r["cost_usd"] for r in subset)/len(subset) if subset else None,
        }
    return {"overall": metrics(records), "per_class": {ft: metrics([r for r in records if r["failure_type"] == ft]) for ft in CLASSES},
            "per_source_model": {source: metrics([r for r in records if r["source_model"] == source])
                                 for source in sorted({r["source_model"] for r in records})}}


def analyze(protocol):
    embedder = MiniLMEmbeddings()
    analysis = {"git_commit": git("rev-parse", "HEAD"), "date_utc": datetime.now(timezone.utc).isoformat(),
                "text_encoding": "utf-8"}
    results = {"evidence_label": LABEL, "protocol": protocol, "analysis": analysis, "arms": {}}
    for arm in ARMS:
        path = OUT / f"{arm}.jsonl"
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
        texts = [r["proposal"]["patch_content"] for r in records]
        vectors, chunks = embedder.encode(texts)
        status_path = OUT / f"{arm}_status.json"
        status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {"status": "not_run"}
        results["arms"][arm] = {"evidence_label": LABEL, "status": status,
                                "embedding_chunks_per_patch": chunks, "trace_order": [r["trace_id"] for r in records],
                                **summarize_arm(records, vectors)}
        if records:
            (OUT / f"{arm}_embeddings.json").write_text(json.dumps({
                "evidence_label": LABEL, "implementation_commit": protocol["implementation_commit"],
                "analysis_commit": analysis["git_commit"], "date_utc": analysis["date_utc"],
                "model": EMBED_MODEL, "revision": EMBED_REVISION,
                "trace_ids": [r["trace_id"] for r in records], "vectors": vectors.tolist(),
            }), encoding="utf-8")
    ledger = Round2Ledger(OUT / "calls.jsonl", git_commit=protocol["implementation_commit"])
    calls = ledger.rows()
    results["spend"] = {"cap_usd": 1.0, "accounted_usd": ledger.spent,
                         "generation_calls": len(calls), "unsettled_reservations": sum(r.get("status") == "reserved" for r in calls),
                         "known_input_tokens": sum(r.get("input_tokens") or 0 for r in calls),
                         "known_output_tokens": sum(r.get("output_tokens") or 0 for r in calls),
                         "unknown_usage_calls": sum(r.get("input_tokens") is None for r in calls),
                         "by_arm": {arm: sum(r["cost_usd"] for r in calls if r["arm"] == arm)
                                    for arm in sorted(set(ARMS) | {r["arm"] for r in calls})},
                         "provider_versions": sorted({r.get("model_version", r.get("model", "unknown")) for r in calls if r.get("status") != "reserved"})}
    (OUT / "summary.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps({"summary": {arm: {k: v["overall"][k] for k in ("C1", "C2", "fallback", "grounding_patch_content", "latency_ms", "cost_per_proposal_usd")}
                                   for arm, v in results["arms"].items()}, "spend": results["spend"]}, indent=2), flush=True)
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--analyze-only", action="store_true")
    parser.add_argument("--env-file", default="C:/Umich/Projects/Nexus/.env")
    args = parser.parse_args()
    if ROOT.name != "nexus-phase3" or git("branch", "--show-current") != "phase-3-critic":
        raise RuntimeError("Wrong branch/worktree")
    if args.analyze_only:
        analyze(json.loads((OUT / "protocol.json").read_text(encoding="utf-8")))
        return
    selected, rows, traces, evidence = load_selection()
    legacy = OriginalCritic()
    if args.preflight:
        embedder = MiniLMEmbeddings()
        vectors, _ = embedder.encode(["Deterministic local embedding preflight."])
        print(json.dumps({"evidence_label": LABEL, "selection_size": len(rows), "selection_sha256": selected["selection_sha256"],
                          "original_source_sha256": legacy.hashes, "embedding_dimension": vectors.shape[1]}))
        return
    if git("status", "--porcelain", "--", "services/critic", "tests/unit/critic"):
        raise RuntimeError("Commit implementation before generation")
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / "protocol.json").exists():
        raise RuntimeError("Refusing to overwrite round 2 generation records")
    from bench.llm import load_env
    load_env(args.env_file)
    os.environ["NEXUS_LLM"] = "deepseek"
    protocol = {"evidence_label": LABEL, "implementation_commit": git("rev-parse", "HEAD"),
                "original_commit": git("rev-parse", "phase-1-nexusbench"), "original_source_sha256": legacy.hashes,
                "date_utc": datetime.now(timezone.utc).isoformat(), "selection_sha256": selected["selection_sha256"],
                "trace_ids": [r["trace_id"] for r in rows],
                "trace_sha256": {tid: hashlib.sha256(t.model_dump_json().encode()).hexdigest() for tid, t in traces.items()},
                "temperature": .2, "max_output_tokens": 800, "cap_usd": 1.0,
                "provider_thinking": {"deepseek": "disabled", "gemini": "MINIMAL"},
                "gemini_billing_confirmation": "User confirmed billing working for this round",
                "context_bleed_regeneration_pending": True, "grounding_scope": "patch_content only; literal boundary match",
                "anchor_rules": "span/step, observed tool_name, fictional-world names present in supporting text, observed IDs, exact prose outputs 12-160 chars or numeric outputs 3-40 chars; no gold answers",
                "normalization": "NFKC, JSON key canonicalization when applicable, casefold, whitespace collapse; preserve values and IDs",
                "embedding": {"model": EMBED_MODEL, "revision": EMBED_REVISION, "cosine_threshold": COSINE_THRESHOLD,
                              "pooling": "L2 normalized token-count-weighted mean of nonoverlapping max_seq_length-2 token chunk embeddings",
                              "near_distinct": "connected components of within-class pairs with cosine >=0.9 (transitive); direct pairs also recorded"},
                "examples": "first three selection records per class per arm, without choosing by outcome",
                "concurrency": "one sequential stream per arm; arms concurrent; aggregate reservation writes locked",
                "qwen_stall_policy": "45-second request timeout; stop Qwen arm on first transport stall; no fabricated denominator"}
    (OUT / "protocol.json").write_text(json.dumps(protocol, indent=2), encoding="utf-8")
    ledger = Round2Ledger(OUT / "calls.jsonl", git_commit=protocol["implementation_commit"])
    stop = threading.Event()

    def run_arm(arm):
        ledger.context.arm = arm
        if arm == "old_deepseek":
            provider = OriginalDeepSeek(ledger)
        elif arm == "new_deepseek":
            provider = DeepSeekProvider(ledger=ledger)
        elif arm == "new_gemini":
            provider = GeminiStructured(ledger)
        else:
            try:
                provider = OllamaProvider(ledger=ledger, client=httpx.Client(timeout=45))
            except Exception as exc:
                status = {"status": "skipped", "completed": 0, "reason": f"Local backend initialization: {type(exc).__name__}: {exc}", "evidence_label": LABEL}
                (OUT / f"{arm}_status.json").write_text(json.dumps(status, indent=2))
                return
        completed = 0
        status = {"status": "complete", "reason": "", "evidence_label": LABEL}
        for row in rows:
            if stop.is_set():
                status = {"status": "stopped", "reason": "Aggregate cap reached or peer failed", "evidence_label": LABEL}
                break
            tid = row["trace_id"]
            before_calls = {r.get("call_id", str(i)) for i, r in enumerate(ledger.rows())}
            started = time.perf_counter()
            alert = Alert(trace_id=tid, agent_name=traces[tid].agent_name, failure_type=row["label"])
            store = Store(traces)
            try:
                if arm == "old_deepseek":
                    provider.trace_id, provider.call_index = tid, 0
                    p, fallback, attempts = legacy.run(alert, store, provider)
                    valid = not fallback and bool(attempts) and attempts[-1]["passed"]
                    failures = [a["reason"] for a in attempts if not a["passed"]]
                    try:
                        ConfigRegistry(current_config(row)).apply(p)
                        applied = valid
                    except ValueError:
                        applied = False
                else:
                    # On Qwen's first request, call once before constructing a graph
                    # retry; a backend stall skips this optional model immediately.
                    if arm == "new_qwen" and completed == 0:
                        from services.critic.graph import build_prompt
                        prompt = build_prompt({"trace": traces[tid], "current_config": current_config(row), "evidence": evidence[tid]})
                        raw = provider.complete_patch(prompt, trace_id=tid, attempt=0)
                        # Reuse this real response once, not a new call or mock result.
                        class FirstResponse:
                            def __init__(self, response):
                                self.used = False
                                self.response = response
                            @property
                            def last_provenance(self):
                                return provider.last_provenance
                            def complete_patch(self, prompt, **kwargs):
                                if not self.used:
                                    self.used = True
                                    return self.response
                                return provider.complete_patch(prompt, **kwargs)
                        active_provider = FirstResponse(raw)
                    else:
                        active_provider = provider
                    p = run_critic(alert, store, llm_factory=lambda chosen=active_provider, **_: chosen,
                                   current_config=current_config(row), evidence=evidence[tid])
                    fallback = p.provenance.source == "fallback"
                    valid, applied = p.valid_without_fallback, p.dry_run_applied
                    failures = [r for r in p.rejection_reasons if not r.startswith("Dry-run rejected:")]
                    attempts = []
                now_calls = ledger.rows()
                calls = [r for i, r in enumerate(now_calls) if r.get("call_id", str(i)) not in before_calls and r["arm"] == arm]
                if arm == "new_qwen" and any(c.get("error") for c in calls):
                    status = {"status": "skipped" if not completed else "partial",
                              "reason": "Qwen transport stalled; stopped optional arm after logged failed calls",
                              "evidence_label": LABEL}
                    break
                anchors = evidence_anchors(evidence[tid])
                proposal = p.model_dump(mode="json")
                record = {"evidence_label": LABEL, "context_bleed_regeneration_pending": row["label"] == "CONTEXT_BLEED",
                          "arm": arm, "trace_id": tid, "task_id": row["task_id"], "failure_type": row["label"],
                          "source_model": f'{row["provider"]}/{row["model"]}', "source": "fallback" if fallback else "llm",
                          "implementation_commit": protocol["implementation_commit"], "date_utc": datetime.now(timezone.utc).isoformat(),
                          "model": provider.model, "model_version": provider.last_provenance.model_version,
                          "wall_latency_ms": (time.perf_counter()-started)*1000, "cost_usd": sum(c["cost_usd"] for c in calls),
                          "input_tokens": sum(c["input_tokens"] or 0 for c in calls), "output_tokens": sum(c["output_tokens"] or 0 for c in calls),
                          "call_ids": [c.get("call_id") for c in calls], "c1_valid": valid, "dry_run_applied": applied,
                          "validator_failures": failures, "original_validator_attempts": attempts,
                          "evidence": evidence[tid].model_dump(mode="json"), "evidence_anchors": anchors,
                          "grounding": grounding(p.patch_content, anchors),
                          "grounding_with_explanation": grounding(p.patch_content+"\n"+p.explanation, anchors), "proposal": proposal}
                with (OUT / f"{arm}.jsonl").open("a", encoding="utf-8", newline="\n") as stream:
                    stream.write(json.dumps(record, ensure_ascii=False)+"\n")
                completed += 1
                print(f"{arm} {completed}/60 {row['label']} source={record['source']} valid={valid} apply={applied} cost=${record['cost_usd']:.6f}", flush=True)
            except BudgetExceeded:
                stop.set()
                status = {"status": "stopped", "reason": "$1 aggregate cap would be exceeded", "evidence_label": LABEL}
                break
            except ProviderError as exc:
                if arm == "new_qwen":
                    status = {"status": "skipped" if not completed else "partial", "reason": str(exc), "evidence_label": LABEL}
                    break
                raise
        status.update(completed=completed, model=provider.model, model_version=provider.last_provenance.model_version)
        (OUT / f"{arm}_status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {arm: executor.submit(run_arm, arm) for arm in ARMS}
        for arm, future in futures.items():
            try:
                future.result()
            except Exception:
                stop.set()
                raise
    analyze(protocol)


if __name__ == "__main__":
    main()
