"""Export a deterministic, DEV-only demo from an explicit committed allowlist.

No benchmark execution, model loading, LLM calls, working-tree results or TEST
result files. Run from any directory: python dashboard/scripts/export_replay.py.
"""

from __future__ import annotations

import csv
import io
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = (
    "data/nexusbench/splits.json",
    "data/nexusbench/labels.csv",
    "data/nexusbench/traces.jsonl",
    "results/phase2_dev_predictions.json",
    "results/critic_smoke_mock.json",
)
CLASSES = ("NORMAL", "HALLUCINATION", "TOOL_MISFIRE", "CONTEXT_BLEED", "PLAN_DRIFT", "LOOP_DETECTED")


def git(*args: str) -> bytes:
    return subprocess.check_output(
        ["git", "-c", f"safe.directory={ROOT.as_posix()}", *args], cwd=ROOT,
    )


def committed_sources() -> tuple[dict[str, bytes], dict[str, str]]:
    # Pin the commit first, then each blob, even if HEAD changes during export.
    revision = git("rev-parse", "HEAD").decode().strip()
    blobs = {p: git("rev-parse", f"{revision}:{p}").decode().strip() for p in SOURCES}
    return {p: git("cat-file", "blob", blob) for p, blob in blobs.items()}, blobs


def build_replay(sources: dict[str, bytes], blobs: dict[str, str]) -> dict:
    splits = json.loads(sources[SOURCES[0]])
    rows = csv.DictReader(io.StringIO(sources[SOURCES[1]].decode("utf-8")))
    dev_ids = set()
    for row in rows:
        if row["split"] == "dev":
            if splits.get(row["task_id"]) != "dev":
                raise ValueError("DEV label disagrees with committed task split")
            dev_ids.add(row["trace_id"])
    predictions = json.loads(sources[SOURCES[3]])["predictions"]
    if not set(predictions) <= dev_ids:
        raise ValueError("Prediction source contains non-DEV trace IDs")
    # Two per predicted class, so the small demo includes failures and normal runs.
    selected = set()
    for label in CLASSES:
        selected.update(sorted(tid for tid, p in predictions.items() if p["pred"] == label)[:2])
    traces = []
    for line in sources[SOURCES[2]].splitlines():
        # The committed JSONL holds both splits. Inspect only the opaque ID;
        # deserialize trace content only after it is selected from DEV IDs.
        match = re.search(rb'"trace_id"\s*:\s*"([^"]+)"', line)
        if not match or match[1].decode() not in selected:
            continue
        trace = json.loads(line)
        if trace["trace_id"] not in selected:
            continue
        task_ids = {s.get("metadata", {}).get("task_id") for s in trace["spans"]}
        task_ids.discard(None)
        if not task_ids or any(splits.get(task) != "dev" for task in task_ids):
            raise ValueError("Trace is not independently confirmed DEV")
        trace.pop("source", None)
        traces.append(trace)
    if {t["trace_id"] for t in traces} != selected:
        raise ValueError("Selected DEV traces missing from committed corpus")
    traces.sort(key=lambda t: t["trace_id"])
    templates = json.loads(sources[SOURCES[4]])
    if templates["provenance"]["mock"] is not True:
        raise ValueError("Expected explicitly mock critic smoke templates")
    by_failure = {}
    for p in templates["results"]["proposals"]:
        if p["source"] == "fallback":
            by_failure.setdefault(p["failure_type"], p)
    alerts, proposals, gates = [], [], []
    for trace in traces:
        tid = trace["trace_id"]
        failure = predictions[tid]["pred"]
        if failure == "NORMAL":
            continue
        alert_id = f"replay-{tid}"
        alerts.append({
            "alert_id": alert_id, "trace_id": tid, "agent_name": trace["agent_name"],
            "failure_type": failure, "severity": "HIGH", "status": "OPEN",
            "created_at": trace["completed_at"] or trace["started_at"],
            "source": SOURCES[3],
        })
        template = by_failure.get(failure)
        if template:
            proposal_id = f"{alert_id}-template"
            proposals.append({
                "proposal_id": proposal_id, "alert_id": alert_id, "trace_id": tid,
                "failure_type": failure, "patch_type": template["patch_type"],
                "target_component": template["target_component"],
                "explanation": template["explanation_excerpt"],
                "patch_content": template["patch_content_excerpt"],
                "confidence": template["confidence"], "status": "PENDING_REVIEW",
                "created_at": trace["completed_at"] or trace["started_at"],
                "source": "committed_mock_template", "template_trace_id": template["trace_id"],
                "illustrative": True, "excerpt_only": True,
                "root_cause_analysis": "Illustrative generic fallback excerpt from committed mock smoke results. Not generated or evaluated for this DEV trace.",
            })
        gates.append({
            "trace_id": tid, "proposal_id": f"{alert_id}-template" if template else None,
            "status": "placeholder", "decision": None,
            "reason": "placeholder: Phase 4 results are not final. No gate evaluation or patch application.",
        })
    return {
        "schema_version": 1, "mode": "replay", "split": "dev", "read_only": True,
        "provenance": {"source_blobs": blobs, "selection": "first two trace IDs per predicted class", "llm_calls": 0},
        "notices": [
            "DEV-only historical replay; detector predictions are committed Phase 2 results.",
            "Critic proposals are illustrative generic mock template excerpts, not evaluated DEV proposals.",
            "Phase 4 gate decisions are placeholder. No health gains or gate outcomes are claimed.",
        ],
        "traces": traces, "alerts": alerts, "proposals": proposals, "gate_decisions": gates,
    }


def main() -> None:
    sources, blobs = committed_sources()
    replay = build_replay(sources, blobs)
    destination = ROOT / "dashboard/public/replay.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(replay, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Exported {len(replay['traces'])} DEV traces, {len(replay['alerts'])} alerts to {destination}")


if __name__ == "__main__":
    main()
