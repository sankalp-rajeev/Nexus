"""Blind, balanced review sample from saved round-2 outputs; no model calls."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import random

ROOT = Path(__file__).resolve().parents[2]
SEED = 20261110
ARMS = ("old_deepseek", "new_deepseek", "new_gemini", "new_qwen")
CLASSES = ("HALLUCINATION", "TOOL_MISFIRE", "CONTEXT_BLEED", "PLAN_DRIFT", "LOOP_DETECTED")


def sample_records(records, seed=SEED):
    buckets = defaultdict(list)
    for row in records:
        buckets[row["failure_type"], row["arm"]].append(row)
    rng = random.Random(seed)
    chosen = []
    for ft in CLASSES:
        for arm in ARMS:
            pool = sorted(buckets[ft, arm], key=lambda r: r["trace_id"])
            if not pool:
                raise ValueError(f"Missing class/arm stratum: {ft}/{arm}")
            chosen.append(rng.choice(pool))
    rng.shuffle(chosen)
    return chosen


def write_sample(source, output):
    paths = [source / f"{arm}.jsonl" for arm in ARMS]
    selected = sample_records([json.loads(line) for p in paths
                               for line in p.read_text(encoding="utf-8").splitlines()])
    lines = ["# Specificity proxy: blind human review", "",
        "20 saved round-2 proposals; seed 20261110; one random proposal per class × arm stratum.",
        "Arms/classes, source identities and proxy verdicts are in proxy_sample_key.json only.",
        "Evidence is the saved oracle DEV evidence; CONTEXT_BLEED predates regeneration.",
        "Judge whether the patch is meaningfully grounded in this evidence, beyond a generic rule or shared tool name.",
        "Leave a verdict of grounded / ungrounded / unclear, with an optional reason.", ""]
    key = {"seed": SEED, "sources_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
           "samples": []}
    for i, row in enumerate(selected, 1):
        sample_id = f"P{i:02d}"
        lines += [f"## {sample_id}", "", "| Human verdict | Reason (optional) |", "|---|---|", "| | |", "",
                  "Patch text:", "", "````text", row["proposal"]["patch_content"], "````", "",
                  "Evidence:", "", "````json", json.dumps(row["evidence"], indent=2, ensure_ascii=False), "````", ""]
        key["samples"].append({"sample_id": sample_id, "trace_id": row["trace_id"],
            "arm": row["arm"], "failure_type": row["failure_type"],
            "proposal_id": row["proposal"].get("proposal_id"),
            "grounding": row["grounding"]})
    output.mkdir(parents=True, exist_ok=True)
    (output / "proxy_sample.md").write_text("\n".join(lines), encoding="utf-8")
    (output / "proxy_sample_key.json").write_text(json.dumps(key, indent=2, ensure_ascii=False), encoding="utf-8")
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "results/critic_dev/round2")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/phase3")
    args = parser.parse_args()
    write_sample(args.source, args.output)


if __name__ == "__main__":
    main()
