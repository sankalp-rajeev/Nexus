"""Offline measurement invariance, durable accounting, and resume safeguards."""
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import sqlite3

import httpx
import pytest

from bench.heal.config import ConfigPatch
from bench.heal.harness import RunStore
from bench.heal.score import Scorer, failure_specs
from bench.llm import CostLedger as AgentLedger, LLMClient, ResponseCache
from services.critic.accounting import CostLedger as CriticLedger
from services.critic.llm import DeepSeekProvider
from scripts.phase5 import measurement as m
from scripts.phase5 import pipeline
from scripts.phase5.prepare import sample_manifest, smoke_items

USAGE = dict(prompt_tokens=100, completion_tokens=10, prompt_cache_hit_tokens=60, prompt_cache_miss_tokens=40)
CREATED = int(datetime(2026, 11, 12, 2, tzinfo=timezone.utc).timestamp())


def response():
    return dict(model="deepseek-flash", system_fingerprint="fixture", created=CREATED, usage=USAGE,
        choices=[dict(finish_reason="tool_calls", message=dict(content='{"answer":"same"}',
            tool_calls=[dict(function=dict(name="propose_patch", arguments='{"same":true}'))]))])


def test_actor_observation_preserves_wire_payload_and_return_value(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fixture-key")
    wire, values = [], []
    def handle(request):
        wire.append((request.content, request.headers["authorization"], str(request.url)))
        return httpx.Response(200, json=response())
    budget = m.Budget(tmp_path / "budget")
    for observed in (False, True):
        name = "observed" if observed else "baseline"
        client = LLMClient("deepseek", "deepseek-flash", ledger=AgentLedger(str(tmp_path / name / "ledger.jsonl")),
                           cache=ResponseCache(str(tmp_path / name / "cache.jsonl")))
        client._http.close()
        inner = httpx.MockTransport(handle)
        transport = m.ObservedTransport(inner, budget, "heal-1") if observed else inner
        with httpx.Client(transport=transport) as http:
            client._http = http
            values.append(client.complete("frozen system", [{"role": "user", "content": "same task"}], max_tokens=50, seed=2))
    assert wire[0] == wire[1]
    assert replace(values[0], latency_ms=0) == replace(values[1], latency_ms=0)
    call = budget.calls()[0]
    assert call["provider_usage"] == USAGE
    assert call["ledger_usd"] == pytest.approx(42e-6)
    assert call["provider_cost"]["cost_usd"] == pytest.approx(24.36e-6)


def test_critic_observation_preserves_strict_payload_and_proposal(tmp_path):
    wire, proposals = [], []
    def handle(request):
        wire.append(request.content)
        return httpx.Response(200, json=response())
    budget = m.Budget(tmp_path / "budget")
    for observed in (False, True):
        inner = httpx.MockTransport(handle)
        with httpx.Client(transport=m.ObservedTransport(inner, budget, "critic") if observed else inner) as http:
            provider = DeepSeekProvider(client=http, api_key="fixture-key",
                ledger=CriticLedger(tmp_path / f"critic-{observed}.jsonl", cap_usd=6))
            proposals.append(provider.complete_patch("unchanged frozen prompt"))
    assert wire[0] == wire[1]
    assert proposals[0] == proposals[1]


def test_credentials_and_other_destinations_are_blocked_before_wire(tmp_path):
    sent = []
    transport = m.ObservedTransport(httpx.MockTransport(lambda r: sent.append(r)), m.Budget(tmp_path), "heal", ["fixture-secret"])
    with httpx.Client(transport=transport) as client:
        with pytest.raises(ValueError, match="Credential"):
            client.post("https://api.deepseek.com/chat/completions", json={"max_tokens": 5, "text": "fixture-secret"})
        with pytest.raises(ValueError, match="DeepSeek only"):
            client.post("https://example.com/chat/completions", json={"max_tokens": 5})
    assert not sent


def test_failed_transport_reservation_survives_restart(tmp_path):
    budget = m.Budget(tmp_path)
    def fail(request):
        raise httpx.ReadTimeout("fixture")
    with httpx.Client(transport=m.ObservedTransport(httpx.MockTransport(fail), budget, "heal")) as http:
        with pytest.raises(httpx.ReadTimeout):
            http.post("https://api.deepseek.com/chat/completions", json={"max_tokens": 400})
    restarted = m.Budget(tmp_path)
    assert restarted.spent() == budget.calls()[0]["reserved_usd"] > 0
    assert restarted.calls()[0]["error"] == "ReadTimeout"
    assert restarted.calls()[0]["status"] == "unknown"


def test_hard_cap_blocks_wire_call_and_persists_stop(tmp_path):
    budget = m.Budget(tmp_path, cap=0.00001)
    sent = []
    with httpx.Client(transport=m.ObservedTransport(httpx.MockTransport(lambda r: sent.append(r)), budget, "heal")) as http:
        with pytest.raises(m.BudgetExceeded, match="cap reached"):
            http.post("https://api.deepseek.com/chat/completions", json={"max_tokens": 800})
    assert not sent
    assert m.Budget(tmp_path, cap=0.00001).stopped()
    assert budget.spent() <= 0.00001


def test_concurrent_reservations_cannot_exceed_the_shared_cap(tmp_path):
    budget = m.Budget(tmp_path, cap=0.003)
    def reserve(index):
        try:
            return budget.reserve(str(index), {"max_tokens": 400})
        except m.BudgetExceeded:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(reserve, range(8)))
    assert sum(x is not None for x in ids) == 2
    restarted = m.Budget(tmp_path, cap=0.003)
    assert restarted.spent() <= 0.003
    assert restarted.spent() == pytest.approx(sum(c["ledger_usd"] for c in restarted.calls()))
    assert restarted.stopped()


def test_provider_cap_reserves_inflight_calls_before_the_wire(tmp_path):
    budget = m.Budget(tmp_path, cap=9.0, provider_cap=0.003)
    def reserve(index):
        try:
            return budget.reserve(str(index), {"max_tokens": 400})
        except m.BudgetExceeded:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(reserve, range(8)))
    state = budget.snapshot()
    assert sum(x is not None for x in ids) == 2
    assert state["stop_reason"] == "provider"
    assert state["provider_actual_usd"] == 0
    assert state["provider_accounted_usd"] <= 0.003
    assert state["ledger_accounted_usd"] < 9.0


def test_provider_settlement_and_unknown_costs_survive_restart(tmp_path):
    budget = m.Budget(tmp_path, cap=9.0, provider_cap=4.0)
    known = budget.reserve("smoke-known", {"max_tokens": 400})
    budget.settle(known, usage=USAGE, provider_model="deepseek-flash", fingerprint="fixture",
                  created=CREATED, status_code=200)
    unknown = budget.reserve("smoke-unknown", {"max_tokens": 400})
    budget.settle(unknown, usage={}, provider_model=None, fingerprint=None, created=None,
                  status_code=None, error="ReadTimeout")
    state = m.Budget(tmp_path).snapshot()
    assert state["provider_actual_usd"] == pytest.approx(24.36e-6)
    assert state["provider_accounted_usd"] == pytest.approx(24.36e-6 + budget.calls()[1]["reserved_usd"])


def test_cap_migration_preserves_smoke_ledger_and_provider_cost(tmp_path):
    row = dict(call_id="old", heal_id="smoke-promoted", status="settled", ledger_usd=42e-6,
               reserved_usd=0.001, provider_cost={"cost_usd": 24.36e-6})
    with sqlite3.connect(tmp_path / "budget.sqlite3") as conn:
        conn.execute("CREATE TABLE budget (id INTEGER PRIMARY KEY, cap REAL, spent REAL, stopped INTEGER)")
        conn.execute("INSERT INTO budget VALUES (1,6,?,0)", (42e-6,))
        conn.execute("CREATE TABLE calls (id TEXT PRIMARY KEY, heal_id TEXT, record TEXT)")
        conn.execute("INSERT INTO calls VALUES ('old','smoke-promoted',?)", (json.dumps(row),))
    budget = m.Budget.configure_smoke_caps(tmp_path)
    assert len(budget.calls()) == 1
    state = budget.snapshot()
    assert state["ledger_cap_usd"] == 9.0
    assert state["provider_cap_usd"] == 4.0
    assert state["ledger_accounted_usd"] == pytest.approx(42e-6)
    assert state["provider_actual_usd"] == pytest.approx(24.36e-6)


def test_usage_prices_follow_peak_boundary_and_preserve_missing_cache_fields():
    assert m.usage_cost(USAGE, datetime(2026, 11, 12, 3, 59, tzinfo=timezone.utc))["price_tier"] == "peak"
    assert m.usage_cost(USAGE, datetime(2026, 11, 12, 4, tzinfo=timezone.utc))["cost_usd"] == pytest.approx(12.18e-6)
    assert m.usage_cost({"prompt_tokens": 100, "completion_tokens": 10}, datetime.now(timezone.utc)) is None
    assert m.usage_cost(dict(USAGE, prompt_cache_miss_tokens=99), datetime.now(timezone.utc)) is None


def test_monotonic_stages_include_failure_and_total(tmp_path, monkeypatch):
    ticks = iter([10, 11, 13, 14])
    monkeypatch.setattr(m.time, "perf_counter", lambda: next(ticks))
    measure = m.Measurement("heal", "dev-trace")
    with pytest.raises(ValueError):
        with measure.stage("detect"):
            raise ValueError("fixture")
    record = measure.finish(m.Budget(tmp_path))
    assert record["stages_s"]["detect"] == 2
    assert record["total_s"] == 4
    assert record["stage_status"]["detect"] == "error"
    assert record["stage_status"]["critic_call"] == "skipped"
    assert datetime.fromisoformat(record["started_at"]).utcoffset() is not None


def test_atomic_completion_and_resume_identity(tmp_path):
    item = dict(item_id="heal", trace_id="dev-trace")
    path = tmp_path / "heal.json"
    assert pipeline.completed(path, item) is None
    m.atomic_json(path, dict(item, complete=True, gate_decision="rejected"))
    assert pipeline.completed(path, item)["gate_decision"] == "rejected"
    with pytest.raises(ValueError, match="identity"):
        pipeline.completed(path, dict(item, trace_id="another"))
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("promoted", [True, False])
def test_instrumented_gate_batches_equal_frozen_scorer(tmp_path, monkeypatch, promoted):
    item = smoke_items()[0]
    patch = ConfigPatch(ops=({"op": "replace", "path": "/MAX_STEPS", "value": 9},))
    def record(spec):
        passing = spec.env_fault == "NONE" or (not spec.patch.is_empty and promoted)
        return dict(run_id=spec.run_id, intended_config_hash=spec.intended_hash(), status="ok",
                    task_id=spec.task_id, env_fault=spec.env_fault, checker_pass=passing,
                    stop_reason="final" if passing else "max_steps", steps=[],
                    final_answer="Insufficient context to answer." if passing else "")
    expected_records = {s.run_id: record(s) for s in [*failure_specs(item, patch, item["regression"]),
                        *failure_specs(item, ConfigPatch.none(), item["regression"])]}
    expected = Scorer(expected_records).score_failure(item, patch, item["regression"])
    class HarnessDouble:
        def __init__(self, **kw):
            self.store = RunStore(kw["runs_path"])
            self.ledger = AgentLedger(str(tmp_path / "actor-ledger.jsonl"))
            self.cache = ResponseCache(str(tmp_path / "actor-cache.jsonl"))
            self._clients = {}
        def execute(self, spec):
            return record(spec)
        def records(self):
            return self.store.by_id
    monkeypatch.setattr(pipeline, "Harness", HarnessDouble)
    monkeypatch.setattr(pipeline, "baseline_records", lambda: {})
    measure = m.Measurement("fixture", item["trace_id"])
    actual = pipeline._evaluate(item, patch, tmp_path / "attempt", m.Budget(tmp_path / "budget"), measure)
    assert actual["gate"] == expected["gate"]
    assert actual["gate_decision"] == ("promoted" if promoted else "rejected")
    assert all(measure.record["stage_status"][s] == "complete" for s in m.STAGES[3:])


def test_seeded_manifest_is_reproducible_and_occurrence_ids_are_unique():
    a, b = sample_manifest(), sample_manifest()
    assert a == b
    assert len(a["items"]) == len({r["item_id"] for r in a["items"]}) == 100
    assert all(i["provider"] == "deepseek" for i in a["items"])
    assert a["population_size"] == 91


def test_controller_skips_complete_heal_without_starting_a_worker(tmp_path, monkeypatch):
    from scripts.phase5 import run
    item = dict(item_id="heal-001", trace_id="dev-only")
    m.atomic_json(tmp_path / "records/heal-001.json", dict(item, complete=True, status="ok"))
    monkeypatch.setattr(run.subprocess, "run", lambda *a, **kw: pytest.fail("completed heal was replayed"))
    assert run.invoke(item, tmp_path, 5)["status"] == "ok"


def test_progress_is_idempotent_and_cap_stop_is_explicit(tmp_path):
    from scripts.phase5 import run
    rec = dict(item_id="heal-001", gate_decision="rejected", total_s=3.2, status="ok")
    run.progress(tmp_path, rec, "heals.log")
    run.progress(tmp_path, rec, "heals.log")
    assert len((tmp_path / "heals.log").read_text().splitlines()) == 1
    with pytest.raises(m.BudgetExceeded):
        m.Budget(tmp_path).reserve("blocked", {"max_tokens": 10_000_000})
    run.progress(tmp_path, rec, "heals.log")
    assert (tmp_path / "heals.log").read_text().splitlines()[-1] == "stopped: cap reached"
