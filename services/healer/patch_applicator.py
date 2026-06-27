"""Patch applicator — writes PatchProposal content to the Config Store
(agent_configs table) and notifies agent runtimes via Redis pub/sub.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("nexus.healer.patch_applicator")

_REDIS_NOTIFY_TYPES = {"PROMPT_PATCH", "TOOL_CONFIG_PATCH", "RETRY_POLICY_PATCH"}


def apply_patch(proposal: dict[str, Any], conn, redis_client=None) -> str:
    """Write the patch to agent_configs and mark the proposal as APPLIED.

    Returns the config_id created/updated.
    """
    proposal_id = proposal["proposal_id"]
    agent_name = proposal.get("agent_name") or _extract_agent_name(proposal)
    patch_type = proposal["patch_type"]
    component = proposal["target_component"]
    content = proposal["patch_content"]

    config_id = _upsert_agent_config(
        conn=conn,
        agent_name=agent_name,
        component_name=component,
        config_type=patch_type.lower().replace("_patch", ""),
        content=content,
        applied_patch_id=proposal_id,
    )

    _mark_applied(conn, proposal_id)

    if redis_client and patch_type in _REDIS_NOTIFY_TYPES:
        channel = f"nexus:config:update:{agent_name}"
        payload = json.dumps({
            "config_id": config_id,
            "patch_type": patch_type,
            "component": component,
            "agent_name": agent_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        try:
            redis_client.publish(channel, payload)
            logger.info("healer: published config update to %s", channel)
        except Exception as exc:
            logger.warning("healer: Redis publish failed: %s", exc)

    logger.info("healer: applied patch %s -> config_id=%s", proposal_id, config_id)
    return config_id


def _upsert_agent_config(conn, agent_name, component_name, config_type,
                         content, applied_patch_id) -> str:
    config_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO agent_configs
                (config_id, agent_name, component_name, config_type,
                 content, version, applied_patch_id, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, 1, %s, %s, %s)
            ON CONFLICT (config_id) DO UPDATE SET
                content = EXCLUDED.content,
                version = agent_configs.version + 1,
                applied_patch_id = EXCLUDED.applied_patch_id,
                updated_at = EXCLUDED.updated_at
        """, (config_id, agent_name, component_name, config_type,
              content, applied_patch_id, now, now))
    conn.commit()
    return config_id


def _mark_applied(conn, proposal_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE patches SET status='APPLIED', applied_at=%s WHERE proposal_id=%s",
            (datetime.now(timezone.utc), proposal_id),
        )
    conn.commit()


def _extract_agent_name(proposal: dict) -> str:
    for key in ("agent_name", "target_component"):
        val = proposal.get(key, "")
        if val:
            return val.split(":")[0]
    return "unknown_agent"
