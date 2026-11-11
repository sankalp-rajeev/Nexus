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


@pytest.fixture(autouse=True)
def _audit_to_tmp(tmp_path, monkeypatch):
    """Keep mock proposals out of results/critic_dev/proposals.jsonl (the default path)."""
    monkeypatch.setenv("CRITIC_AUDIT_PATH", str(tmp_path / "audit.jsonl"))


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


def _stored(db, proposal_id) -> bool:
    with db._conn.cursor() as cur:
        cur.execute("SELECT proposal_id FROM patches WHERE proposal_id = %s", (proposal_id,))
        return cur.fetchone() is not None


def test_unapplied_mock_proposal_is_not_written_to_postgres(db, tmp_path, monkeypatch):
    """Phase 3 contract: only an LLM proposal with a clean config dry run is stored."""
    from services.critic.graph import run_critic
    monkeypatch.setenv("CRITIC_AUDIT_PATH", str(tmp_path / "audit.jsonl"))
    proposal = run_critic(_alert(FailureType.TOOL_MISFIRE, "trace_integ_misfire"), db)
    assert not proposal.dry_run_applied and proposal.status == "REJECTED"
    assert not _stored(db, proposal.proposal_id)


def test_critic_writes_applied_llm_proposal_to_postgres_patches_table(db, tmp_path, monkeypatch):
    import json

    from services.critic.evidence import FailureEvidence
    from services.critic.graph import run_critic
    from services.critic.proposal import Provenance

    class Scripted:
        last_provenance = Provenance(source="llm", model="transport-double",
                                     model_version="integration-v1", temperature=0.2,
                                     input_tokens=11, output_tokens=17)

        def complete_patch(self, prompt, **kwargs):
            return json.dumps(dict(
                patch_type="PROMPT_PATCH", target_component="_BASE_SYSTEM",
                explanation="The prompt does not require sufficient grounding from the trace evidence.",
                patch_content="Answer only using the observed tool output. Abstain if context is missing.",
                confidence="MEDIUM",
                estimated_impact="Independent evaluation is required to measure repair quality.",
                root_cause_analysis="The trace output lacks support in the observed tool results."))

    from datetime import datetime, timezone

    from nexus_agent.models import CompleteTrace, Span

    class TraceFromFixture:
        """Real Postgres for writes; the trace read is a fixture (none is stored for this id)."""

        def __init__(self, real):
            self._real = real

        def __getattr__(self, name):
            return getattr(self._real, name)

        def load_trace(self, trace_id):
            now = datetime.now(timezone.utc)
            span = Span(span_id="s", trace_id=trace_id, agent_name="test-agent",
                        span_type="agent_step", input="question", output="Observed output",
                        duration_ms=1, client_timestamp=now, sdk_version="1",
                        metadata={"role": "root"})
            return CompleteTrace(trace_id=trace_id, agent_name="test-agent", started_at=now,
                                 spans=[span])

    monkeypatch.setenv("CRITIC_AUDIT_PATH", str(tmp_path / "audit.jsonl"))
    proposal = run_critic(_alert(FailureType.HALLUCINATION, "trace_integ_applied"),
                          TraceFromFixture(db), llm_factory=lambda **_: Scripted(),
                          current_config={"_BASE_SYSTEM": "Existing prompt value"},
                          evidence=FailureEvidence(failure_type="HALLUCINATION", span_id="s",
                                                   supporting_text="Observed output"))
    assert proposal.provenance.source == "llm" and proposal.dry_run_applied,         proposal.rejection_reasons
    assert _stored(db, proposal.proposal_id), "Applied proposal should be written to Postgres"


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
