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


def assert_split(task_ids, split: str, splits: dict[str, str] | None = None) -> None:
    """Every task id belongs to ``split`` (A3: a test-mode run never touches dev)."""
    if split == "dev":
        return assert_dev(task_ids, splits)
    splits = splits or dev_splits()
    bad = sorted(t for t in task_ids if splits.get(t) != split)
    if bad:
        raise SealedSplitError(f"{split} mode; task ids from another split: {bad[:5]}")


def dev_label_rows(path: str = LABELS) -> Iterator[dict[str, str]]:
    """Yield dev rows only. Non-dev rows are dropped on their split field, unused."""
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if row["split"] == "dev":
                yield row


def file_sha256(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def derive(rows: list[dict[str, str]], failures: list[dict[str, Any]]
           ) -> tuple[dict[str, list[str]], list[str], list[str]]:
    """Held-out pools (sets each failure's ``heldout`` and ``failure_id``), the regression
    set and the A2 regression set, from the label rows of one split. Same code and seed
    strings for dev and, under amendment A3, for test."""
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

    return pools, regression, regression_a2


def entries(selection, by_trace, split: str
            ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Failure entries for a selection, and the exclusions: an entry whose bench-v1.1
    label or fault differs from the label the selection gives it is not a failure."""
    failures, excluded = [], []
    for s in selection:
        r = by_trace.get(s["trace_id"])
        if r is None:
            raise SealedSplitError(f"selection trace {s['trace_id']} is not a {split} trace")
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
    return failures, excluded


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

    failures, excluded = entries(selection, by_trace, "dev")

    pools, regression, regression_a2 = derive(rows, failures)

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


# -- amendment A3: the test sets ---------------------------------------------------

TEST_SETS_PATH = os.path.join(REPO, "reports", "phase4", "prereg_sets_test.json")


def test_label_rows(path: str = LABELS) -> list[dict[str, str]]:
    """Test label rows (A3: labels only, read once the dev phase is reviewed)."""
    with open(path, encoding="utf-8", newline="") as fh:
        return [r for r in csv.DictReader(fh) if r["split"] == "test"]


def build_test_sets() -> dict[str, Any]:
    """A3 section 1: the test sets, by the dev code and rules on the test label rows.

    Failures are chosen by the rule that chose the dev failures, Phase 3's
    ``services.critic.experiments.select_labels`` (12 per class, seed
    ``20261110:<class>``, round-robin over source models, distinct tasks first), run on
    the bench-v1.1 test rows. The dev exclusion (``entries``) and the A1
    no-observable-harm rule (``score.eligible``) apply unchanged. Held-out pools,
    regression and A2 regression sets come from ``derive`` with the same seed strings."""
    from services.critic.experiments import select_labels

    rows = test_label_rows()
    by_trace = {r["trace_id"]: r for r in rows}
    picked = select_labels(rows)
    selection = [{k: r[k] for k in ("trace_id", "task_id", "label", "provider", "model")}
                 for r in picked]
    sel_sha = hashlib.sha256(json.dumps(selection, sort_keys=True).encode()).hexdigest()
    failures, excluded = entries(selection, by_trace, "test")
    pools, regression, regression_a2 = derive(rows, failures)
    splits = dev_splits()
    ids = ({f["task_id"] for f in failures} | set(regression_a2)
           | {t for p in pools.values() for t in p})
    bad = sorted(t for t in ids if splits.get(t) != "test")
    if bad:
        raise ValueError(f"A3 test sets contain non-test task ids: {bad[:5]}")
    return {
        "split": "test",
        "amendment": "A3",
        "seed": SEED,
        "heldout_k": HELDOUT_K,
        "regression_per_family": REG_PER_FAMILY,
        "selection_rule": "services.critic.experiments.select_labels on bench-v1.1 test rows",
        "selection": selection,
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
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--selection")
    g.add_argument("--test", action="store_true", help="A3: write the test sets")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    sets = build_test_sets() if args.test else build_sets(args.selection)
    args.out = args.out or (TEST_SETS_PATH if args.test else SETS_PATH)
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
