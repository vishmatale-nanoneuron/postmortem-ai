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
from ...services.email import EmailNotConfiguredError, send_purchase_reminder_email
from ...settings import Settings, get_settings

router = APIRouter(prefix="/v1/internal", tags=["internal"])
logger = logging.getLogger("postmortem_ai")

# Only ever remind accounts old enough to have plausibly looked around
# and decided, not one created an hour ago -- a same-day email would read
# as spammy, not helpful.
MIN_ACCOUNT_AGE_MS = 24 * 60 * 60 * 1000
MAX_REMINDERS_PER_RUN = 50
DAY_MS = 24 * 60 * 60 * 1000


def _require_cron_secret(request: Request, settings: Settings) -> None:
    if not settings.cron_secret:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Cron endpoint is not configured")
    header = request.headers.get("authorization", "")
    provided = header.removeprefix("Bearer ").strip() if header.startswith("Bearer ") else ""
    if not provided or not hmac.compare_digest(provided, settings.cron_secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid cron secret")


class PurchaseReminderResult(BaseModel):
    candidates_found: int
    emails_sent: int
    emails_failed: int


@router.post("/cron/purchase-reminder", response_model=PurchaseReminderResult)
async def purchase_reminder(
    request: Request,
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> PurchaseReminderResult:
    """The one automated purchase-decision nudge in this app: an account
    that signed up at least a day ago and has never paid for anything --
    no subscription, no payment claim of either product in any state, no
    Airlock credits ever bought -- gets exactly one email, ever.

    This replaced the free-incident nudge on 2026-09-13 when the trial was
    retired: with no free incidents, that cron could never fire again, and
    a signup from anywhere in the world who never paid would have heard
    nothing. The "sent" mark reuses the free_incident_reminder_sent_at
    column (migration 0022): it has always meant "this account's one
    reminder went out", and reusing it means a legacy account that already
    received the old nudge does not get a second email now.

    A pending claim excludes the account on purpose: they have paid and are
    waiting on the founder, and a "have you considered paying?" email at
    that moment would be insulting. The founder's own account is excluded
    by email."""
    _require_cron_secret(request, settings)

    now = int(time.time() * 1000)
    cutoff = now - MIN_ACCOUNT_AGE_MS
    candidates = await database.fetch_all(
        """SELECT u.id::text AS id, u.email, u.created_at
           FROM users u
           WHERE u.subscription_status = 'none'
             AND u.free_incident_reminder_sent_at IS NULL
             AND u.created_at <= %s
             AND lower(u.email) <> lower(%s)
             AND NOT EXISTS (SELECT 1 FROM payment_claims pc WHERE pc.user_id = u.id)
             AND NOT EXISTS (
               SELECT 1 FROM airlock_credit_ledger l WHERE l.user_id = u.id AND l.reason IN ('purchase', 'grant')
             )
           ORDER BY u.created_at
           LIMIT %s""",
        (cutoff, settings.founder_email, MAX_REMINDERS_PER_RUN),
    )

    sent = 0
    failed = 0
    for row in candidates:
        days = max(1, (now - int(row["created_at"])) // DAY_MS)
        try:
            send_purchase_reminder_email(settings, row["email"], row["id"], days_since_signup=days)
        except EmailNotConfiguredError:
            # Not configured means "cron runs, does nothing" everywhere
            # else in this app too (see billing._client()) -- stop the
            # whole run rather than fail every candidate individually.
            logger.warning("purchase_reminder_email_not_configured")
            break
        except Exception:
            # One bad address/API hiccup shouldn't block every other
            # candidate in this run -- logged, counted, and retried
            # automatically on the next scheduled run since the sent mark
            # is only set on success.
            logger.exception("purchase_reminder_email_failed", extra={"user_id": row["id"]})
            failed += 1
            continue
        await database.execute(
            "UPDATE users SET free_incident_reminder_sent_at = %s WHERE id = %s",
            (int(time.time() * 1000), row["id"]),
        )
        sent += 1

    return PurchaseReminderResult(candidates_found=len(candidates), emails_sent=sent, emails_failed=failed)
