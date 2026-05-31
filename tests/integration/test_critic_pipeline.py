"""Integration test: Alert -> LangGraph critic -> PatchProposal in Postgres.

Skips if Postgres is not reachable at localhost:55432.
"""

from __future__ import annotations

import os
import socket

import pytest

from nexus_agent.models import Alert, FailureType

os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "55432")


def _pg_available() -> bool:
    try:
        s = socket.create_connection(("localhost", 55432), timeout=1)
        s.close()
        return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _pg_available(), reason="Postgres not running on localhost:55432")


@pytest.fixture(scope="module")
def db():
    from services.critic.db import CriticDB
    d = CriticDB()
    d.connect()
    yield d
    d.close()


def _alert(failure_type: FailureType, trace_id: str) -> Alert:
    return Alert(trace_id=trace_id, agent_name="test-agent", failure_type=failure_type)


def test_critic_produces_patch_for_hallucination(db):
    from services.critic.graph import run_critic
    alert = _alert(FailureType.HALLUCINATION, "trace_integ_hall")
    proposal = run_critic(alert, db)
    assert proposal is not None
    assert proposal.failure_type == FailureType.HALLUCINATION
    assert len(proposal.explanation) >= 10
    assert len(proposal.patch_content) >= 10


def test_critic_produces_patch_for_loop_detected(db):
    from services.critic.graph import run_critic
    alert = _alert(FailureType.LOOP_DETECTED, "trace_integ_loop")
    proposal = run_critic(alert, db)
    assert proposal is not None
    assert proposal.patch_type.value in ("PROMPT_PATCH", "TOOL_CONFIG_PATCH", "MEMORY_PATCH", "RETRY_POLICY_PATCH")


def test_critic_writes_to_postgres_patches_table(db):
    from services.critic.graph import run_critic
    alert = _alert(FailureType.TOOL_MISFIRE, "trace_integ_misfire")
    proposal = run_critic(alert, db)
    with db._conn.cursor() as cur:
        cur.execute("SELECT proposal_id FROM patches WHERE proposal_id = %s", (proposal.proposal_id,))
        row = cur.fetchone()
    assert row is not None, "Patch proposal should be written to Postgres"


def test_critic_retry_loop_on_vague_proposal(db):
    """Mock provider returns a valid proposal so no retry is needed;
    verify retry_count stays 0 when valid."""
    from services.critic.graph import build_graph
    from unittest.mock import MagicMock

    mock_db = MagicMock()
    mock_db.load_trace.return_value = None
    mock_db.write_patch.return_value = None

    alert = _alert(FailureType.PLAN_DRIFT, "trace_integ_drift")
    graph = build_graph(mock_db)
    result = graph.invoke({
        "alert_id": alert.alert_id,
        "trace_id": alert.trace_id,
        "agent_name": alert.agent_name,
        "failure_type": alert.failure_type.value,
        "failure_span_id": None,
        "retry_count": 0,
        "validation_passed": False,
        "patch_proposal": None,
        "final_proposal": None,
        "root_cause_analysis": "",
    })
    assert result["final_proposal"] is not None
    assert result["retry_count"] == 0


def test_critic_produces_patch_for_all_5_failure_types(db):
    from services.critic.graph import run_critic

    types = [
        FailureType.HALLUCINATION,
        FailureType.CONTEXT_BLEED,
        FailureType.PLAN_DRIFT,
        FailureType.TOOL_MISFIRE,
        FailureType.LOOP_DETECTED,
    ]
    for ft in types:
        alert = _alert(ft, f"trace_integ_{ft.value.lower()}_all5")
        proposal = run_critic(alert, db)
        assert proposal is not None, f"No proposal for {ft.value}"
        assert proposal.failure_type == ft
