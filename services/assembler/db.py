"""Postgres writer for assembled traces and spans (Section 13.2)."""

from __future__ import annotations

import json
import logging
import os

import psycopg2
import psycopg2.extras

from nexus_agent.models import CompleteTrace

logger = logging.getLogger("nexus.assembler.db")


def dsn_from_env() -> str:
    return (
        f"host={os.getenv('POSTGRES_HOST', 'localhost')} "
        f"port={os.getenv('POSTGRES_PORT', '5432')} "
        f"dbname={os.getenv('POSTGRES_DB', 'nexus')} "
        f"user={os.getenv('POSTGRES_USER', 'nexus')} "
        f"password={os.getenv('POSTGRES_PASSWORD', 'nexus_dev_password')}"
    )


class AssemblerDB:
    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn or dsn_from_env()
        self._conn = None

    def connect(self) -> None:
        self._conn = psycopg2.connect(self.dsn)
        self._conn.autocommit = True

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()

    def write_trace(self, trace: CompleteTrace) -> None:
        """Idempotent upsert of a trace and its spans."""
        if self._conn is None:
            self.connect()
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO traces (trace_id, agent_name, environment, root_input,
                    final_output, span_count, total_duration_ms, started_at,
                    completed_at, status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (trace_id) DO UPDATE SET
                    final_output = EXCLUDED.final_output,
                    span_count = EXCLUDED.span_count,
                    total_duration_ms = EXCLUDED.total_duration_ms,
                    completed_at = EXCLUDED.completed_at,
                    status = EXCLUDED.status
                """,
                (
                    trace.trace_id, trace.agent_name, trace.environment, trace.root_input,
                    trace.final_output, trace.span_count, trace.total_duration_ms,
                    trace.started_at, trace.completed_at, trace.status.value,
                ),
            )
            rows = [
                (
                    s.span_id, s.trace_id, s.parent_span_id, s.agent_name, s.span_type.value,
                    s.input, s.output, s.duration_ms, s.error_type, s.error_message,
                    json.dumps(s.metadata or {}), s.client_timestamp,
                    s.server_timestamp or s.client_timestamp,
                )
                for s in trace.spans
            ]
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO spans (span_id, trace_id, parent_span_id, agent_name,
                    span_type, input, output, duration_ms, error_type, error_message,
                    metadata, client_timestamp, server_timestamp)
                VALUES %s
                ON CONFLICT DO NOTHING
                """,
                rows,
            )
        logger.info("nexus-assembler: wrote trace %s (%d spans)", trace.trace_id, trace.span_count)
