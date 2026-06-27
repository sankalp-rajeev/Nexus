"""Unit tests for healer.patch_applicator and healer.slack_notifier."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock


from services.healer.patch_applicator import apply_patch, _extract_agent_name
from services.healer.slack_notifier import notify_patch_proposal


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _mock_conn():
    conn = MagicMock()
    cur = MagicMock()
    cur.__enter__ = lambda s: s
    cur.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value = cur
    return conn


def _proposal(patch_type="TOOL_CONFIG_PATCH"):
    return {
        "proposal_id": str(uuid.uuid4()),
        "alert_id": str(uuid.uuid4()),
        "trace_id": "trace_test_001",
        "failure_type": "TOOL_MISFIRE",
        "patch_type": patch_type,
        "target_component": "my_agent:search_tool",
        "explanation": "Empty query string passed to search tool",
        "patch_content": "Validate query is non-empty before dispatch",
        "confidence": "HIGH",
        "estimated_impact": "Eliminates empty-query errors",
        "root_cause_analysis": "Missing input validation",
        "status": "PENDING_REVIEW",
        "created_at": datetime.now(timezone.utc),
    }


# ── patch_applicator tests ────────────────────────────────────────────────────

class TestPatchApplicator:
    def test_apply_patch_writes_to_db(self):
        conn = _mock_conn()
        prop = _proposal()
        config_id = apply_patch(prop, conn)
        assert config_id  # non-empty
        assert conn.cursor.called
        assert conn.commit.called

    def test_apply_patch_notifies_redis_for_tool_config(self):
        conn = _mock_conn()
        redis = MagicMock()
        prop = _proposal("TOOL_CONFIG_PATCH")
        apply_patch(prop, conn, redis)
        redis.publish.assert_called_once()
        channel = redis.publish.call_args[0][0]
        assert "my_agent" in channel

    def test_apply_patch_no_redis_publish_for_memory_patch(self):
        conn = _mock_conn()
        redis = MagicMock()
        prop = _proposal("MEMORY_PATCH")
        apply_patch(prop, conn, redis)
        redis.publish.assert_not_called()

    def test_apply_patch_no_redis_client(self):
        conn = _mock_conn()
        prop = _proposal()
        # Should not raise even without redis
        config_id = apply_patch(prop, conn, redis_client=None)
        assert config_id

    def test_extract_agent_name_from_component(self):
        prop = {"target_component": "my_agent:search_tool", "agent_name": None}
        name = _extract_agent_name(prop)
        assert name == "my_agent"

    def test_extract_agent_name_prefers_agent_name_field(self):
        prop = {"agent_name": "explicit_agent", "target_component": "other:tool"}
        name = _extract_agent_name(prop)
        assert name == "explicit_agent"


# ── slack_notifier tests ──────────────────────────────────────────────────────

class TestSlackNotifier:
    def test_no_webhook_returns_false(self):
        prop = _proposal()
        result = notify_patch_proposal(prop, webhook_url="")
        assert result is False

    def test_message_structure(self):
        """Verify the message dict has all required Slack block keys."""
        from services.healer.slack_notifier import _build_message
        prop = _proposal()
        msg = _build_message(prop)
        assert "text" in msg
        assert "blocks" in msg
        assert len(msg["blocks"]) >= 3
        # First block contains failure type
        assert "TOOL_MISFIRE" in msg["text"]
