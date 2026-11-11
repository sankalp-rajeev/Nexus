"""Append-only per-call accounting; unsupported paid providers fail closed."""

import json
import threading
from pathlib import Path

CAP_USD = 0.75


class BudgetExceeded(RuntimeError):
    pass


class CostLedger:
    def __init__(self, path="results/critic_dev/calls.jsonl", *, cap_usd=CAP_USD):
        self.path = Path(path)
        self.lock = threading.Lock()
        if cap_usd <= 0:
            raise ValueError("A positive explicitly authorized cap is required")
        self.cap_usd = cap_usd

    def rows(self):
        if not self.path.exists():
            return []
        events = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]
        # A reservation is replaced logically by its settlement, never deleted.
        calls = {}
        for i, row in enumerate(events):
            calls[row.get("call_id", f"legacy-{i}")] = row
        return list(calls.values())

    @property
    def spent(self):
        return sum(row["cost_usd"] for row in self.rows())

    def check(self, worst_case_usd=0):
        if self.spent >= self.cap_usd or self.spent + worst_case_usd > self.cap_usd:
            raise BudgetExceeded(f"Phase 3 ${self.cap_usd:.2f} cap reached")

    def append(self, row):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as out:
                out.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
