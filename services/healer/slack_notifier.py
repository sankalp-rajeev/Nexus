"""Slack webhook notifier for patch proposals.

Posts a rich message to a configured Slack channel when a PatchProposal
arrives, with a summary of the failure type, proposed fix, and confidence.

If SLACK_WEBHOOK_URL is not set, this module is a no-op.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger("nexus.healer.slack_notifier")


def notify_patch_proposal(
    proposal: dict[str, Any],
    webhook_url: str | None = None,
) -> bool:
    """POST patch proposal summary to Slack. Returns True if successful."""
    url = webhook_url or os.getenv("SLACK_WEBHOOK_URL", "")
    if not url:
        logger.debug("healer: SLACK_WEBHOOK_URL not set — skipping Slack notification")
        return False

    message = _build_message(proposal)
    try:
        import urllib.request
        data = json.dumps(message).encode("utf-8")
        req = urllib.request.Request(url, data=data,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            ok = resp.status == 200
        if ok:
            logger.info("healer: Slack notification sent for patch %s",
                        proposal.get("proposal_id"))
        return ok
    except Exception as exc:
        logger.warning("healer: Slack notification failed: %s", exc)
        return False


def _build_message(proposal: dict[str, Any]) -> dict:
    pid = proposal.get("proposal_id", "?")[:8]
    failure = proposal.get("failure_type", "UNKNOWN")
    patch_type = proposal.get("patch_type", "?")
    component = proposal.get("target_component", "?")
    confidence = proposal.get("confidence", "?")
    explanation = (proposal.get("explanation") or "")[:200]
    content_preview = (proposal.get("patch_content") or "")[:300]

    return {
        "text": f":warning: *Nexus Patch Proposal* `{pid}` — `{failure}`",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f":warning: *Nexus Patch Proposal* `{pid}`\n"
                        f"*Failure:* `{failure}` | *Type:* `{patch_type}` | "
                        f"*Component:* `{component}` | *Confidence:* `{confidence}`"
                    ),
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Root cause:* {explanation}",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Proposed patch:*\n```{content_preview}```",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "_Autonomous mode: patch will be applied automatically._",
                },
            },
        ],
    }
