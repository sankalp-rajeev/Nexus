"""The Phase 6 L4 wrapper must only redirect I/O; it must not copy or alter measurement code."""
from pathlib import Path

import pytest

import nexus_agent as nexus
from scripts.phase6 import sdk_overhead_rerun as rerun

ROOT = Path(__file__).resolve().parents[3]


def test_redirects_only_the_result_and_ledger_paths():
    root = rerun.RedirectRoot(ROOT)
    assert root / "results/phase5/sdk_overhead.json" == ROOT / "results/phase6/l4_rerun.json"
    assert root / "results\\phase5\\sdk_overhead.json" == ROOT / "results/phase6/l4_rerun.json"
    assert root / "data/phase5/runs/budget.sqlite3" == rerun.PHASE5_LEDGER
    assert root / "sdk/nexus_agent" == ROOT / "sdk/nexus_agent"
    assert root / "reports/phase5/sample_manifest.json" == ROOT / "reports/phase5/sample_manifest.json"


@pytest.mark.parametrize("path", ["results/phase5/headline.json", "reports/phase5/results.md",
                                  "reports/phase5/amendment_1.md", "results/phase5/anything_new.json"])
def test_any_other_phase5_output_path_is_refused(path):
    with pytest.raises(RuntimeError, match="Phase 5 output"):
        rerun.RedirectRoot(ROOT) / path


def test_raw_vectors_go_to_the_ignored_phase6_directory():
    assert rerun.RAW_DIR == ROOT / "data/phase6/runs/l4"


def test_wrapper_contains_no_measurement_logic():
    source = (ROOT / "scripts/phase6/sdk_overhead_rerun.py").read_text(encoding="utf-8")
    for forbidden in ("perf_counter", "quantile", "default_rng", "def execute_task(", "def timing(",
                      "def memory_worker(", "def recovery_probe(", "tracemalloc", "SEED ="):
        assert forbidden not in source
    # The harness functions it relies on are imported, not redefined.
    for name in ("timing", "memory_trials", "recovery_probe", "execute_task", "main"):
        assert getattr(rerun.l4, name).__module__ == "scripts.phase5.sdk_overhead"


def test_counter_summary_reports_invariant_violations():
    class Exporter:
        def export(self, batch):
            return True

        def close(self):
            pass

    client = nexus.init(agent_name="rerun-fixture", async_export=False)
    client._exporter = Exporter()
    try:
        with nexus.span("custom", input="x"):
            pass
    finally:
        nexus.shutdown()
    summary = rerun.summarize_clients([client])
    assert summary["produced"] == summary["exported"] == 1
    assert summary["invariant_violations"] == 0
    assert summary["dropped_shutdown"] == 0 and summary["dropped_total"] == 0
