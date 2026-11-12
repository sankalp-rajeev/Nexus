"""Prepare fixed DEV smoke items and a seeded sample; never launches paid calls."""
import hashlib
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "sdk"))

from bench.heal.sets import derive, load_sets
from services.critic.dev_adapter import dev_labels
from scripts.phase5.measurement import atomic_json

SEED = 202611115


def smoke_items():
    sets = load_sets()
    result = json.loads((ROOT / "results/heal_critic_v1_structured_dev.json").read_text(encoding="utf-8"))["results"]
    scored = result["by_outcome"]["a1"]["per_failure_rows"]
    historical = {}
    with (ROOT / "reports/phase3/round3/v1_structured.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            historical[row["trace_id"]] = row
    items = []
    for promoted in (True, False):
        row = next(r for r in scored if r["provider"] == "deepseek" and r["gate"]["promoted"] == promoted)
        failure = next(f for f in sets["failures"] if f["failure_id"] == row["failure_id"])
        critic = historical[failure["trace_id"]]
        items.append(dict(failure, item_id="smoke-promoted" if promoted else "smoke-rejected",
                          regression=sets["regression_a2"], expected=dict(
                              gate_decision="promoted" if promoted else "rejected",
                              failure_class=critic["detector_type"],
                              outcome=row["gate"]["check1_own_task"], gate=row["gate"])))
    return items


def sample_manifest():
    rows = list(dev_labels(ROOT / "data/nexusbench/labels.csv"))
    population = sorted((r for r in rows if r["provider"] == "deepseek" and r["label"] == r["fault"] and r["label"] != "NORMAL"), key=lambda r: r["trace_id"])
    draws = random.Random(SEED).choices(population, k=100)
    items = []
    for index, row in enumerate(draws):
        items.append({**{k: row[k] for k in ("trace_id", "task_id", "family", "fault", "provider", "model")},
                      "original_checker_pass": row["checker_pass"] == "True", "item_id": f"heal-{index + 1:03d}"})
    _, _, regression = derive(rows, items)
    for item in items:
        item["regression"] = regression
    ids = [dict(item_id=i["item_id"], trace_id=i["trace_id"]) for i in items]
    payload = json.dumps(ids, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return dict(seed=SEED, split="dev", provider="deepseek", population_size=len(population),
                sampling="100 uniform draws with replacement; unique occurrence IDs", sample_size=100,
                id_list=ids, id_list_sha256=hashlib.sha256(payload).hexdigest(),
                hash_serialization="UTF-8 json.dumps(id_list, sort_keys=True, separators=(',', ':')); no newline",
                items=items)


if __name__ == "__main__":
    out = ROOT / "data/phase5/runs"
    atomic_json(out / "smoke_items.json", smoke_items())
    print("Prepared two DEV smoke items; no paid calls launched.")
