"""Phase 6 SDK hardening: one retry, byte cap, config validation, counters, long outage."""

from __future__ import annotations

import ctypes
import os
import queue
import random
import socket
import threading
import time
import tracemalloc
from pathlib import Path

import pytest

import nexus_agent as nexus
from nexus_agent.client import SPAN_OVERHEAD_BYTES, NexusClient, estimate_span_bytes
from nexus_agent.config import NexusConfig
from nexus_agent.models import SpanType

MIB = 1024 * 1024


class FakeExporter:
    """Scriptable exporter: outcomes[i] is the result of call i (default: last/``default``)."""

    def __init__(self, outcomes=(), default=True, block: threading.Event | None = None):
        self.outcomes = list(outcomes)
        self.default = default
        self.block = block
        self.batches: list = []
        self.lock = threading.Lock()

    @property
    def calls(self) -> int:
        return len(self.batches)

    def export(self, batch):
        with self.lock:
            index = len(self.batches)
            self.batches.append(batch)
        if self.block is not None:
            self.block.wait(timeout=30)
        if index < len(self.outcomes):
            result = self.outcomes[index]
            if isinstance(result, Exception):
                raise result
            return result
        return self.default

    def close(self):
        pass


@pytest.fixture
def make_client():
    clients: list[NexusClient] = []

    def factory(exporter=None, **overrides):
        overrides.setdefault("export_retry_backoff_min_ms", 1)
        overrides.setdefault("export_retry_backoff_max_ms", 2)
        client = NexusClient(NexusConfig(agent_name="hardening", **overrides))
        if exporter is not None:
            client._exporter.close()
            client._exporter = exporter
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.shutdown()


def make_span(client, i, text="", metadata=None):
    return client.build_span(span_type=SpanType.CUSTOM, span_id=f"s{i}", trace_id="t",
                             parent_span_id=None, input_text=text, output_text=None,
                             duration_ms=1.0, metadata=metadata)


def wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def assert_invariant(stats):
    assert stats["produced"] == stats["exported"] + stats["dropped_total"] + stats["queued"], stats
    assert stats["dropped"] == stats["dropped_queue_full"] + stats["dropped_bytes_cap"]
    assert stats["dropped_total"] == stats["dropped"] + stats["export_failed"] + stats["dropped_shutdown"]


# ── Config validation ────────────────────────────────────────────────
@pytest.mark.parametrize("field", ["max_queue_size", "max_queue_bytes"])
@pytest.mark.parametrize("value", [0, -1, -10_000])
def test_non_positive_queue_limits_are_rejected(field, value):
    with pytest.raises(ValueError, match=field):
        NexusConfig(agent_name="a", **{field: value})


@pytest.mark.parametrize("field", ["max_queue_size", "max_queue_bytes"])
@pytest.mark.parametrize("value", [True, 1.5, "10", None])
def test_non_integer_queue_limits_are_rejected(field, value):
    with pytest.raises(ValueError, match=field):
        NexusConfig(agent_name="a", **{field: value})


def test_init_rejects_unbounded_queue_before_starting_anything():
    with pytest.raises(ValueError, match="max_queue_size"):
        nexus.init(agent_name="a", max_queue_size=0)
    assert not nexus.is_initialized()


@pytest.mark.parametrize("lo,hi", [(-1, 10), (50, 10)])
def test_bad_backoff_is_rejected(lo, hi):
    with pytest.raises(ValueError, match="backoff"):
        NexusConfig(agent_name="a", export_retry_backoff_min_ms=lo, export_retry_backoff_max_ms=hi)


def test_defaults_match_documented_values():
    cfg = NexusConfig(agent_name="a")
    assert cfg.shutdown_timeout_ms == 5000
    assert cfg.max_queue_size == 10_000
    assert cfg.max_queue_bytes == 32 * MIB
    assert (cfg.export_retry_backoff_min_ms, cfg.export_retry_backoff_max_ms) == (100, 300)


# ── Retry ────────────────────────────────────────────────────────────
def test_retry_succeeds_on_second_attempt_with_same_batch(make_client):
    exporter = FakeExporter(outcomes=[False], default=True)
    client = make_client(exporter)
    for i in range(3):
        client.record(make_span(client, i))
    assert wait_for(lambda: client.stats["exported"] == 3)
    client.shutdown()
    stats = client.stats
    assert stats["export_retried"] == 1
    assert stats["export_failed"] == 0 and stats["dropped_total"] == 0
    assert exporter.batches[0] is exporter.batches[1]  # same batch_id and span ids on the retry
    assert_invariant(stats)


def test_retry_exhaustion_drops_and_counts_after_exactly_one_retry(make_client):
    exporter = FakeExporter(default=False)
    client = make_client(exporter)
    for i in range(4):
        client.record(make_span(client, i))
    assert wait_for(lambda: exporter.calls >= 2 and client.stats["export_failed"] > 0)
    client.shutdown()
    stats = client.stats
    assert stats["exported"] == 0
    assert stats["export_failed"] == 4 and stats["dropped_total"] == 4
    assert stats["export_retried"] >= 1
    # Every batch is attempted at most twice (original + one retry), never more.
    ids = [b.batch_id for b in exporter.batches]
    assert max(ids.count(i) for i in set(ids)) <= 2
    assert_invariant(stats)


def test_exporter_exception_is_retried_then_counted_fail_silent(make_client):
    exporter = FakeExporter(outcomes=[RuntimeError("boom"), RuntimeError("boom")], default=True)
    client = make_client(exporter)
    client.record(make_span(client, 0))
    assert wait_for(lambda: client.stats["export_failed"] == 1)
    client.shutdown()
    assert client.stats["export_retried"] == 1
    assert_invariant(client.stats)


def test_sync_mode_and_flush_never_retry(make_client):
    sync_exporter = FakeExporter(default=False)
    sync = make_client(sync_exporter, async_export=False)
    sync.record(make_span(sync, 0))
    assert sync_exporter.calls == 1 and sync.stats["export_retried"] == 0

    exporter = FakeExporter(default=False)
    client = make_client(exporter, export_retry_backoff_min_ms=1, export_retry_backoff_max_ms=1)
    client._stop.set()  # park the worker so flush() is the only exporter
    client._worker.join(timeout=5)
    client._stop.clear()
    for i in range(3):
        client.record(make_span(client, i))
    client.flush()
    assert exporter.calls == 1 and client.stats["export_retried"] == 0
    assert client.stats["export_failed"] == 3
    assert_invariant(client.stats)


def test_shutdown_interrupts_backoff_and_skips_retry(make_client):
    exporter = FakeExporter(default=False)
    client = make_client(exporter, export_retry_backoff_min_ms=5000, export_retry_backoff_max_ms=5000)
    client.record(make_span(client, 0))
    assert wait_for(lambda: exporter.calls == 1)
    time.sleep(0.05)  # worker is now sleeping in its 5 s backoff
    started = time.perf_counter()
    client.shutdown()
    elapsed = time.perf_counter() - started
    assert elapsed < 1.0, elapsed  # the 5 s backoff did not delay shutdown
    stats = client.stats
    assert exporter.calls == 1 and stats["export_retried"] == 0
    assert stats["export_failed"] == 1
    assert_invariant(stats)


def test_retry_jitter_does_not_consume_application_random_stream(make_client):
    random.seed(1234)
    expected = [random.random() for _ in range(3)]
    random.seed(1234)
    client = make_client(FakeExporter(outcomes=[False], default=True))
    client.record(make_span(client, 0))
    assert wait_for(lambda: client.stats["exported"] == 1)
    assert client.stats["export_retried"] == 1
    assert [random.random() for _ in range(3)] == expected


# ── Byte cap ─────────────────────────────────────────────────────────
def test_byte_cap_drops_newest_and_is_enforced_with_large_spans(make_client):
    gate = threading.Event()
    exporter = FakeExporter(default=True, block=gate)  # worker stuck in-flight, queue fills
    cap = 1 * MIB
    client = make_client(exporter, max_queue_bytes=cap, max_input_chars=200_000)
    big = 100_000
    first = make_span(client, 0, text="a" * big)
    client.record(first)
    assert wait_for(lambda: exporter.calls == 1)  # in-flight spans still count against the cap
    for i in range(1, 31):
        client.record(make_span(client, i, text=chr(97 + i % 26) * big))
        assert client.stats["queued_bytes_estimate"] <= cap
    stats = client.stats
    assert stats["dropped_bytes_cap"] > 0 and stats["dropped_queue_full"] == 0
    assert stats["dropped"] == stats["dropped_bytes_cap"]
    with client._queue.mutex:  # snapshot without consuming, so accounting stays intact
        kept = [item[0].span_id for item in client._queue.queue]
    assert len(kept) == stats["queued"] and kept
    assert kept == [f"s{i}" for i in range(1, 1 + len(kept))]  # earliest kept, newest dropped
    gate.set()
    client.shutdown()
    final = client.stats
    assert final["queued_bytes_estimate"] == 0
    assert_invariant(final)


def test_single_span_larger_than_cap_is_dropped_not_raised(make_client):
    client = make_client(FakeExporter(), max_queue_bytes=10_000, max_input_chars=100_000)
    client.record(make_span(client, 0, text="x" * 50_000))
    client.record(make_span(client, 1, text="ok"))
    client.shutdown()
    stats = client.stats
    assert stats["dropped_bytes_cap"] == 1 and stats["exported"] == 1
    assert_invariant(stats)


def test_count_cap_still_applies_and_is_counted_separately(make_client):
    gate = threading.Event()
    exporter = FakeExporter(default=True, block=gate)
    client = make_client(exporter, max_queue_size=5)
    client.record(make_span(client, 0))
    assert wait_for(lambda: exporter.calls == 1)
    for i in range(1, 21):
        client.record(make_span(client, i))
    stats = client.stats
    assert stats["queued"] == 5 and stats["dropped_queue_full"] == 15
    assert stats["dropped_bytes_cap"] == 0 and stats["dropped"] == 15
    gate.set()
    client.shutdown()
    assert_invariant(client.stats)


def test_estimate_is_cheap_constant_plus_text_and_never_raises():
    client = NexusClient(NexusConfig(agent_name="e", async_export=False))
    try:
        empty = make_span(client, 0)
        base = estimate_span_bytes(empty)
        assert base >= SPAN_OVERHEAD_BYTES
        grown = make_span(client, 0, text="x" * 1000, metadata={"k": "y" * 500, "b": b"z" * 100})
        assert estimate_span_bytes(grown) - base >= 1600  # text + metadata strings/bytes

        class NoSerialise:
            def __repr__(self):  # would raise if the estimator tried repr()/JSON
                raise AssertionError("estimator must not serialise")

        cyclic: dict = {}
        cyclic["self"] = cyclic
        weird = make_span(client, 1, metadata={"obj": NoSerialise(), "loop": cyclic,
                                               "nested": [[["deep"]]], "wide": list(range(10_000))})
        assert estimate_span_bytes(weird) > SPAN_OVERHEAD_BYTES  # terminates, no exception
    finally:
        client.shutdown()


# ── Never blocks or raises ───────────────────────────────────────────
def test_capture_never_blocks_or_raises_with_slow_or_raising_exporter(make_client):
    slow = make_client(FakeExporter(default=True, block=threading.Event()))
    started = time.perf_counter()
    for i in range(300):
        slow.record(make_span(slow, i))
    assert time.perf_counter() - started < 1.0
    slow._exporter.block.set()

    raising = make_client(FakeExporter(outcomes=[RuntimeError("x")] * 1000, default=True))
    for i in range(50):
        raising.record(make_span(raising, i))  # must not raise
    raising.flush()


def test_record_survives_estimator_or_queue_internal_errors(make_client):
    class BrokenQueue(queue.Queue):
        def put_nowait(self, item):
            raise RuntimeError("unexpected")

    client = make_client(FakeExporter())
    client._queue = BrokenQueue(maxsize=10)  # worker keeps its own reference semantics via self._queue
    client.record(make_span(client, 0, text="abc"))  # must not raise
    stats = client.stats
    assert stats["produced"] == 1 and stats["export_failed"] == 1  # counted, invariant intact
    assert stats["queued_bytes_estimate"] == 0  # reservation was released
    assert_invariant(stats)


# ── Sustained outage: bounded memory, invariant holds ────────────────
def _rss_reader():
    if os.name == "nt":
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
                (n, ctypes.c_size_t) for n in ("peak_working_set", "working_set", "a", "b", "c", "d",
                                              "pagefile", "peak_pagefile", "private")]

        kernel = ctypes.WinDLL("kernel32")
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.WinDLL("psapi")
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]

        def read():
            c = Counters()
            c.cb = ctypes.sizeof(c)
            psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(c), c.cb)
            return c.working_set

        return read
    return lambda: int(Path("/proc/self/statm").read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE")


def _closed_loopback_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_long_outage_memory_stays_near_cap_and_counters_balance():
    """Collector down (closed loopback port); ~190 MiB of spans produced against a 32 MiB cap."""
    cap = 32 * MIB
    client = NexusClient(NexusConfig(
        agent_name="outage", collector_url=f"http://127.0.0.1:{_closed_loopback_port()}",
        export_timeout_ms=50, max_input_chars=200_000, max_queue_bytes=cap, max_batch_size=10,
        export_retry_backoff_min_ms=20, export_retry_backoff_max_ms=40))
    read_rss = _rss_reader()
    span_chars, total = 128 * 1024, 1500  # distinct 128 KiB strings: ~188 MiB produced
    assert span_chars * total > 5 * cap
    peak_rss = baseline_rss = read_rss()
    stop = threading.Event()

    def sample():
        nonlocal peak_rss
        while not stop.is_set():
            peak_rss = max(peak_rss, read_rss())
            stop.wait(0.005)

    sampler = threading.Thread(target=sample, daemon=True)
    tracemalloc.start()
    base_heap = tracemalloc.get_traced_memory()[0]
    sampler.start()
    slowest = 0.0
    try:
        for i in range(total):
            span = make_span(client, i, text=("%08d" % i) + "x" * (span_chars - 8))
            started = time.perf_counter()
            client.record(span)  # must neither raise nor block
            slowest = max(slowest, time.perf_counter() - started)
            del span
            time.sleep(0.0005)  # sustained production while the exporter keeps failing
        mid = client.stats
        peak_heap = tracemalloc.get_traced_memory()[1] - base_heap
    finally:
        tracemalloc.stop()
        stop.set()
        sampler.join(timeout=5)
    started = time.perf_counter()
    client.shutdown()
    shutdown_s = time.perf_counter() - started

    stats = client.stats
    assert stats["produced"] == total
    assert stats["exported"] == 0  # collector never came back
    assert stats["dropped_bytes_cap"] > total // 2  # most production was refused at the cap
    assert stats["dropped_queue_full"] == 0  # byte cap, not count cap, bound this workload
    assert stats["export_retried"] >= 1  # the background thread did retry while it could
    assert stats["queued_bytes_estimate"] == 0
    assert_invariant(stats)
    assert mid["queued_bytes_estimate"] <= cap
    # Memory: traced Python heap and process RSS stay near the cap, not near the ~188 MiB produced.
    # (Exporting a batch transiently adds ~2x that batch for JSON encoding: 10 x 128 KiB here.)
    print(f"\nlong-outage: produced={stats['produced']} dropped_bytes_cap={stats['dropped_bytes_cap']} "
          f"retried={stats['export_retried']} failed={stats['export_failed']} "
          f"heap_peak={peak_heap / MIB:.1f}MiB rss_growth={(peak_rss - baseline_rss) / MIB:.1f}MiB "
          f"slowest_record={slowest * 1000:.2f}ms shutdown={shutdown_s:.2f}s")
    assert peak_heap <= cap * 1.25, peak_heap / MIB
    assert peak_rss - baseline_rss <= cap * 2, (peak_rss - baseline_rss) / MIB
    assert slowest < 0.5, slowest
    assert shutdown_s < 10, shutdown_s


# -- Shutdown deadline ------------------------------------------------
@pytest.mark.parametrize("value", [0, -1, True, 1.5, "5", None])
def test_bad_shutdown_timeout_is_rejected(value):
    with pytest.raises(ValueError, match="shutdown_timeout_ms"):
        NexusConfig(agent_name="a", shutdown_timeout_ms=value)


class SlowFailingExporter(FakeExporter):
    def __init__(self, delay):
        super().__init__(default=False)
        self.delay = delay

    def export(self, batch):
        time.sleep(self.delay)
        return super().export(batch)


def test_shutdown_deadline_bounds_a_long_outage_with_a_full_queue_and_counts_exactly(make_client):
    """Collector down, queue full: shutdown returns at the deadline; every span is accounted for."""
    exporter = SlowFailingExporter(delay=0.05)  # each failed attempt takes ~50 ms
    client = make_client(exporter, max_queue_size=2000, max_batch_size=50, export_timeout_ms=50,
                         shutdown_timeout_ms=60_000)  # the per-call timeout below must win
    total = 2000
    for i in range(total):
        client.record(make_span(client, i))
    assert client.stats["produced"] == total and client.stats["dropped_total"] == 0
    # Draining 40 batches at ~50 ms each (plus the retry) would take 2 s or more.
    deadline = 0.3
    started = time.perf_counter()
    client.shutdown(timeout=deadline)
    elapsed = time.perf_counter() - started
    assert deadline <= elapsed <= deadline + 0.5, elapsed  # deadline + one attempt + join grace
    stats = client.stats
    attempted = {}
    for batch in exporter.batches:
        attempted[batch.batch_id] = len(batch.spans)
    assert stats["exported"] == 0 and stats["queued"] == 0
    assert stats["export_failed"] == sum(attempted.values())  # every attempted batch counted once
    assert stats["dropped_shutdown"] == total - sum(attempted.values()) > 0
    assert stats["dropped_total"] == stats["export_failed"] + stats["dropped_shutdown"]
    assert stats["queued_bytes_estimate"] == 0
    assert_invariant(stats)
    # Idempotent: a second shutdown (e.g. atexit) changes nothing.
    client.shutdown(timeout=0.1)
    assert client.stats == stats


def test_shutdown_default_comes_from_config(make_client):
    exporter = SlowFailingExporter(delay=0.05)
    client = make_client(exporter, max_queue_size=2000, export_timeout_ms=50, shutdown_timeout_ms=200)
    for i in range(1500):
        client.record(make_span(client, i))
    started = time.perf_counter()
    client.shutdown()  # no argument: config default (200 ms)
    assert time.perf_counter() - started <= 0.2 + 0.5
    assert client.stats["dropped_shutdown"] > 0
    assert_invariant(client.stats)


def test_shutdown_drains_fully_when_healthy_and_drops_nothing(make_client):
    exporter = FakeExporter(default=True)
    client = make_client(exporter, max_queue_size=5000)
    for i in range(3000):
        client.record(make_span(client, i))
    client.shutdown()
    stats = client.stats
    assert stats["exported"] == 3000 and stats["dropped_shutdown"] == 0 and stats["dropped_total"] == 0
    assert_invariant(stats)


def test_stuck_inflight_export_is_abandoned_at_the_deadline_without_double_counting(make_client):
    gate = threading.Event()
    exporter = FakeExporter(default=True, block=gate)  # the worker's export hangs
    client = make_client(exporter, export_timeout_ms=50)
    client.record(make_span(client, 0))
    assert wait_for(lambda: exporter.calls == 1)  # the worker is now stuck in flight
    for i in range(1, 11):
        client.record(make_span(client, i))
    started = time.perf_counter()
    client.shutdown(timeout=0.2)
    elapsed = time.perf_counter() - started
    assert elapsed <= 0.2 + 0.1 + 0.4, elapsed  # deadline + join grace (2 x 50 ms) + margin
    stats = client.stats
    assert stats["dropped_shutdown"] == 11 and stats["exported"] == 0 and stats["export_failed"] == 0
    assert_invariant(stats)
    gate.set()  # the stuck attempt now finishes; it must not be counted a second time
    time.sleep(0.3)
    assert client.stats == stats


def test_flush_is_unchanged_and_has_no_deadline(make_client):
    exporter = SlowFailingExporter(delay=0.02)
    client = make_client(exporter, max_queue_size=500, shutdown_timeout_ms=1)
    client._stop.set()
    client._worker.join(timeout=5)
    client._stop.clear()
    for i in range(200):
        client.record(make_span(client, i))
    client.flush()  # 4 batches x 20 ms, far beyond the 1 ms shutdown deadline: all attempted
    stats = client.stats
    assert stats["export_failed"] == 200 and stats["dropped_shutdown"] == 0
    assert_invariant(stats)


def test_module_level_shutdown_passes_the_timeout_through():
    client = nexus.init(agent_name="timeout-passthrough", max_queue_size=100)
    client._exporter.close()
    client._exporter = SlowFailingExporter(delay=0.05)
    for i in range(100):
        client.record(make_span(client, i))
    started = time.perf_counter()
    nexus.shutdown(timeout=0.15)
    assert time.perf_counter() - started <= 0.15 + 0.6
    assert not nexus.is_initialized()
    assert_invariant(client.stats)
