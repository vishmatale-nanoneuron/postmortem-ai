"""Inbound webhook for a forwarded real bank credit-alert email. See
app/bank_alerts.py for the parsing itself and the honest caveat that its
patterns aren't yet verified against a real Axis Bank email.

Not user-authenticated (there's no user session at this point -- an email
routing provider calls this, not a browser) -- authenticated instead by a
shared secret header, same "unconfigured means off" stance as the rest of
this codebase's optional integrations.
"""

import hmac
import logging
import time

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from ...bank_alerts import extract_amount, extract_reference, looks_like_a_credit
from ...database import Database
from ...dependencies import get_database
from ...services.billing import activate_manual_subscription
from ...settings import Settings, get_settings

logger = logging.getLogger("postmortem_ai")

router = APIRouter(prefix="/v1/billing", tags=["billing"])


class BankAlertIn(BaseModel):
    # The raw email/SMS text -- kept as one blob rather than pre-parsed
    # fields, since the whole point is this app does its own parsing (see
    # bank_alerts.py) rather than trusting whatever shape the forwarding
    # provider chooses to send.
    text: str = Field(min_length=1, max_length=20_000)


class BankAlertResult(BaseModel):
    matched: bool
    reference: str | None
    reason: str | None = None


@router.post("/bank-alert", response_model=BankAlertResult)
async def bank_alert_webhook(
    payload: BankAlertIn,
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
    x_bank_alert_secret: str | None = Header(default=None),
) -> BankAlertResult:
    if not settings.bank_alert_webhook_secret:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Bank alert webhook is not configured")
    if not x_bank_alert_secret or not hmac.compare_digest(x_bank_alert_secret, settings.bank_alert_webhook_secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook secret")

    if not looks_like_a_credit(payload.text):
        logger.info("bank_alert_not_a_credit")
        return BankAlertResult(matched=False, reference=None, reason="Not recognized as a credit alert")

    reference = extract_reference(payload.text)
    if not reference:
        logger.warning("bank_alert_reference_unparseable")
        return BankAlertResult(matched=False, reference=None, reason="Could not parse a reference number")

    amount = extract_amount(payload.text)

    claim = await database.fetch_one(
        "SELECT id::text, user_id::text, amount_inr FROM payment_claims WHERE reference=%s AND status='pending'",
        (reference,),
    )
    if not claim:
        logger.info("bank_alert_no_matching_pending_claim", extra={"reference": reference})
        return BankAlertResult(matched=False, reference=reference, reason="No matching pending claim")

    # Amount is corroboration, not the primary match key (reference already
    # is), but a parsed amount that clearly disagrees with the claim is
    # worth refusing to auto-approve rather than trusting a possibly
    # misparsed alert -- falls back to the founder's own manual review.
    if amount is not None and amount != claim["amount_inr"]:
        logger.warning(
            "bank_alert_amount_mismatch",
            extra={"reference": reference, "alert_amount": amount, "claim_amount": claim["amount_inr"]},
        )
        return BankAlertResult(matched=False, reference=reference, reason="Amount does not match the claim")

    now = int(time.time() * 1000)
    async with database.transaction() as tx:
        updated = await tx.execute(
            "UPDATE payment_claims SET status='approved', reviewed_by='auto:bank-alert', reviewed_at=%s "
            "WHERE reference=%s AND status='pending'",
            (now, reference),
        )
        if not updated:
            # Lost a race with another concurrent alert/approval for the
            # same reference -- already handled, not an error.
            return BankAlertResult(matched=False, reference=reference, reason="Already handled")
        await activate_manual_subscription(tx, claim["user_id"])

    logger.info("bank_alert_auto_approved", extra={"reference": reference})
    return BankAlertResult(matched=True, reference=reference, reason=None)
