"""Read progress and both budgets without computing outcome statistics."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.phase5.measurement import Budget


if __name__ == "__main__":
    root = ROOT / "data/phase5/runs"
    print(json.dumps(Budget(root).snapshot(), indent=2))
    pid = root / "runner.pid.json"
    if pid.exists():
        print(pid.read_text(encoding="utf-8"))
    log = root / "heals.log"
    if log.exists():
        lines = log.read_text(encoding="utf-8").splitlines()
        print(f"Progress lines: {sum(line.startswith('id=') for line in lines)}")
        print("\n".join(lines[-3:]))
