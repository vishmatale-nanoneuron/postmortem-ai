import time

from ..database import Database, Transaction

# A manual approval is treated as an indefinite-ish subscription that
# renews every 30 days -- there is no gateway enforcing an actual billing
# cycle here, so this is the founder's own reminder window, re-extended
# each time a claim for the same account is approved.
MANUAL_SUBSCRIPTION_PERIOD_SECONDS = 30 * 24 * 60 * 60


async def activate_manual_subscription(database: Database | Transaction, user_id: str) -> int:
    """Grants/renews 30 days of access for a manually-verified (UPI/wire)
    payment. This is the ONLY place in the entire codebase that sets
    subscription_status='active' for a manual payment -- called from
    exactly one call site, api/v1/founder.py's approve_payment_claim,
    which requires the real founder to click approve. bank_alerts.py's
    webhook (automated bank-alert matching) deliberately never calls this;
    it can only mark a claim bank_verified, never grant access itself."""
    period_end = int(time.time()) + MANUAL_SUBSCRIPTION_PERIOD_SECONDS
    await database.execute(
        "UPDATE users SET subscription_status='active', current_period_end=%s WHERE id=%s",
        (period_end, user_id),
    )
    return period_end


async def record_claim_event(
    database: Database | Transaction, claim_id: str, event_type: str, actor: str, detail: str | None = None
) -> None:
    """Append-only audit trail (payment_claim_events, migration 0016) --
    never overwritten or deleted, unlike payment_claims.status which only
    ever shows the current state. Real payment-engineering practice: never
    lose financial history, even when the current-state row moves on."""
    await database.execute(
        "INSERT INTO payment_claim_events (claim_id, event_type, actor, detail, created_at) VALUES (%s, %s, %s, %s, %s)",
        (claim_id, event_type, actor, detail, int(time.time() * 1000)),
    )
