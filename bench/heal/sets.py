"""Pre-registered Phase 4 task sets (dev only): failures, held-out sets, regression set.

    python -m bench.heal.sets --selection ../nexus-phase3/results/critic_dev/selection.json

writes ``reports/phase4/prereg_sets.json``. Every choice is a function of the
committed dev labels and fixed seeds, so rerunning prints the same file.

* **Failures** are the Phase 3 critic's dev selection (12 traces per class), pinned
  by the SHA-256 of that file. An entry whose bench-v1.1 label differs from the
  label the selection gives it is excluded and listed.
* **Held-out set** of a failure: ``HELDOUT_K`` other dev tasks where the same fault
  fired for the same provider in the committed data. Each (fault, provider) gets a
  seeded pool of ``HELDOUT_K + 1`` tasks; a failure takes the first ``HELDOUT_K``
  pool tasks that are not its own task.
* **Regression set**: ``REG_PER_FAMILY`` dev tasks per family (all four families),
  seeded, from tasks whose committed uninjected run passed the checker.
* **A2 regression set** (``regression_a2``, amendment A2): the regression set with its
  qa part widened to *every* dev qa task whose committed uninjected run passed the
  checker; the tool, plan and memory tasks are unchanged. ``regression`` is kept as
  written so scores made under A1 stay reproducible.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
from collections import defaultdict
from typing import Any, Iterator

from bench.generate import SEED

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
LABELS = os.path.join(REPO, "data", "nexusbench", "labels.csv")
SPLITS = os.path.join(REPO, "data", "nexusbench", "splits.json")
SETS_PATH = os.path.join(REPO, "reports", "phase4", "prereg_sets.json")

HELDOUT_K = 5
REG_PER_FAMILY = 3
FAMILIES = ("qa", "tool", "plan", "memory")
A2_WIDENED_FAMILY = "qa"   # amendment A2: over-abstention guard
FAILURE_CLASSES = ("HALLUCINATION", "CONTEXT_BLEED", "PLAN_DRIFT", "TOOL_MISFIRE",
                   "LOOP_DETECTED")


class SealedSplitError(RuntimeError):
    """Raised when anything outside the dev split is requested."""


def dev_splits() -> dict[str, str]:
    with open(SPLITS, encoding="utf-8") as fh:
        return json.load(fh)


def assert_dev(task_ids, splits: dict[str, str] | None = None) -> None:
    splits = splits or dev_splits()
    bad = sorted(t for t in task_ids if splits.get(t) != "dev")
    if bad:
        raise SealedSplitError(f"test split is sealed; non-dev task ids: {bad[:5]}")


def dev_label_rows(path: str = LABELS) -> Iterator[dict[str, str]]:
    """Yield dev rows only. Non-dev rows are dropped on their split field, unused."""
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if row["split"] == "dev":
                yield row


def file_sha256(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def build_sets(selection_path: str) -> dict[str, Any]:
    rows = list(dev_label_rows())
    by_trace = {r["trace_id"]: r for r in rows}
    with open(selection_path, encoding="utf-8") as fh:
        sel_doc = json.load(fh)
    selection = sel_doc["selection"]
    # Content hash, as Phase 3 computes it (robust to line-ending conversion).
    sel_sha = hashlib.sha256(json.dumps(selection, sort_keys=True).encode()).hexdigest()
    if sel_sha != sel_doc.get("selection_sha256"):
        raise ValueError("selection content does not match its recorded selection_sha256")

    failures, excluded = [], []
    for s in selection:
        r = by_trace.get(s["trace_id"])
        if r is None:
            raise SealedSplitError(f"selection trace {s['trace_id']} is not a dev trace")
        entry = {"trace_id": s["trace_id"], "task_id": r["task_id"], "family": r["family"],
                 "fault": r["fault"], "provider": r["provider"], "model": r["model"],
                 "selection_label": s["label"], "v11_label": r["label"],
                 "original_checker_pass": r["checker_pass"] == "True"}
        if r["label"] != s["label"] or r["fault"] != s["label"]:
            entry["reason"] = (f"bench-v1.1 label is {r['label']} (fault {r['fault']}), "
                               f"not {s['label']}")
            excluded.append(entry)
        else:
            failures.append(entry)

    # Held-out pools per (fault, provider).
    fired: dict[tuple[str, str], set[str]] = defaultdict(set)
    for r in rows:
        if r["fault"] in FAILURE_CLASSES and r["label"] == r["fault"]:
            fired[(r["fault"], r["provider"])].add(r["task_id"])
    pools: dict[str, list[str]] = {}
    for f in failures:
        key = (f["fault"], f["provider"])
        name = f"{key[0]}|{key[1]}"
        if name not in pools:
            cands = sorted(fired[key])
            random.Random(f"{SEED}:heal:heldout:{key[0]}:{key[1]}").shuffle(cands)
            pools[name] = cands[:HELDOUT_K + 1]
        f["heldout"] = [t for t in pools[name] if t != f["task_id"]][:HELDOUT_K]
        f["failure_id"] = f"{f['fault']}|{f['provider']}|{f['task_id']}"

    # Regression set: tasks whose committed uninjected run passed.
    passed_none = defaultdict(set)
    for r in rows:
        if r["fault"] == "NONE" and r["checker_pass"] == "True":
            passed_none[r["family"]].add(r["task_id"])
    regression: list[str] = []
    for fam in FAMILIES:
        cands = sorted(passed_none[fam])
        random.Random(f"{SEED}:heal:regression:{fam}").shuffle(cands)
        regression += sorted(cands[:REG_PER_FAMILY])
    # A2: every dev qa task that passes with no fault, plus the other families as before.
    regression_a2 = sorted(passed_none[A2_WIDENED_FAMILY]) + [
        t for t in regression if not t.startswith(f"{A2_WIDENED_FAMILY}-")]

    all_ids = {f["task_id"] for f in failures} | set(regression) | set(regression_a2)
    all_ids |= {t for p in pools.values() for t in p}
    assert_dev(all_ids)

    return {
        "seed": SEED,
        "heldout_k": HELDOUT_K,
        "regression_per_family": REG_PER_FAMILY,
        "selection_source": os.path.relpath(selection_path, REPO).replace(os.sep, "/"),
        "selection_sha256": sel_sha,
        "labels_sha256": file_sha256(LABELS),
        "heldout_pools": pools,
        "regression": regression,
        "regression_a2": regression_a2,
        "failures": failures,
        "excluded": excluded,
    }


def load_sets(path: str = SETS_PATH) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selection", required=True)
    ap.add_argument("--out", default=SETS_PATH)
    args = ap.parse_args()
    sets = build_sets(args.selection)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(sets, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print(f"{len(sets['failures'])} failures, {len(sets['excluded'])} excluded, "
          f"{len(sets['regression'])} regression tasks "
          f"({len(sets['regression_a2'])} under A2) -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
