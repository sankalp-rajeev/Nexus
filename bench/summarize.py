"""Summarise NexusBench into results/bench_dataset.json and print the datasheet tables.

    python -m bench.summarize
"""

from __future__ import annotations

import csv
import json
import os
import sys
from collections import Counter, defaultdict

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _p in (REPO, os.path.join(REPO, "sdk")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bench.generate import MODELS, SEED  # noqa: E402
from bench.labeler import LABELS  # noqa: E402
from bench.llm import CostLedger  # noqa: E402
from services.common.results import provenance, rate, write_result  # noqa: E402

DATA = os.path.join(REPO, "data", "nexusbench")


def load_rows(data_dir: str = DATA) -> list[dict]:
    with open(os.path.join(data_dir, "labels.csv"), encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def summarise(rows: list[dict]) -> dict:
    by_split_label = {sp: Counter(r["label"] for r in rows if r["split"] == sp)
                      for sp in ("dev", "test")}
    by_provider_label = {p: Counter(r["label"] for r in rows if r["provider"] == p)
                         for p in sorted({r["provider"] for r in rows})}
    eff: dict[str, dict] = {}
    for fault in sorted({r["fault"] for r in rows} - {"NONE"}):
        per = defaultdict(lambda: [0, 0])
        for r in rows:
            if r["fault"] == fault:
                per[r["provider"]][1] += 1
                per[r["provider"]][0] += r["injection_effective"] == "True"
                per["all"][1] += 1
                per["all"][0] += r["injection_effective"] == "True"
        eff[fault] = {p: rate(k, n) for p, (k, n) in sorted(per.items())}
    none = [r for r in rows if r["fault"] == "NONE"]
    natural = Counter(r["label"] for r in none)
    with open(os.path.join(DATA, "manifest.sha256"), encoding="utf-8") as fh:
        digest = next(ln.split()[2] for ln in fh if ln.startswith("# digest"))
    return {
        "n_traces": len(rows),
        "n_tasks": len({r["task_id"] for r in rows}),
        "labels_total": dict(Counter(r["label"] for r in rows)),
        "labels_by_split": {k: dict(v) for k, v in by_split_label.items()},
        "labels_by_provider": {k: dict(v) for k, v in by_provider_label.items()},
        "injection_effectiveness": eff,
        "uninjected_runs": {"n": len(none), "labels": dict(natural),
                            "task_success": rate(sum(r["checker_pass"] == "True" for r in none),
                                                 len(none))},
        "test_manifest_digest": digest,
    }


def main() -> int:
    rows = load_rows()
    s = summarise(rows)
    ledger = CostLedger()
    s["spend_usd_all_time"] = {p: round(ledger.spent(p), 4) for p in ("gemini", "deepseek")}
    test = s["labels_by_split"]["test"]
    summary = (f"NexusBench: {s['n_traces']} labelled traces over {s['n_tasks']} tasks; "
               "test split per class " + ", ".join(f"{k}={test.get(k, 0)}" for k in LABELS
                                                  if test.get(k)))
    prov = provenance(provider="deepseek+ollama",
                      model=f"{MODELS['deepseek']} + {MODELS['ollama']}", mock=False, seed=SEED)
    write_result("B0-dataset", "bench_dataset.json", s, provenance_info=prov, summary=summary)
    print(json.dumps(s, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
