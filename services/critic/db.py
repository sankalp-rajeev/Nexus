"""Postgres helpers for the critic: load trace, write patch proposal."""

from __future__ import annotations

import logging
import os
import json
from pathlib import Path
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras

from nexus_agent.models import CompleteTrace, PatchProposal, Span, SpanType, TraceStatus

logger = logging.getLogger("nexus.critic.db")


def dsn_from_env() -> str:
    return (
        f"host={os.getenv('POSTGRES_HOST', 'localhost')} "
        f"port={os.getenv('POSTGRES_PORT', '5432')} "
        f"dbname={os.getenv('POSTGRES_DB', 'nexus')} "
        f"user={os.getenv('POSTGRES_USER', 'nexus')} "
        f"password={os.getenv('POSTGRES_PASSWORD', 'nexus_dev_password')}"
    )


class CriticDB:
    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn or dsn_from_env()
        self._conn = None

    def connect(self) -> None:
        self._conn = psycopg2.connect(self.dsn)
        self._conn.autocommit = True

    def close(self) -> None:
        if self._conn:
            self._conn.close()

    def _ensure(self) -> None:
        if self._conn is None:
            self.connect()

    def load_trace(self, trace_id: str) -> CompleteTrace | None:
        self._ensure()
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM traces WHERE trace_id = %s", (trace_id,)
            )
            row = cur.fetchone()
            if row is None:
                return None
            cur.execute(
                "SELECT * FROM spans WHERE trace_id = %s ORDER BY client_timestamp",
                (trace_id,),
            )
            span_rows = cur.fetchall()

        spans = [
            Span(
                span_id=r["span_id"],
                trace_id=r["trace_id"],
                parent_span_id=r.get("parent_span_id"),
                agent_name=r["agent_name"],
                span_type=SpanType(r["span_type"]),
                input=r.get("input"),
                output=r.get("output"),
                duration_ms=float(r["duration_ms"] or 0),
                error_type=r.get("error_type"),
                error_message=r.get("error_message"),
                metadata=r.get("metadata") or {},
                client_timestamp=r["client_timestamp"],
                server_timestamp=r.get("server_timestamp"),
                sdk_version="1.0.0",
            )
            for r in span_rows
        ]
        return CompleteTrace(
            trace_id=row["trace_id"],
            agent_name=row["agent_name"],
            environment=row.get("environment"),
            root_input=row.get("root_input"),
            final_output=row.get("final_output"),
            span_count=int(row["span_count"]),
            total_duration_ms=float(row.get("total_duration_ms") or 0),
            started_at=row["started_at"],
            completed_at=row.get("completed_at"),
            status=TraceStatus(row["status"]),
            spans=spans,
        )

    def load_config(self, agent_name: str) -> dict:
        """Read only keys already registered for this specific agent."""
        self._ensure()
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT DISTINCT ON (component_name) component_name, content, config_type "
                "FROM agent_configs WHERE agent_name = %s ORDER BY component_name, version DESC",
                (agent_name,),
            )
            return {r["component_name"]: (r["content"] if r["config_type"] == "prompt"
                    else json.loads(r["content"])) for r in cur.fetchall()}

    def record_attempt(self, proposal) -> None:
        """Keep provenance/rejections durably while shared SQL schema stays frozen."""
        path = Path(os.getenv("CRITIC_AUDIT_PATH", "results/critic_dev/proposals.jsonl"))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as audit:
            audit.write(proposal.model_dump_json() + "\n")

    def write_patch(self, proposal: PatchProposal) -> None:
        if (not hasattr(proposal, "provenance") or proposal.provenance.source != "llm"
                or not proposal.dry_run_applied or proposal.status == "REJECTED"):
            raise ValueError("Only proposals with a clean config dry run can be stored")
        self._ensure()
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO patches (
                    proposal_id, alert_id, trace_id, failure_type, patch_type,
                    target_component, explanation, patch_content, confidence,
                    estimated_impact, root_cause_analysis, created_at, status
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (proposal_id) DO NOTHING
                """,
                (
                    proposal.proposal_id, proposal.alert_id, proposal.trace_id,
                    proposal.failure_type.value, proposal.patch_type.value,
                    proposal.target_component, proposal.explanation,
                    proposal.patch_content, proposal.confidence,
                    proposal.estimated_impact, proposal.root_cause_analysis,
                    proposal.created_at or datetime.now(timezone.utc), proposal.status,
                ),
            )
        logger.info("nexus-critic: wrote patch %s (type=%s)", proposal.proposal_id, proposal.patch_type.value)
