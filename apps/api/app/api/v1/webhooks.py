"""Real incident-source webhook ingestion -- lets an external tool
(monitoring, alerting, a CI job, a script -- anything that can POST JSON)
create evidence without a signed-in browser session. Closes the gap that
existed until now: evidence could only ever be typed in by hand through the
authenticated app, even though this product's whole premise is grounding a
postmortem in evidence recorded as an incident actually unfolds -- which,
for most real incidents, means alerts firing automatically, not someone
copy-pasting them in after the fact.

Deliberately generic, not source-specific (no Datadog/PagerDuty/etc. field
mapping): this app has no real example payload from any of those services
to build and test against honestly, and a fabricated field-mapping guess
would be worse than a plain format any tool's "custom webhook" option can
already send. The generic shape here is exactly what create_incident /
record_evidence already accept -- this endpoint is the same write path,
authenticated differently.
"""

import logging
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ...auth import User, current_user, user_by_webhook_token
from ...database import Database
from ...dependencies import get_database
from ...security.rate_limit import try_record_action
from ...settings import Settings, get_settings

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

    now = int(time.time() * 1000)
    occurred_at = payload.occurred_at or now

    # Resolve which incident this event targets BEFORE the paywall check --
    # the free-tier allowance genuinely differs between the two cases
    # (require_active_subscription_or_free_incident vs.
    # _or_free_slot in auth.py), so which one applies depends on whether
    # this is an append or a create, not a single flat check. The previous
    # version here used a single `has_active_subscription` check for both
    # cases -- despite this file's own module docstring and public
    # documentation both claiming this is "the same paywall" as the
    # authenticated REST endpoints, it silently was not: a brand-new
    # unpaid account got a 402 on its very first webhook call, even for
    # what would have been its one free incident through the normal app.
    # Confirmed live against production before this fix, not assumed.
    incident_id: str | None = None
    if payload.incident_id:
        existing = await database.fetch_one(
            "SELECT id FROM incidents WHERE id=%s AND client_email=%s AND status='open'",
            (payload.incident_id, user.email),
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
        title = payload.title or payload.summary[:200]
        await database.execute(
            """INSERT INTO incidents (id, client_email, title, severity, status, impact, created_at, updated_at)
               VALUES (%s, %s, %s, %s, 'open', NULL, %s, %s)""",
            (incident_id, user.email, title, payload.severity, now, now),
        )
        # Mirrors create_incident's own ordering exactly (postmortems.py):
        # only spend the free slot once the insert above actually
        # succeeded, and only for an account that isn't already a real
        # subscriber.
        if not user.has_active_subscription:
            await database.execute("UPDATE users SET free_incident_id=%s WHERE id=%s", (incident_id, user.id))

    evidence_row = await database.fetch_one(
        """INSERT INTO incident_evidence
             (incident_id,client_email,occurred_at,source,summary,detail,
              authorized_by,recorded_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
           RETURNING id::text""",
        (incident_id, user.email, occurred_at, payload.source, payload.summary, payload.detail, "webhook", now),
    )
    assert evidence_row is not None

    resolved = False
    if payload.resolved and not created_incident:
        updated = await database.execute(
            "UPDATE incidents SET status='resolved', updated_at=%s WHERE id=%s AND client_email=%s AND status='open'",
            (now, incident_id, user.email),
        )
        resolved = bool(updated)

    logger.info(
        "webhook_event_received incident_id=%s created_incident=%s source=%s resolved=%s",
        incident_id,
        created_incident,
        payload.source,
        resolved,
    )
    return WebhookEventOut(
        incident_id=incident_id, evidence_id=evidence_row["id"], created_incident=created_incident, resolved=resolved
    )
