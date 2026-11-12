"""Load Phase 3 critic proposals (round 3 records) as Phase 4 config diffs.

Input: ``reports/phase3/round3/<arm>.jsonl`` from ../nexus-phase3 once merged, one
record per (trace, arm): ``{"trace_id", "arm", "evidence_mode", "proposal",
"c1_valid", "dry_run_applied", ...}`` with ``proposal`` a ``CriticProposal`` dict.

Rules (amendment A1, item 5):
* only ``evidence_mode == "detector"`` records of the requested arm are accepted
  (oracle evidence cannot be deployed);
* a fallback (``provenance.source != "llm"``), an invalid proposal (``c1_valid``
  false) or one that failed the Phase 3 dry run gives **no patch**: it is never a
  success and is reported per failure;
* the patch is ``bench.heal.config.from_phase3(target_component, patch_content)``,
  applied to the failure's deployed config; a key or type it cannot apply is
  ``inapplicable``;
* a trace with two records for one arm is refused.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from bench.heal.config import ConfigPatch, PatchError, apply_patch, faulted_config, from_phase3

ARMS = ("new", "v1_structured")


@dataclass(frozen=True)
class Proposal:
    trace_id: str
    arm: str
    patch: ConfigPatch | None
    status: str          # "patch" | "no_patch" | "inapplicable"
    reason: str = ""
    phase3_fix_tag: str | None = None


def load_round3(path: str, arm: str, faults: dict[str, str]) -> dict[str, Proposal]:
    """``faults`` maps trace_id -> fault of the pre-registered failure (deployed config)."""
    if arm not in ARMS:
        raise ValueError(f"arm must be one of {ARMS} (oracle evidence is excluded)")
    out: dict[str, Proposal] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("arm") != arm:
                raise ValueError(f"{path}: record for arm {rec.get('arm')!r}, expected {arm!r}")
            if rec.get("evidence_mode") != "detector":
                raise ValueError(f"{rec['trace_id']}: evidence_mode must be 'detector'")
            tid = rec["trace_id"]
            if tid in out:
                raise ValueError(f"{tid}: two {arm} records")
            out[tid] = _one(rec, arm, faults.get(tid))
    return out


def _one(rec, arm, fault) -> Proposal:
    tid, p = rec["trace_id"], rec.get("proposal")
    if p is None:
        return Proposal(tid, arm, None, "no_patch", "no proposal generated")
    tag = p.get("fix_tag")
    if (p.get("provenance") or {}).get("source") != "llm":
        return Proposal(tid, arm, None, "no_patch", "fallback proposal", tag)
    if not rec.get("c1_valid") or not rec.get("dry_run_applied"):
        return Proposal(tid, arm, None, "no_patch", "invalid or failed Phase 3 dry run", tag)
    try:
        patch = from_phase3(p["target_component"], p["patch_content"])
        patch = ConfigPatch(ops=patch.ops, source=f"critic:{arm}", note=tid)
        if fault is not None:
            apply_patch(faulted_config(fault), patch)
    except (PatchError, ValueError, json.JSONDecodeError) as exc:
        return Proposal(tid, arm, None, "inapplicable", str(exc), tag)
    return Proposal(tid, arm, patch, "patch", "", tag)
