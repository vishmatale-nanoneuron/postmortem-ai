"""Internal, non-user-facing endpoints -- not authenticated by session
cookie (there's no browser involved) or founder email, but by a shared
secret Vercel Cron itself sends. See settings.cron_secret's own comment
for the exact convention.
"""

import hmac
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from ...database import Database
from ...dependencies import get_database
from ...services.email import EmailNotConfiguredError, send_free_incident_nudge_email
from ...settings import Settings, get_settings

router = APIRouter(prefix="/v1/internal", tags=["internal"])
logger = logging.getLogger("postmortem_ai")

# Only ever nudge accounts whose free incident is old enough that they've
# plausibly had time to look at the draft and decide, not one still
# mid-session -- a same-day email would read as spammy, not helpful.
MIN_INCIDENT_AGE_MS = 24 * 60 * 60 * 1000
MAX_REMINDERS_PER_RUN = 50


def _require_cron_secret(request: Request, settings: Settings) -> None:
    if not settings.cron_secret:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Cron endpoint is not configured")
    header = request.headers.get("authorization", "")
    provided = header.removeprefix("Bearer ").strip() if header.startswith("Bearer ") else ""
    if not provided or not hmac.compare_digest(provided, settings.cron_secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid cron secret")


class FreeIncidentNudgeResult(BaseModel):
    candidates_found: int
    emails_sent: int
    emails_failed: int


@router.post("/cron/free-incident-nudge", response_model=FreeIncidentNudgeResult)
async def free_incident_nudge(
    request: Request,
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> FreeIncidentNudgeResult:
    """The one automated purchase-decision nudge in this app: an account
    that used its free incident, got a real draft out of it, still hasn't
    subscribed, and has had at least a day to decide -- gets exactly one
    email, ever (free_incident_reminder_sent_at is set immediately after
    sending and checked here, so a retry of this same cron run can never
    double-send). Requires a real draft to exist, not just an incident --
    someone who created the incident and never entered evidence got no
    real value yet, and nudging them would be premature, not helpful."""
    _require_cron_secret(request, settings)

    cutoff = int(time.time() * 1000) - MIN_INCIDENT_AGE_MS
    candidates = await database.fetch_all(
        """SELECT u.id::text AS id, u.email, i.title AS incident_title
           FROM users u
           JOIN incidents i ON i.id = u.free_incident_id
           JOIN incident_postmortems p ON p.incident_id = i.id
           WHERE u.subscription_status = 'none'
             AND u.free_incident_reminder_sent_at IS NULL
             AND i.created_at <= %s
           ORDER BY i.created_at
           LIMIT %s""",
        (cutoff, MAX_REMINDERS_PER_RUN),
    )

    sent = 0
    failed = 0
    for row in candidates:
        try:
            send_free_incident_nudge_email(settings, row["email"], row["incident_title"], row["id"])
        except EmailNotConfiguredError:
            # Not configured means "cron runs, does nothing" everywhere
            # else in this app too (see billing._client()) -- stop the
            # whole run rather than fail every candidate individually.
            logger.warning("free_incident_nudge_email_not_configured")
            break
        except Exception:
            # One bad address/API hiccup shouldn't block every other
            # candidate in this run -- logged, counted, and retried
            # automatically on the next scheduled run since
            # free_incident_reminder_sent_at is only set on success.
            logger.exception("free_incident_nudge_email_failed", extra={"user_id": row["id"]})
            failed += 1
            continue
        await database.execute(
            "UPDATE users SET free_incident_reminder_sent_at = %s WHERE id = %s",
            (int(time.time() * 1000), row["id"]),
        )
        sent += 1

    return FreeIncidentNudgeResult(candidates_found=len(candidates), emails_sent=sent, emails_failed=failed)
