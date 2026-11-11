"""Single-process demo pipeline: bounded queue, deterministic detectors, SQLite.

The critic uses its existing generic fallback directly; no model or LLM calls.
One worker owns processing, and SQLite transactions commit spans and derived
artifacts together. Queue acceptance is volatile until the worker commits.
"""

from __future__ import annotations

import json
import logging
import queue
import sqlite3
import threading
import time
from datetime import timedelta

from nexus_agent.models import Alert, CompleteTrace, FailureType, Span

from services.critic.fallback import make_fallback_proposal
from services.detectors import bleed, drift, rules

logger = logging.getLogger("nexus.collector.lite")


class LiteSpanProducer:
    def __init__(self, path: str, capacity: int = 1000) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        self._conn.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS spans (
                span_id TEXT NOT NULL, trace_id TEXT NOT NULL, body TEXT NOT NULL,
                PRIMARY KEY(trace_id, span_id));
            CREATE INDEX IF NOT EXISTS spans_trace ON spans(trace_id);
            CREATE TABLE IF NOT EXISTS artifacts (
                kind TEXT NOT NULL, id TEXT NOT NULL, trace_id TEXT NOT NULL,
                body TEXT NOT NULL, PRIMARY KEY(kind, id));
        """)
        self._queue = queue.Queue(maxsize=capacity)
        self._closed = False
        self.processing_errors = 0
        self._thread = threading.Thread(target=self._work, name="nexus-lite", daemon=True)
        self._thread.start()

    def produce_span(self, trace_id: str, value: dict) -> None:
        span = Span.model_validate(value)
        if span.trace_id != trace_id:
            raise ValueError("queue key differs from span trace_id")
        with self._lock:
            if self._closed:
                raise RuntimeError("Lite queue is closed")
            self._queue.put_nowait(span)

    def _work(self) -> None:
        while True:
            span = self._queue.get()
            try:
                if span is None:
                    return
                self._process(span)
            except Exception:  # noqa: BLE001
                self.processing_errors += 1
                logger.exception("Lite processing failed; queue is degraded")
            finally:
                self._queue.task_done()

    def _process(self, span: Span) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO spans VALUES (?, ?, ?)",
                (span.span_id, span.trace_id, span.model_dump_json()),
            )
            spans = [Span.model_validate_json(r[0]) for r in self._conn.execute(
                "SELECT body FROM spans WHERE trace_id=?", (span.trace_id,)
            )]
            spans.sort(key=lambda s: (s.client_timestamp, s.span_id))
            root = next((s for s in reversed(spans) if s.parent_span_id is None), None)
            completed = max(s.client_timestamp + timedelta(milliseconds=s.duration_ms) for s in spans)
            trace = CompleteTrace(
                trace_id=span.trace_id, agent_name=span.agent_name,
                environment=span.environment, spans=spans, span_count=len(spans),
                root_input=root.input if root else None,
                final_output=root.output if root else None,
                started_at=spans[0].client_timestamp,
                completed_at=completed if root else None,
                status="completed" if root else "in_progress",
                total_duration_ms=(completed - spans[0].client_timestamp).total_seconds() * 1000,
            )
            self._save("traces", trace.trace_id, trace.trace_id, trace.model_dump(mode="json"))
            # No NLI model download or optional LLM judge in lite mode.
            flags = {
                "LOOP_DETECTED": rules.loop(trace),
                "TOOL_MISFIRE": rules.misfire(trace),
                "CONTEXT_BLEED": (bleed.score(trace) or 0) >= 1,
                "PLAN_DRIFT": bool(root) and drift.flags(trace).get("ungrounded_any_source", False),
            }
            for failure, fired in flags.items():
                if not fired:
                    continue
                alert = Alert(
                    alert_id=f"lite-{trace.trace_id}-{failure}", trace_id=trace.trace_id,
                    agent_name=trace.agent_name, failure_type=FailureType(failure),
                )
                # Idempotent on retried deliveries and accumulating trace snapshots.
                if self._conn.execute(
                    "SELECT 1 FROM artifacts WHERE kind='alerts' AND id=?", (alert.alert_id,)
                ).fetchone():
                    continue
                proposal = make_fallback_proposal(
                    alert.alert_id, trace.trace_id, alert.failure_type,
                    "Lite deterministic detector; generic fallback only, no LLM analysis.",
                )
                proposal.proposal_id = f"{alert.alert_id}-fallback"
                self._save("alerts", alert.alert_id, trace.trace_id, alert.model_dump(mode="json"))
                body = proposal.model_dump(mode="json")
                body["source"] = "generic_fallback_no_llm"
                self._save("proposals", proposal.proposal_id, trace.trace_id, body)
                self._save("gate_decisions", proposal.proposal_id, trace.trace_id, {
                    "proposal_id": proposal.proposal_id, "trace_id": trace.trace_id,
                    "status": "placeholder", "decision": None,
                    "reason": "Phase 4 pending; no evaluation or application in lite mode.",
                })

    def _save(self, kind: str, key: str, trace_id: str, body: dict) -> None:
        self._conn.execute("INSERT OR REPLACE INTO artifacts VALUES (?, ?, ?, ?)",
                           (kind, key, trace_id, json.dumps(body)))

    def snapshot(self) -> dict:
        with self._lock:
            result = {kind: [] for kind in ("traces", "alerts", "proposals", "gate_decisions")}
            for kind, body in self._conn.execute("SELECT kind, body FROM artifacts ORDER BY kind, id"):
                result[kind].append(json.loads(body))
            return result

    def is_connected(self, timeout: float = 1.0) -> bool:
        return not self._closed and self._thread.is_alive() and self.processing_errors == 0

    def flush(self, timeout: float = 5.0) -> int:
        deadline = time.monotonic() + timeout
        with self._queue.all_tasks_done:
            while self._queue.unfinished_tasks:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._queue.all_tasks_done.wait(remaining)
            return self._queue.unfinished_tasks + self.processing_errors

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        # Graceful shutdown drains accepted spans before closing SQLite.
        self._queue.put(None)
        self._thread.join()
        self._conn.close()
