"""Slack notifications via a client-provided Incoming Webhook URL -- no
OAuth app, no Slack App Directory review needed. Each account connects
its own Slack workspace by pasting a webhook URL it creates itself
(Slack -> Incoming Webhooks -> Add New Webhook), the same pattern as
alerting.py's founder-level webhook, just per-client instead of global.
"""

import logging

import httpx

logger = logging.getLogger("postmortem_ai")


async def notify_slack(webhook_url: str | None, message: str) -> None:
    if not webhook_url:
        return
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(webhook_url, json={"text": message})
    except httpx.HTTPError:
        # Never let a Slack delivery failure interrupt the action that
        # triggered it (publishing a postmortem) -- log and move on.
        logger.warning("slack_notify_failed", exc_info=True)
