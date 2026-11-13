"""Phase 6 L4 re-run with the hardened SDK.

Imports the UNMODIFIED Phase 5 harness (``scripts/phase5/sdk_overhead.py``) and runs
its ``main()``. No measurement logic is copied or edited here. This wrapper only:

* redirects the harness's output/raw locations (``RAW`` and the ``ROOT``-relative
  result path) to ``data/phase6/runs/l4/`` and ``results/phase6/l4_rerun.json``;
* disables the harness's Part-B markdown writer, which would otherwise rewrite
  ``reports/phase5/results.md`` (the Phase 6 report is written separately);
* points the harness's read-only provider-ledger fingerprint at the Phase 5
  worktree's ledger (that file is not in this worktree);
* records SDK counters from each client AFTER it was shut down (outside every
  timed region), and attaches them, the comparison to Phase 5 and harness
  integrity evidence to the result JSON.

Any attempt by the harness to open a ``results/phase5`` or ``reports/phase5`` path
other than the read-only workload manifest raises instead of writing.
"""
from datetime import datetime, timezone
import hashlib
import json
import multiprocessing as mp
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "sdk"))

from scripts.phase5 import sdk_overhead as l4  # noqa: E402  (the unmodified harness)

PREREG_COMMIT = "08403ef"
HARNESS = "scripts/phase5/sdk_overhead.py"
RESULT_REL = "results/phase6/l4_rerun.json"
PHASE5_RESULT_REL = "results/phase5/sdk_overhead.json"
PHASE5_LEDGER = Path(r"C:\Umich\Projects\nexus-phase5\data\phase5\runs\budget.sqlite3")
READ_ONLY_PHASE5 = {"reports/phase5/sample_manifest.json"}
PROTECTED_PREFIXES = ("results/phase5", "reports/phase5")

# Harness ROOT-relative path -> where this re-run reads/writes instead.
REDIRECTS = {
    PHASE5_RESULT_REL: ROOT / RESULT_REL,
    "data/phase5/runs/budget.sqlite3": PHASE5_LEDGER,
}
RAW_DIR = ROOT / "data/phase6/runs/l4"

COUNTERS: dict[str, dict] = {}
_clients: list = []


class RedirectRoot:
    """Stand-in for the harness's ROOT: joins resolve normally except for REDIRECTS."""

    def __init__(self, real: Path):
        self._real = real

    def __truediv__(self, relative):
        key = str(relative).replace("\\", "/")
        if key in REDIRECTS:
            return REDIRECTS[key]
        if key.startswith(PROTECTED_PREFIXES) and key not in READ_ONLY_PHASE5:
            raise RuntimeError(f"Phase 6 re-run must not touch Phase 5 output: {key}")
        return self._real / relative

    def __getattr__(self, name):
        return getattr(self._real, name)


def git(*args: str) -> str:
    return subprocess.run(["git", "-c", f"safe.directory={ROOT.as_posix()}", *args], cwd=ROOT,
                          check=True, capture_output=True, text=True).stdout.strip()


def phase5_tree_clean() -> bool:
    """True when nothing under the Phase 5 results/reports/scripts differs from HEAD."""
    return git("status", "--porcelain", "--", "results/phase5", "reports/phase5", "scripts/phase5") == ""


def summarize_clients(clients) -> dict:
    keys = ("produced", "exported", "dropped", "dropped_queue_full", "dropped_bytes_cap",
            "export_retried", "export_failed", "dropped_total", "queued")
    total = {k: 0 for k in keys}
    violations = 0
    for client in clients:
        stats = client.stats
        for k in keys:
            total[k] += stats[k]
        violations += stats["produced"] != stats["exported"] + stats["dropped_total"] + stats["queued"]
    return dict(clients=len(clients), invariant_violations=violations, **total)


def install() -> None:
    """Apply the overrides. Everything measured stays the harness's own code."""
    l4.RAW = RAW_DIR
    l4.ROOT = RedirectRoot(ROOT)
    l4.write_report = lambda result: None  # would rewrite reports/phase5/results.md

    original_client, original_timing, original_recovery = l4.sdk_client, l4.timing, l4.recovery_probe

    def tracked_client(url):  # called only in setup, outside every timed region
        client = original_client(url)
        _clients.append(client)
        return client

    def timing_with_counters(workload, url, label):
        _clients.clear()
        result = original_timing(workload, url, label)
        COUNTERS[label] = summarize_clients(_clients)
        _clients.clear()
        return result

    def recovery_with_counters(workload, collector):
        _clients.clear()
        result = original_recovery(workload, collector)
        COUNTERS["recovery"] = summarize_clients(_clients[:1])  # the single long-lived client
        COUNTERS["recovery"]["final_stats"] = _clients[0].stats if _clients else None
        _clients.clear()
        return result

    l4.sdk_client, l4.timing, l4.recovery_probe = tracked_client, timing_with_counters, recovery_with_counters


def finish() -> dict:
    path = ROOT / RESULT_REL
    result = json.loads(path.read_text(encoding="utf-8"))
    phase5 = json.loads((ROOT / PHASE5_RESULT_REL).read_text(encoding="utf-8"))
    harness_bytes = (ROOT / HARNESS).read_bytes()
    result["harness_experiment_id"] = result.pop("experiment_id")
    result["experiment_id"] = "phase6-L4-rerun-hardened-sdk"
    result["phase6_rerun"] = dict(
        preregistration=dict(file="reports/phase6/l4_rerun_prereg.md", commit=PREREG_COMMIT),
        completed_at=datetime.now(timezone.utc).isoformat(),
        only_change="hardened SDK (sdk/nexus_agent); harness imported unmodified",
        harness=dict(path=HARNESS, sha256=hashlib.sha256(harness_bytes).hexdigest(),
                     git_blob=git("hash-object", HARNESS),
                     git_blob_at_prereg_commit=git("rev-parse", f"{PREREG_COMMIT}:{HARNESS}"),
                     identical_to_prereg_commit=git("hash-object", HARNESS) == git("rev-parse", f"{PREREG_COMMIT}:{HARNESS}")),
        redirected_outputs=dict(raw=str(RAW_DIR.relative_to(ROOT)), result=RESULT_REL,
                                markdown_writer="disabled", ledger_read_only=str(PHASE5_LEDGER)),
        phase5_tree_clean_after_run=phase5_tree_clean(),
        sdk_counters=COUNTERS,
        counter_notes="Read after each client was shut down, outside timed regions. 'timing' phases "
                      "aggregate every SDK-on client; 'recovery' is the single long-lived probe client. "
                      "Memory trials run in child processes and are not counted here.",
        phase5_reference=dict(
            source=PHASE5_RESULT_REL,
            sdk_source_sha256=phase5["methodology"]["sdk_source_sha256"],
            healthy_paired_added_per_step=phase5["collector_healthy"]["paired_added_per_step"],
            stopped_paired_added_per_step=phase5["collector_stopped"]["paired_added_per_step"],
            added_median_peak_rss_bytes=phase5["memory"]["added_median_peak_rss_bytes"],
            lost_outage_events=phase5["recovery"]["lost_outage_events"]))
    path.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def main() -> None:
    if not phase5_tree_clean():
        raise RuntimeError("results/phase5, reports/phase5 or scripts/phase5 already differ from HEAD; stop")
    if git("hash-object", HARNESS) != git("rev-parse", f"{PREREG_COMMIT}:{HARNESS}"):
        raise RuntimeError("Harness differs from the pre-registered version; stop")
    sdk_file = Path(sys.modules["nexus_agent"].__file__).resolve()
    if ROOT / "sdk" not in sdk_file.parents:
        raise RuntimeError(f"nexus_agent imported from outside this worktree: {sdk_file}")
    install()
    l4.main()
    result = finish()
    if not result["phase6_rerun"]["phase5_tree_clean_after_run"]:
        raise RuntimeError("Phase 5 files changed during the re-run")
    print("Phase 6 L4 re-run complete:", RESULT_REL, flush=True)


if __name__ == "__main__":
    mp.freeze_support()
    main()
