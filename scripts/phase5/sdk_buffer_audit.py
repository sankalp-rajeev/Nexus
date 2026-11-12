"""Code-derived SDK buffer/loss answers; no benchmark or provider calls."""
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.phase5.measurement import atomic_json


def main():
    result = dict(
        observed_failed_events=17, export_attempts_per_batch=1, retries=0,
        code_path="NexusClient._run_export_loop -> _drain -> _export_batch -> HttpExporter.export",
        failed_batch_policy="discard on False or exception; no retry/requeue/persistence",
        previous_public_counter="stats.dropped counted queue-full spans only",
        new_public_counters=["stats.export_failed", "stats.dropped_total"],
        compatibility="stats.dropped retains queue-full-only meaning; all counters are process-lifetime spans",
        max_queue_size_default=10000, max_batch_size_default=50,
        queue_full_policy="drop newest incoming span; preserve already queued spans",
        configurable_unbounded_queue="max_queue_size <= 0 uses Python Queue's unbounded mode",
        worst_case_memory_bytes=None,
        worst_case_memory_reason="No byte bound: unrestricted metadata, identifiers, caller-supplied Span fields, configurable character limits and unbounded explicit pending spans. A count bound cannot imply a finite RAM bound.",
        default_capped_text_chars_per_span=4500,
        default_capped_text_unicode_storage_upper_bound_bytes=10000 * 4500 * 4,
        text_estimate_excludes="Python objects, metadata, identifiers, in-flight batch (normally <=50), serializer copies, pending spans; this is not a total memory bound",
        memory_measurement_collector="healthy/up",
        memory_result_source="results/phase5/sdk_overhead.json",
        historical_measurement="L4 measured SDK before the new loss counters; not re-run",
        sdk_source_sha256={p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in
                           ["sdk/nexus_agent/client.py", "sdk/nexus_agent/config.py", "sdk/nexus_agent/exporters/http.py"]},
    )
    atomic_json(ROOT / "results/phase5/sdk_buffer_audit.json", result)
    path = ROOT / "reports/phase5/results.md"
    text = path.read_text(encoding="utf-8")
    text += """

### Export-loss counter and buffer bounds (code/data follow-up)

Source: [`sdk_buffer_audit.json`](../../results/phase5/sdk_buffer_audit.json).
`NexusClient._run_export_loop()` drains spans, `_export_batch()` calls
`HttpExporter.export()`, and a false return (non-2xx or transport exception)
discards the drained batch. The HTTP exporter makes one attempt, with no retry,
requeue or persistence. That is why the recovery probe's 17 failed-export events
were permanently lost; restarting the collector cannot recover them.

The existing public `client.stats["dropped"]` counted queue-full losses only.
The SDK now additionally exposes `export_failed` (failed-export spans, including
unexpected exporter exceptions) and `dropped_total` (queue-full plus failed
exports). Counters are thread-safe process-lifetime counts, not durable metrics;
the existing `dropped` meaning is preserved. A test verifies a failed 17-span
batch is counted once and never retried, plus exception and newest-drop cases.
This SDK-only observability fix came after L4; its timings were not re-measured.

The default queue is bounded at **10,000 spans**, with **50 spans** per export
batch normally held outside it. A full queue drops the **newest incoming** span,
not the oldest. Configuration can opt out of a count bound: nonpositive
`max_queue_size` uses Python Queue's unbounded mode. There is **no finite
worst-case total memory bound**, even at defaults: metadata/identifiers and
caller-supplied Span fields are unrestricted, explicit pending spans are
unbounded, and serialization creates temporary copies. The default build_span
input/output/error text caps total 4,500 characters/span: 10,000 such spans alone
can hold up to 180,000,000 bytes (171.66 MiB) of Unicode character storage, before
all those other allocations. That is a partial text-storage estimate, not a RAM
limit. The **28.58 MiB added sampled peak RSS** was measured with the collector
**up**, on the registered replay workload; no outage/worst-case memory claim is
supported by that number.
"""
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
