"""Measurement-only clocks, wire-response observation and durable hard budget.

No detector, prompt, patch, gate or outcome rule is implemented here.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import time
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx

STAGES = ("detect", "classify", "critic_call", "gate_repair", "gate_heldout", "gate_regression")
PRICING_URL = "https://api-docs.deepseek.com/quick_start/pricing/"


class BudgetExceeded(RuntimeError):
    pass


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    with temporary.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, sort_keys=True, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def usage_cost(usage, at):
    """Published USD schedule applied to API-reported usage, not an invoice."""
    tin, tout = usage.get("prompt_tokens"), usage.get("completion_tokens")
    hit = usage.get("prompt_cache_hit_tokens")
    if not all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in (tin, tout, hit)):
        return None
    miss = usage.get("prompt_cache_miss_tokens", tin - hit)
    if not isinstance(miss, int) or miss < 0 or miss + hit != tin:
        return None
    utc = at.astimezone(timezone.utc)
    peak = utc.weekday() < 5 and (1 <= utc.hour < 4 or 6 <= utc.hour < 10)
    rates = (0.006, 0.30, 1.20) if peak else (0.003, 0.15, 0.60)
    return dict(input_tokens=tin, cache_hit_input_tokens=hit, cache_miss_input_tokens=miss,
                output_tokens=tout, cache_miss_source="reported" if "prompt_cache_miss_tokens" in usage else "prompt_tokens_minus_reported_hits",
                cost_usd=(hit * rates[0] + miss * rates[1] + tout * rates[2]) / 1e6,
                price_tier="peak" if peak else "off_peak", rates_per_million=list(rates),
                pricing_source=PRICING_URL, pricing_verified="2026-11-11",
                cost_basis="reported_usage_times_published_rates; not provider invoice")


class Budget:
    """One cross-process budget; pending/unknown attempts retain reservations."""
    def __init__(self, root, cap=None, provider_cap=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "budget.sqlite3"
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE IF NOT EXISTS budget (id INTEGER PRIMARY KEY, cap REAL NOT NULL, spent REAL NOT NULL, stopped INTEGER NOT NULL, provider_cap REAL NOT NULL, provider_spent REAL NOT NULL, provider_accounted REAL NOT NULL, stop_reason TEXT)")
            conn.execute("CREATE TABLE IF NOT EXISTS calls (id TEXT PRIMARY KEY, heal_id TEXT NOT NULL, record TEXT NOT NULL)")
            conn.execute("CREATE INDEX IF NOT EXISTS calls_by_heal ON calls(heal_id)")
            columns = {r[1] for r in conn.execute("PRAGMA table_info(budget)")}
            if "provider_cap" not in columns:
                for definition in ("provider_cap REAL NOT NULL DEFAULT 4.0", "provider_spent REAL NOT NULL DEFAULT 0", "provider_accounted REAL NOT NULL DEFAULT 0", "stop_reason TEXT"):
                    conn.execute("ALTER TABLE budget ADD COLUMN " + definition)
                actual = accounted = 0.0
                for call_id, encoded in conn.execute("SELECT id, record FROM calls").fetchall():
                    row = json.loads(encoded)
                    cost = row.get("provider_cost")
                    known = cost["cost_usd"] if cost is not None else None
                    if known is None and row.get("ledger_usd") == 0:
                        known = 0.0
                    row["provider_actual_usd"] = known
                    row["provider_accounted_usd"] = known if known is not None else row["reserved_usd"]
                    row["provider_reserved_usd"] = row["reserved_usd"]
                    actual += known or 0.0
                    accounted += row["provider_accounted_usd"]
                    conn.execute("UPDATE calls SET record=? WHERE id=?", (json.dumps(row, allow_nan=False), call_id))
                conn.execute("UPDATE budget SET provider_spent=?, provider_accounted=? WHERE id=1", (actual, accounted))
            conn.execute("INSERT OR IGNORE INTO budget VALUES (1, ?, 0, 0, ?, 0, 0, NULL)", (9.0 if cap is None else cap, 4.0 if provider_cap is None else provider_cap))
            self.cap, self.provider_cap = conn.execute("SELECT cap, provider_cap FROM budget WHERE id=1").fetchone()
            if cap is not None and self.cap != cap or provider_cap is not None and self.provider_cap != provider_cap:
                raise ValueError("Cannot change an existing run's budget cap")

    @classmethod
    def configure_smoke_caps(cls, root, cap=9.0, provider_cap=4.0):
        """Apply the user's accepted-smoke cap amendment once; keep every call."""
        budget = cls(root)
        with budget.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if any(not json.loads(r[0])["heal_id"].startswith("smoke-") for r in conn.execute("SELECT record FROM calls")):
                raise ValueError("Caps cannot be amended after the main run has started")
            pending = [r for r in budget.calls() if r["status"] != "settled"]
            if pending:
                raise ValueError("Smoke calls must be settled before the cap amendment")
            conn.execute("UPDATE budget SET cap=?, provider_cap=?, stopped=0, stop_reason=NULL WHERE id=1", (cap, provider_cap))
        return cls(root, cap=cap, provider_cap=provider_cap)

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=60)
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    def reserve(self, heal_id, body):
        # Every text byte plus schema/protocol overhead is a conservative token bound.
        bound = len(json.dumps(body, ensure_ascii=True).encode("utf-8")) + 2048
        amount = (bound * 0.30 + int(body["max_tokens"]) * 1.20) / 1e6
        call_id = uuid4().hex
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            spent, stopped, provider_accounted = conn.execute("SELECT spent, stopped, provider_accounted FROM budget WHERE id=1").fetchone()
            ledger_limit = spent >= self.cap or spent + amount > self.cap
            provider_limit = provider_accounted >= self.provider_cap or provider_accounted + amount > self.provider_cap
            if stopped or ledger_limit or provider_limit:
                reason = "ledger_and_provider" if ledger_limit and provider_limit else "ledger" if ledger_limit else "provider"
                conn.execute("UPDATE budget SET stopped=1, stop_reason=COALESCE(stop_reason, ?) WHERE id=1", (reason,))
                conn.commit()
                raise BudgetExceeded("stopped: cap reached")
            row = dict(call_id=call_id, heal_id=heal_id, status="reserved",
                ledger_usd=amount, reserved_usd=amount, started_at=datetime.now(timezone.utc).isoformat(),
                model=body.get("model"), temperature=body.get("temperature"), provider_usage=None,
                provider_cost=None, error=None, provider_actual_usd=None,
                provider_accounted_usd=amount, provider_reserved_usd=amount)
            conn.execute("INSERT INTO calls VALUES (?, ?, ?)", (call_id, heal_id, json.dumps(row, allow_nan=False)))
            conn.execute("UPDATE budget SET spent=spent+?, provider_accounted=provider_accounted+? WHERE id=1", (amount, amount))
        return call_id

    def settle(self, call_id, *, usage, provider_model, fingerprint, created, status_code, error=None):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = json.loads(conn.execute("SELECT record FROM calls WHERE id=?", (call_id,)).fetchone()[0])
            previous_cost = row["ledger_usd"]
            previous_actual = row.get("provider_actual_usd") or 0.0
            previous_accounted = row.get("provider_accounted_usd", row["reserved_usd"])
            at = datetime.fromtimestamp(created, timezone.utc) if isinstance(created, (int, float)) else datetime.fromisoformat(row["started_at"])
            reported = usage_cost(usage, at)
            tin, tout = usage.get("prompt_tokens"), usage.get("completion_tokens")
            known = all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in (tin, tout))
            if known:
                ledger = (tin * 0.30 + tout * 1.20) / 1e6
            elif status_code is not None and 400 <= status_code < 500:
                ledger = 0.0
            else:
                ledger = row["reserved_usd"]
            if ledger > row["reserved_usd"] + 1e-12:
                raise RuntimeError("Token usage exceeded conservative reservation; STOP")
            provider_actual = reported["cost_usd"] if reported is not None else 0.0 if ledger == 0 else None
            provider_accounted = provider_actual if provider_actual is not None else row["provider_reserved_usd"]
            if provider_accounted > row["provider_reserved_usd"] + 1e-12:
                raise RuntimeError("Provider cost exceeded conservative reservation; STOP")
            row.update(status="settled" if known or ledger == 0 else "unknown", ledger_usd=ledger,
                       provider_usage=usage, provider_cost=reported, provider_model=provider_model,
                       system_fingerprint=fingerprint, response_created=created, http_status=status_code,
                       ended_at=datetime.now(timezone.utc).isoformat(), error=error,
                       provider_actual_usd=provider_actual, provider_accounted_usd=provider_accounted)
            conn.execute("UPDATE calls SET record=? WHERE id=?", (json.dumps(row, allow_nan=False), call_id))
            conn.execute("UPDATE budget SET spent=spent+?, provider_spent=provider_spent+?, provider_accounted=provider_accounted+? WHERE id=1",
                         (ledger - previous_cost, (provider_actual or 0.0) - previous_actual, provider_accounted - previous_accounted))
            ledger_total, provider_total = conn.execute("SELECT spent, provider_accounted FROM budget WHERE id=1").fetchone()
            if ledger_total >= self.cap or provider_total >= self.provider_cap:
                reason = "ledger" if ledger_total >= self.cap else "provider"
                conn.execute("UPDATE budget SET stopped=1, stop_reason=COALESCE(stop_reason, ?) WHERE id=1", (reason,))

    def calls(self, heal_id=None):
        with self.connect() as conn:
            rows = conn.execute("SELECT record FROM calls ORDER BY rowid") if heal_id is None else conn.execute("SELECT record FROM calls WHERE heal_id=? ORDER BY rowid", (heal_id,))
            return [json.loads(r[0]) for r in rows]

    def spent(self):
        with self.connect() as conn:
            return conn.execute("SELECT spent FROM budget WHERE id=1").fetchone()[0]

    def stopped(self):
        with self.connect() as conn:
            return bool(conn.execute("SELECT stopped FROM budget WHERE id=1").fetchone()[0])

    def snapshot(self):
        with self.connect() as conn:
            row = conn.execute("SELECT cap, spent, provider_cap, provider_spent, provider_accounted, stopped, stop_reason FROM budget WHERE id=1").fetchone()
        return dict(zip(("ledger_cap_usd", "ledger_accounted_usd", "provider_cap_usd", "provider_actual_usd",
                         "provider_accounted_usd", "stopped", "stop_reason"), row))


class ObservedTransport(httpx.BaseTransport):
    """Pass requests/responses through unchanged; persist usage from actual wire calls."""
    def __init__(self, inner, budget, heal_id, forbidden_values=()):
        self.inner, self.budget, self.heal_id = inner, budget, heal_id
        self.forbidden_values = tuple(v.encode("utf-8") for v in forbidden_values if v)

    def handle_request(self, request):
        if request.url.scheme != "https" or request.url.host != "api.deepseek.com" or request.url.path not in {"/chat/completions", "/beta/chat/completions"}:
            raise ValueError("Phase 5 transport permits DeepSeek only")
        if any(value in request.content for value in self.forbidden_values):
            raise ValueError("Credential detected in request body; blocked before transmission")
        body = json.loads(request.content)
        call_id = self.budget.reserve(self.heal_id, body)
        response = None
        data = {}
        error = None
        try:
            response = self.inner.handle_request(request)
            response.read()
            try:
                data = response.json()
                if not isinstance(data, dict):
                    data = {}
            except (ValueError, UnicodeError):
                pass
            if response.status_code >= 400:
                error = f"HTTP_{response.status_code}"
            return response
        except BaseException as exc:
            error = type(exc).__name__
            raise
        finally:
            self.budget.settle(call_id, usage=data.get("usage") or {}, provider_model=data.get("model"),
                fingerprint=data.get("system_fingerprint"), created=data.get("created"),
                status_code=response.status_code if response is not None else None, error=error)

    def close(self):
        self.inner.close()


def observed_client(budget, heal_id, timeout):
    # Build the ordinary frozen-runtime client first, preserving proxy, TLS and
    # connection-pool settings. Observe each selected transport without rerouting.
    client = httpx.Client(timeout=timeout)
    forbidden = []
    env_path = Path(__file__).resolve().parents[2] / ".env"
    for line in env_path.read_text(encoding="utf-8-sig").splitlines() if env_path.exists() else []:
        if line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if any(part in key.upper() for part in ("KEY", "TOKEN", "SECRET", "PASSWORD", "WEBHOOK")):
            value = value.split(" #")[0].strip().strip('"').strip("'")
            if value:
                forbidden.append(value)
    client._transport = ObservedTransport(client._transport, budget, heal_id, forbidden)
    client._mounts = {pattern: ObservedTransport(transport, budget, heal_id, forbidden) if transport is not None else None
                      for pattern, transport in client._mounts.items()}
    return client


class Measurement:
    def __init__(self, item_id, trace_id):
        self.started = time.perf_counter()
        self.record = dict(item_id=item_id, trace_id=trace_id,
            started_at=datetime.now(ZoneInfo("America/New_York")).isoformat(),
            stages_s={s: 0.0 for s in STAGES}, stage_status={s: "not_run" for s in STAGES},
            model_id="deepseek-flash", temperature={"critic": 0.2, "agent": 0.0},
            gate_decision=None, status="running", complete=False)

    @contextmanager
    def stage(self, name):
        if name not in STAGES:
            raise ValueError(name)
        start = time.perf_counter()
        self.record["stage_status"][name] = "running"
        try:
            yield
        except BaseException:
            self.record["stage_status"][name] = "error"
            raise
        else:
            self.record["stage_status"][name] = "complete"
        finally:
            self.record["stages_s"][name] += time.perf_counter() - start

    def finish(self, budget):
        calls = budget.calls(self.record["item_id"])
        provider_known = all(c["provider_cost"] is not None for c in calls)
        provider_usd = sum(c["provider_cost"]["cost_usd"] for c in calls) if provider_known else None
        ledger_usd = sum(c["ledger_usd"] for c in calls)
        tokens = lambda field: sum(c["provider_cost"][field] for c in calls) if provider_known else None
        self.record.update(ended_at=datetime.now(ZoneInfo("America/New_York")).isoformat(),
            total_s=time.perf_counter() - self.started, complete=True,
            ledger=dict(cost_usd=ledger_usd,
                input_tokens=sum((c["provider_usage"] or {}).get("prompt_tokens", 0) for c in calls),
                output_tokens=sum((c["provider_usage"] or {}).get("completion_tokens", 0) for c in calls),
                unknown_calls=sum(c["status"] != "settled" for c in calls)),
            provider=dict(cost_usd=provider_usd, input_tokens=tokens("input_tokens"),
                cache_hit_input_tokens=tokens("cache_hit_input_tokens"), cache_miss_input_tokens=tokens("cache_miss_input_tokens"),
                output_tokens=tokens("output_tokens"), cost_basis="API usage times published rates; not invoice"),
            ledger_provider_cost_ratio=ledger_usd / provider_usd if provider_usd else None,
            calls=calls, error_count=sum(bool(c["error"]) for c in calls),
            timeout_count=sum(c["error"] in {"ReadTimeout", "ConnectTimeout", "WriteTimeout", "PoolTimeout"} for c in calls))
        for stage, status in self.record["stage_status"].items():
            if status == "not_run":
                self.record["stage_status"][stage] = "skipped"
        return self.record
