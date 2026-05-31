"""Benchmark SDK instrumentation overhead (Phase 2 exit criterion: < 5ms/span).

Measures per-call wall time of an instrumented vs. uninstrumented no-op function
using timeit. The collector is NOT required: export happens off the hot path on
a background thread, so overhead is just span construction + a queue put.

    python examples/raw_llm_call/benchmark_overhead.py
"""

from __future__ import annotations

import timeit

import nexus_agent as nexus

N = 10_000


def _baseline(x: int) -> int:
    return x + 1


def main() -> None:
    nexus.init(agent_name="bench", async_export=True, collector_url="http://127.0.0.1:1")

    @nexus.trace(span_type="custom")
    def instrumented(x: int) -> int:
        return x + 1

    base = timeit.timeit(lambda: _baseline(1), number=N) / N
    inst = timeit.timeit(lambda: instrumented(1), number=N) / N
    overhead_ms = (inst - base) * 1000.0

    print(f"baseline    : {base * 1e6:8.2f} us/call")
    print(f"instrumented: {inst * 1e6:8.2f} us/call")
    print(f"overhead    : {overhead_ms:8.3f} ms/call  (target < 5ms)")
    print("PASS" if overhead_ms < 5.0 else "FAIL")
    nexus.shutdown()


if __name__ == "__main__":
    main()
