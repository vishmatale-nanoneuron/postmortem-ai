"""Real alerting, not just logging: when something is actually broken
(the drafting model has failed repeatedly and the circuit breaker has
opened), a webhook fires immediately instead of the founder having to
notice it in Vercel logs. Optional -- ALERT_WEBHOOK_URL unset means this
is a no-op, same "degrade gracefully when unconfigured" stance as UPI/wire
payment details.

Deliberately generic (a plain HTTP POST), not Slack-specific: works with a
Slack incoming webhook, a Discord webhook, or any other endpoint that
accepts a JSON POST -- the founder picks where alerts go by choosing the
URL, not by this code assuming a specific provider.
"""

import logging

import httpx

logger = logging.getLogger("postmortem_ai")


async def send_alert(webhook_url: str | None, message: str) -> None:
    if not webhook_url:
        return
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # {"text": ...} is the Slack incoming-webhook shape; most
            # other webhook receivers (Discord included) also accept or
            # ignore an unrecognized top-level "text" field harmlessly.
            await client.post(webhook_url, json={"text": message})
    except httpx.HTTPError:
        # An alert delivery failure must never become an unhandled
        # exception in the request path that triggered it -- log and move
        # on, the same best-effort stance as RAG retrieval/embedding.
        logger.warning("alert_delivery_failed", exc_info=True)
