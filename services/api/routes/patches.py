"""Patch proposal endpoints — list, approve, reject."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from services.api.db import (
    fetch_patches,
    get_connection,
    update_patch_status,
)

router = APIRouter()


def _conn():
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


@router.get("/v1/patches")
def get_patches(
    status: str | None = Query(None),
    limit: int = Query(50, le=200),
    conn=Depends(_conn),
):
    try:
        return fetch_patches(conn, status=status, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/v1/patches/{proposal_id}/approve")
def approve_patch(proposal_id: str, conn=Depends(_conn)):
    try:
        ok = update_patch_status(conn, proposal_id, "APPROVED")
        if not ok:
            raise HTTPException(status_code=404, detail="Patch not found")
        return {"status": "APPROVED", "proposal_id": proposal_id}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/v1/patches/{proposal_id}/reject")
def reject_patch(proposal_id: str, conn=Depends(_conn)):
    try:
        ok = update_patch_status(conn, proposal_id, "REJECTED")
        if not ok:
            raise HTTPException(status_code=404, detail="Patch not found")
        return {"status": "REJECTED", "proposal_id": proposal_id}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/v1/patches/history")
def get_patch_history(limit: int = Query(50, le=200), conn=Depends(_conn)):
    """Eval runs with before/after scores for PatchHistory panel."""
    try:
        from services.api.db import fetch_eval_runs
        return fetch_eval_runs(conn, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
