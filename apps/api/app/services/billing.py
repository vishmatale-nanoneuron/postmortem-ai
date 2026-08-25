import time

from ..database import Database, Transaction

# A manual approval is treated as an indefinite-ish subscription that
# renews every 30 days -- there is no gateway enforcing an actual billing
# cycle here, so this is the founder's own reminder window, re-extended
# each time a new claim for the same account is approved (whether by a
# founder clicking approve, or by bank_alerts.py's auto-approval).
MANUAL_SUBSCRIPTION_PERIOD_SECONDS = 30 * 24 * 60 * 60


async def activate_manual_subscription(database: Database | Transaction, user_id: str) -> int:
    """Grants/renews 30 days of access for a manually-verified (UPI/wire)
    payment. Shared by the founder-dashboard approval
    (api/v1/founder.py's approve_payment_claim) and the bank-alert
    auto-approval (bank_alerts.py) so both grant access exactly the same
    way, through one code path."""
    period_end = int(time.time()) + MANUAL_SUBSCRIPTION_PERIOD_SECONDS
    await database.execute(
        "UPDATE users SET subscription_status='active', current_period_end=%s WHERE id=%s",
        (period_end, user_id),
    )
    return period_end
