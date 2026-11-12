"""Run the suite without opening sealed TEST artifacts; report explicit skips."""
import os
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "sdk"))

import pytest
from bench.heal import sets
from services.critic.dev_adapter import dev_labels


def guard(event, args):
    if event != "open" or not args or not isinstance(args[0], (str, bytes, os.PathLike)):
        return
    path = Path(os.fsdecode(args[0])).resolve()
    try:
        relative = path.relative_to(ROOT).as_posix()
    except ValueError:
        return
    if (relative.startswith("reports/phase4/test/") or relative == "reports/phase4/prereg_sets_test.json"
            or relative.startswith("results/") and ("_test" in path.name or "test_" in path.name)):
        raise RuntimeError("Phase 5 sealed TEST access blocked")


class DevOnly:
    def pytest_collection_modifyitems(self, items):
        for item in items:
            node = item.nodeid
            blocked = node.startswith("tests/unit/heal/test_a3.py::") and "refuses_without" not in node
            if node.startswith("tests/unit/test_reporting_hygiene.py::"):
                name = str(getattr(item, "callspec", None).params.get("path", "")) if hasattr(item, "callspec") else ""
                sealed_result = bool(name) and Path(name).resolve().parent == ROOT / "results" and ("_test" in Path(name).name or "test_" in Path(name).name)
                blocked |= sealed_result or "test_results_md_is_up_to_date" in node
            if blocked:
                item.add_marker(pytest.mark.skip(reason="Phase 5: TEST sealed; this test opens TEST artifacts"))


def main():
    sys.addaudithook(guard)
    # The legacy helper deserializes CSV rows before checking split. Substitute
    # the existing frozen DEV adapter for tests only, yielding identical DEV rows
    # while discarding TEST payloads before deserialization. Source stays intact.
    with patch.object(sets, "dev_label_rows", lambda path=sets.LABELS: dev_labels(path)):
        return pytest.main(["-p", "no:deepeval", *sys.argv[1:]], plugins=[DevOnly()])


if __name__ == "__main__":
    raise SystemExit(main())
