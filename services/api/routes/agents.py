"""Agent health score endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from services.api.db import fetch_agent_health, get_connection

router = APIRouter()


def _conn():
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


@router.get("/v1/agents/health")
def get_agent_health(conn=Depends(_conn)):
    """Rolling 1-hour health score per instrumented agent."""
    try:
        return fetch_agent_health(conn)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
