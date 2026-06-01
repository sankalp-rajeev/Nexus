"""Postgres helpers for the healer service."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg2

logger = logging.getLogger("nexus.healer.db")


def get_connection():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "nexus"),
        user=os.getenv("POSTGRES_USER", "nexus"),
        password=os.getenv("POSTGRES_PASSWORD", "nexus_dev_password"),
    )


def fetch_pending_patches(conn, limit: int = 10) -> list[dict[str, Any]]:
    """Return PENDING_REVIEW patches ordered by created_at ASC."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT proposal_id, alert_id, trace_id, failure_type, patch_type,
                   target_component, explanation, patch_content, confidence,
                   estimated_impact, root_cause_analysis, status, created_at
            FROM patches
            WHERE status = 'PENDING_REVIEW'
            ORDER BY created_at ASC
            LIMIT %s
        """, (limit,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def fetch_trace(conn, trace_id: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT trace_id, agent_name, root_input, final_output, status
            FROM traces WHERE trace_id = %s
        """, (trace_id,))
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))


def write_eval_run(
    conn,
    patch_id: str,
    trace_id: str,
    agent_name: str,
    before_score: float,
    after_score: float,
    per_metric_scores: dict,
    eval_duration_ms: float,
    mlflow_run_id: str | None,
) -> str:
    run_id = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO eval_runs
                (run_id, patch_id, trace_id, agent_name, before_score,
                 after_score, per_metric_scores, eval_duration_ms, mlflow_run_id, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            run_id, patch_id, trace_id, agent_name,
            before_score, after_score,
            psycopg2.extras.Json(per_metric_scores) if per_metric_scores else "{}",
            eval_duration_ms, mlflow_run_id,
            datetime.now(timezone.utc),
        ))
    conn.commit()
    return run_id
