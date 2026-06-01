"""Postgres connection + query helpers for the API service."""

from __future__ import annotations

import os
from typing import Any

import psycopg2
import psycopg2.extras


def get_connection():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "nexus"),
        user=os.getenv("POSTGRES_USER", "nexus"),
        password=os.getenv("POSTGRES_PASSWORD", "nexus_dev_password"),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


def query(conn, sql: str, params=()) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def execute(conn, sql: str, params=()) -> None:
    with conn.cursor() as cur:
        cur.execute(sql, params)
    conn.commit()


# ── Spans ─────────────────────────────────────────────────────────────────────

def fetch_recent_spans(conn, limit: int = 50) -> list[dict]:
    return query(conn, """
        SELECT span_id, trace_id, agent_name, span_type, input, output,
               duration_ms, error_type, error_message, metadata,
               server_timestamp
        FROM spans
        ORDER BY server_timestamp DESC
        LIMIT %s
    """, (limit,))


# ── Traces ────────────────────────────────────────────────────────────────────

def fetch_recent_traces(conn, limit: int = 50, agent_name: str | None = None) -> list[dict]:
    base = """
        SELECT trace_id, agent_name, environment, root_input, final_output,
               span_count, total_duration_ms, started_at, completed_at, status
        FROM traces
    """
    if agent_name:
        return query(conn, base + "WHERE agent_name=%s ORDER BY started_at DESC LIMIT %s",
                     (agent_name, limit))
    return query(conn, base + "ORDER BY started_at DESC LIMIT %s", (limit,))


# ── Patches ───────────────────────────────────────────────────────────────────

def fetch_patches(conn, status: str | None = None, limit: int = 50) -> list[dict]:
    if status:
        return query(conn, """
            SELECT * FROM patches WHERE status=%s ORDER BY created_at DESC LIMIT %s
        """, (status, limit))
    return query(conn, """
        SELECT * FROM patches
        ORDER BY CASE status
            WHEN 'PENDING_REVIEW' THEN 0 ELSE 1 END,
            created_at DESC LIMIT %s
    """, (limit,))


def update_patch_status(conn, proposal_id: str, status: str) -> bool:
    execute(conn, "UPDATE patches SET status=%s WHERE proposal_id=%s",
            (status, proposal_id))
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM patches WHERE proposal_id=%s AND status=%s",
                    (proposal_id, status))
        return cur.fetchone() is not None


# ── Eval runs (patch history with before/after scores) ────────────────────────

def fetch_eval_runs(conn, limit: int = 50) -> list[dict]:
    return query(conn, """
        SELECT e.run_id, e.patch_id, e.trace_id, e.agent_name,
               e.before_score, e.after_score, e.score_delta,
               e.per_metric_scores, e.eval_duration_ms, e.mlflow_run_id,
               e.created_at,
               p.failure_type, p.patch_type, p.target_component
        FROM eval_runs e
        LEFT JOIN patches p ON e.patch_id = p.proposal_id
        ORDER BY e.created_at DESC LIMIT %s
    """, (limit,))


# ── Agent health ──────────────────────────────────────────────────────────────

def fetch_agent_health(conn) -> list[dict]:
    """Rolling 1-hour composite score per agent from eval_runs."""
    return query(conn, """
        SELECT
            e.agent_name,
            AVG(e.after_score) AS health_score,
            COUNT(*) AS eval_count,
            MAX(e.created_at) AS last_eval_at,
            p.failure_type AS last_failure_type
        FROM eval_runs e
        LEFT JOIN patches p ON e.patch_id = p.proposal_id
        WHERE e.created_at >= NOW() - INTERVAL '1 hour'
        GROUP BY e.agent_name, p.failure_type
        ORDER BY e.agent_name
    """)


def fetch_alerts_timeline(conn) -> list[dict]:
    """Failure counts bucketed by hour over the last 24 hours."""
    return query(conn, """
        SELECT
            date_trunc('hour', created_at) AS bucket,
            failure_type,
            COUNT(*) AS count
        FROM alerts
        WHERE created_at >= NOW() - INTERVAL '24 hours'
        GROUP BY bucket, failure_type
        ORDER BY bucket ASC
    """)
