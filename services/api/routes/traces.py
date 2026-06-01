"""Span + trace endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from services.api.db import fetch_recent_spans, fetch_recent_traces, get_connection

router = APIRouter()


def _conn():
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


@router.get("/v1/spans")
def get_spans(limit: int = Query(50, le=200), conn=Depends(_conn)):
    try:
        return fetch_recent_spans(conn, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/v1/traces")
def get_traces(
    limit: int = Query(50, le=200),
    agent_name: str | None = Query(None),
    conn=Depends(_conn),
):
    try:
        return fetch_recent_traces(conn, limit=limit, agent_name=agent_name)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/v1/timeline")
def get_timeline(conn=Depends(_conn)):
    """Failure counts bucketed by hour for FailureTimeline chart."""
    try:
        from services.api.db import fetch_alerts_timeline
        return fetch_alerts_timeline(conn)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
