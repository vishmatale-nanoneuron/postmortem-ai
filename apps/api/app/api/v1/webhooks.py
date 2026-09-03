"""Real incident-source webhook ingestion -- lets an external tool
(monitoring, alerting, a CI job, a script -- anything that can POST JSON)
create evidence without a signed-in browser session. Closes the gap that
existed until now: evidence could only ever be typed in by hand through the
authenticated app, even though this product's whole premise is grounding a
postmortem in evidence recorded as an incident actually unfolds -- which,
for most real incidents, means alerts firing automatically, not someone
copy-pasting them in after the fact.

The generic endpoint below is deliberately not source-specific -- it's
exactly what create_incident / record_evidence already accept, the same
write path authenticated differently, and it's what Datadog's webhook
integration should be pointed at directly: Datadog's own webhook payload
is entirely user-templated (no fixed schema Datadog imposes -- see
docs/PAGERDUTY_DATADOG_WEBHOOKS.md), so there's nothing to adapt on this
end. PagerDuty is different: its v3 webhook subscriptions send one fixed,
non-customizable JSON envelope, so `receive_pagerduty_webhook` below
parses that specific shape. Its field names (event.event_type,
event.data.id/title/status/urgency/created_at) are corroborated across
PagerDuty's own v3 webhook docs and independent integration guides
(Sumo Logic's PagerDuty V3 integration doc), not a single unverified
guess -- see docs/PAGERDUTY_DATADOG_WEBHOOKS.md for the sources. Still
defensive throughout (missing/renamed fields degrade gracefully) since
this wasn't tested against a live PagerDuty account.
"""

import logging
import secrets
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from ...ai.model_router import create_model_provider
from ...auth import User, current_user, user_by_webhook_token
from ...database import Database
from ...dependencies import get_database
from ...security.rate_limit import try_record_action
from ...settings import Settings, get_settings
from .postmortems import _draft_postmortem_for_incident, log_activity

logger = logging.getLogger("postmortem_ai")

router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])

# Same shape/reasoning as postmortems.py's own per-account write limits --
# bounds real database writes an unauthenticated-by-session caller can
# trigger per account, independent of that file's own limits.
MAX_WEBHOOK_EVENTS_PER_HOUR = 100
RATE_LIMITED_DETAIL = "Too many requests. Try again later."


class WebhookTokenOut(BaseModel):
    token: str


@router.get("/token", response_model=WebhookTokenOut)
async def get_webhook_token(
    database: Database = Depends(get_database),
    user: User = Depends(current_user),
) -> WebhookTokenOut:
    """The account's current webhook token -- every account has one from
    creation (see migration 0019), this just surfaces it for the frontend
    to build the real URL (NEXT_PUBLIC_API_BASE + /v1/webhooks/incidents/
    {token}) without hardcoding the path in two places."""
    row = await database.fetch_one("SELECT webhook_token FROM users WHERE id=%s", (user.id,))
    if not row or not row["webhook_token"]:
        # Only reachable for a pre-migration account that somehow still has
        # no token (shouldn't happen -- 0019 backfills every existing row)
        # -- self-heal rather than 500.
        token = secrets.token_hex(24)
        await database.execute("UPDATE users SET webhook_token=%s WHERE id=%s", (token, user.id))
        return WebhookTokenOut(token=token)
    return WebhookTokenOut(token=row["webhook_token"])


@router.post("/token/rotate", response_model=WebhookTokenOut)
async def rotate_webhook_token(
    database: Database = Depends(get_database),
    user: User = Depends(current_user),
) -> WebhookTokenOut:
    """Invalidates the old token immediately -- for when it's leaked into a
    log, a public repo, a screenshot, etc. Every URL built with the old
    token stops working the moment this returns; the caller is responsible
    for updating whatever external tool was configured with it."""
    token = secrets.token_hex(24)
    await database.execute("UPDATE users SET webhook_token=%s WHERE id=%s", (token, user.id))
    return WebhookTokenOut(token=token)


class WebhookEventIn(BaseModel):
    # Mirrors EvidenceCreate/IncidentCreate from postmortems.py exactly --
    # this is the same data shape, just a different auth path in.
    source: str = Field(pattern="^(alert|log|deploy|metric|human_note|customer_report)$")
    summary: str = Field(min_length=1, max_length=500)
    detail: str | None = Field(default=None, max_length=4000)
    occurred_at: int | None = Field(default=None, gt=0)
    # If set and it names an OPEN incident this account owns, the event is
    # appended to it as evidence. Otherwise (unset, or names an incident
    # that doesn't exist/isn't open/isn't this account's), a NEW incident
    # is created from this event and its id is returned -- the caller is
    # expected to pass that id back on the next related call to group
    # subsequent events under the same incident, the same way a human
    # would keep adding evidence to one incident in the app.
    incident_id: str | None = None
    # Only used when creating a new incident (ignored when appending to an
    # existing one, which already has its own title/severity).
    title: str | None = Field(default=None, max_length=200)
    severity: str = Field(default="sev3", pattern="^(sev1|sev2|sev3|sev4)$")
    # Most real monitoring tools (PagerDuty, Datadog) already send a
    # distinct "resolved" event when the underlying condition clears --
    # this lets that map directly to the incident's own open/resolved
    # status instead of requiring a human to notice and click resolve by
    # hand. Deliberately narrow: only ever transitions open -> resolved,
    # never resolved -> open (a resolved incident reopening itself from an
    # automated signal, with no human involved, is a much riskier default
    # than the one-directional case) and only takes effect when appending
    # to an existing incident -- a brand-new incident being born resolved
    # is not a real scenario worth building for.
    resolved: bool = False


class WebhookEventOut(BaseModel):
    incident_id: str
    evidence_id: str
    created_incident: bool
    resolved: bool
    # True only when resolution also produced a real, stored grounded
    # draft automatically -- false whenever nothing was resolved, drafting
    # failed for any reason, or (see _auto_draft_on_resolve) an approved
    # postmortem already exists and auto-draft deliberately left it alone.
    drafted: bool = False


async def _auto_draft_on_resolve(database: Database, settings: Settings, user: User, incident_id: str) -> bool:
    """Best-effort auto-draft the moment PagerDuty (or the generic
    webhook) resolves an incident -- the one real, small version of
    'auto-trigger postmortem generation on incident resolution' this app
    can actually do today, using the exact same drafting logic the
    authenticated /draft endpoint already uses (see
    postmortems.py's _draft_postmortem_for_incident), not a second copy.

    Two things this deliberately does NOT do:
    - Touch a postmortem that's already PUBLISHED. _draft_postmortem_for_incident
      upserts on incident_id and would silently revert an already-approved,
      published postmortem back to a draft (nulling approved_by/approved_at)
      -- a human approved that one; an automated webhook resolving the
      underlying incident again is not grounds to un-approve it. Checked
      here, before calling the shared drafting function at all.
    - Ever fail the webhook response. A slow or failing drafting model
      must never turn a real, valid incident-resolved event into a
      non-2xx response -- PagerDuty disables a subscription after enough
      of those. The resolve itself (already committed by the caller
      before this runs) is the real, durable outcome either way.
    """
    already_published = await database.fetch_one(
        "SELECT 1 FROM incident_postmortems WHERE incident_id=%s AND status='published'", (incident_id,)
    )
    if already_published:
        logger.info("auto_draft_skipped", extra={"incident_id": incident_id, "reason": "already_published"})
        return False
    try:
        provider = create_model_provider(settings)
        await _draft_postmortem_for_incident(database, provider, settings, user, incident_id)
        logger.info("auto_draft_succeeded", extra={"incident_id": incident_id})
        return True
    except Exception:
        logger.warning("auto_draft_failed", extra={"incident_id": incident_id}, exc_info=True)
        return False


async def _ingest_event(
    database: Database,
    settings: Settings,
    user: User,
    *,
    source: str,
    summary: str,
    detail: str | None,
    occurred_at: int | None,
    title: str | None,
    severity: str,
    resolved_flag: bool,
    incident_id_hint: str | None = None,
    external_id: str | None = None,
    authorized_by: str = "webhook",
    channel: str = "webhook",
) -> WebhookEventOut:
    """The one real write path both webhook routes below share -- the
    generic endpoint (looks up an existing incident by this app's own id,
    which the caller is expected to remember and pass back) and the
    PagerDuty adapter (looks up by `external_id`, PagerDuty's own incident
    id, since PagerDuty has no way to be told this app's id in return).
    Everything downstream of "which incident, if any, already matches" --
    the paywall check, the rate limit, the insert, the resolve -- is
    identical, and stays that way by living in exactly one place. This is
    the same free-tier paywall bug class found three times already this
    session (webhook layer, MCP layer, and MCPBearerAuthMiddleware's own
    root cause) -- a second webhook route reimplementing this check by hand
    would have been a fourth chance to get it subtly wrong."""
    now = int(time.time() * 1000)
    occurred_at = occurred_at or now

    incident_id: str | None = None
    if incident_id_hint:
        existing = await database.fetch_one(
            "SELECT id FROM incidents WHERE id=%s AND client_email=%s AND status='open'",
            (incident_id_hint, user.email),
        )
        if existing:
            incident_id = existing["id"]
    elif external_id:
        existing = await database.fetch_one(
            "SELECT id FROM incidents WHERE external_id=%s AND client_email=%s AND status='open'",
            (external_id, user.email),
        )
        if existing:
            incident_id = existing["id"]

    created_incident = incident_id is None
    if created_incident:
        if not (user.has_active_subscription or user.has_free_incident_available):
            raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="An active subscription is required")
    else:
        if not (user.has_active_subscription or user.free_incident_id == incident_id):
            raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="An active subscription is required")

    if not await try_record_action(
        database, user.id, "webhook_event", MAX_WEBHOOK_EVENTS_PER_HOUR, 60 * 60 * 1000
    ):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=RATE_LIMITED_DETAIL)

    if created_incident:
        incident_id = f"inc-{now}-{secrets.token_hex(4)}"
        incident_title = title or summary[:200]
        await database.execute(
            """INSERT INTO incidents (id, client_email, title, severity, status, impact, external_id, created_at, updated_at)
               VALUES (%s, %s, %s, %s, 'open', NULL, %s, %s, %s)""",
            (incident_id, user.email, incident_title, severity, external_id, now, now),
        )
        # Mirrors create_incident's own ordering exactly (postmortems.py):
        # only spend the free slot once the insert above actually
        # succeeded, and only for an account that isn't already a real
        # subscriber.
        if not user.has_active_subscription:
            await database.execute("UPDATE users SET free_incident_id=%s WHERE id=%s", (incident_id, user.id))
        await log_activity(database, user.email, "incident_created", incident_id, f"via {channel}: {incident_title}")

    evidence_row = await database.fetch_one(
        """INSERT INTO incident_evidence
             (incident_id,client_email,occurred_at,source,summary,detail,
              authorized_by,recorded_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
           RETURNING id::text""",
        (incident_id, user.email, occurred_at, source, summary, detail, authorized_by, now),
    )
    assert evidence_row is not None

    resolved = False
    drafted = False
    if resolved_flag and not created_incident:
        updated = await database.execute(
            "UPDATE incidents SET status='resolved', updated_at=%s WHERE id=%s AND client_email=%s AND status='open'",
            (now, incident_id, user.email),
        )
        resolved = bool(updated)
        if resolved:
            await log_activity(database, user.email, "status_changed", incident_id, f"resolved via {channel}")
            drafted = await _auto_draft_on_resolve(database, settings, user, incident_id)

    logger.info(
        "webhook_event_received incident_id=%s created_incident=%s source=%s resolved=%s drafted=%s channel=%s",
        incident_id,
        created_incident,
        source,
        resolved,
        drafted,
        channel,
    )
    return WebhookEventOut(
        incident_id=incident_id,
        evidence_id=evidence_row["id"],
        created_incident=created_incident,
        resolved=resolved,
        drafted=drafted,
    )


@router.post("/incidents/{token}", status_code=status.HTTP_201_CREATED, response_model=WebhookEventOut)
async def receive_webhook_event(
    token: str,
    payload: WebhookEventIn,
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> WebhookEventOut:
    user = await user_by_webhook_token(database, settings, token)
    if user is None:
        # Deliberately the same 404 shape for "no such token" as for any
        # other not-found resource -- doesn't reveal whether a guessed
        # token is malformed vs. simply doesn't belong to any account.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown webhook token")

    return await _ingest_event(
        database,
        settings,
        user,
        source=payload.source,
        summary=payload.summary,
        detail=payload.detail,
        occurred_at=payload.occurred_at,
        title=payload.title,
        severity=payload.severity,
        resolved_flag=payload.resolved,
        incident_id_hint=payload.incident_id,
    )


# PagerDuty v3 webhook event types this adapter acts on. Anything else
# (priority.updated, incident.escalated, incident.reassigned, ...) is
# acknowledged with 200 and ignored -- PagerDuty disables a subscription
# after enough non-2xx responses, and there's no way to ask it to only send
# these three, so filtering has to happen here rather than in its config.
_PAGERDUTY_HANDLED_EVENT_TYPES = {"incident.triggered", "incident.acknowledged", "incident.resolved"}

# PagerDuty incidents only ever carry two urgency levels -- mapped
# conservatively onto this app's four severities rather than guessing a
# finer split urgency doesn't actually encode.
_PAGERDUTY_URGENCY_TO_SEVERITY = {"high": "sev2", "low": "sev4"}


def _parse_pagerduty_timestamp(value: object) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        # PagerDuty sends RFC3339 with a trailing "Z" -- Python's
        # fromisoformat wants an explicit offset before 3.11's relaxed
        # parsing. This repo pins 3.13 (see CLAUDE.md) but the replace stays
        # correct either way and costs nothing.
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


@router.post("/pagerduty/{token}")
async def receive_pagerduty_webhook(
    token: str,
    request: Request,
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> dict:
    """The URL to put in a PagerDuty v3 webhook subscription. Unlike the
    generic endpoint above, PagerDuty controls the payload shape entirely --
    every field is read defensively with .get(), never indexed, so an event
    shape this hasn't seen before (a field PagerDuty renames, an event type
    added after this was written) degrades to "ignore this one event"
    rather than a 5xx that could get the whole subscription disabled.
    """
    user = await user_by_webhook_token(database, settings, token)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown webhook token")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON body")

    event = body.get("event") if isinstance(body, dict) else None
    if not isinstance(event, dict):
        return {"status": "ignored", "reason": "unrecognized payload shape"}

    event_type = event.get("event_type")
    if event_type not in _PAGERDUTY_HANDLED_EVENT_TYPES:
        return {"status": "ignored", "event_type": event_type}

    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    external_id = data.get("id")
    if not isinstance(external_id, str) or not external_id:
        return {"status": "ignored", "reason": "missing event.data.id"}

    title = data.get("title")
    title = title if isinstance(title, str) and title else f"PagerDuty incident {external_id}"
    severity = _PAGERDUTY_URGENCY_TO_SEVERITY.get(data.get("urgency"), "sev3")
    occurred_at = _parse_pagerduty_timestamp(event.get("occurred_at"))
    summary_by_event_type = {
        "incident.triggered": f"PagerDuty triggered: {title}",
        "incident.acknowledged": f"PagerDuty acknowledged: {title}",
        "incident.resolved": f"PagerDuty resolved: {title}",
    }
    html_url = data.get("html_url")

    result = await _ingest_event(
        database,
        settings,
        user,
        source="alert",
        summary=summary_by_event_type[event_type][:500],
        detail=html_url if isinstance(html_url, str) else None,
        occurred_at=occurred_at,
        title=title[:200],
        severity=severity,
        resolved_flag=event_type == "incident.resolved",
        external_id=external_id,
        authorized_by="webhook:pagerduty",
        channel="pagerduty",
    )
    return result.model_dump()
