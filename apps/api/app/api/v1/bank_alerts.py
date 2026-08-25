"""Inbound webhook for a forwarded real bank credit alert -- email OR SMS.
See app/bank_alerts.py for the parsing itself and the honest caveat that
its patterns aren't yet verified against a real Axis Bank alert.

VERIFIES, DOES NOT APPROVE: a matching real bank alert marks the claim
bank_verified=true and stops there. It never touches payment_claims.status
or grants access -- only api/v1/founder.py's approve_payment_claim (a
founder clicking approve, behind an explicit confirmation dialog on the
frontend) does that, via activate_manual_subscription(). This is
deliberate, per explicit instruction: no client gets access without a
founder approving it, automated verification or not. What this webhook
buys the founder is not having to manually cross-check their own bank
statement against every claim -- the dashboard shows which claims already
have a real matching bank alert behind them.

Not user-authenticated (there's no user session at this point -- an email-
routing provider or an SMS-forwarding app calls this, not a browser).
Deliberately accepts several ways of passing the secret and the message
text, because unlike an email-routing provider (which usually lets you set
custom headers and a JSON body), a phone-side SMS-forwarder app often only
lets you configure a fixed webhook URL and cannot set custom headers or
build a JSON body -- so the secret is also accepted as a query parameter,
and the text is accepted as JSON, a form field, or a raw text/plain body.
"unconfigured means off" applies the same as every other optional
integration here regardless of which shape the request takes.
"""

import hmac
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from ...bank_alerts import extract_amount, extract_reference, looks_like_a_credit
from ...database import Database
from ...dependencies import get_database
from ...settings import Settings, get_settings

logger = logging.getLogger("postmortem_ai")

router = APIRouter(prefix="/v1/billing", tags=["billing"])

MAX_ALERT_TEXT_LENGTH = 20_000
# Common field names across SMS-forwarder apps and email-routing providers
# for "the actual message body" -- tried in order.
_TEXT_FIELD_NAMES = ("text", "message", "body", "sms", "msg")


async def _read_secret_and_text(request: Request) -> tuple[str | None, str]:
    secret = request.headers.get("x-bank-alert-secret") or request.query_params.get("secret")
    content_type = request.headers.get("content-type", "")

    text: str | None = None
    if "application/json" in content_type:
        try:
            data = await request.json()
        except ValueError:
            data = None
        if isinstance(data, dict):
            for field in _TEXT_FIELD_NAMES:
                if isinstance(data.get(field), str):
                    text = data[field]
                    break
    elif "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        form = await request.form()
        for field in _TEXT_FIELD_NAMES:
            value = form.get(field)
            if isinstance(value, str):
                text = value
                break
        if text is None:
            secret = secret or (form.get("secret") if isinstance(form.get("secret"), str) else None)

    if text is None:
        # Raw text/plain body (or no recognized content-type/field) --
        # treat the whole body as the message, the simplest possible
        # contract for an app that can only POST plain text.
        raw = await request.body()
        text = raw.decode("utf-8", errors="ignore")

    return secret, text.strip()[:MAX_ALERT_TEXT_LENGTH]


class BankAlertResult(BaseModel):
    matched: bool
    reference: str | None
    reason: str | None = None


@router.post("/bank-alert", response_model=BankAlertResult)
async def bank_alert_webhook(
    request: Request,
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> BankAlertResult:
    if not settings.bank_alert_webhook_secret:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Bank alert webhook is not configured")

    secret, text = await _read_secret_and_text(request)
    if not secret or not hmac.compare_digest(secret, settings.bank_alert_webhook_secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook secret")
    if not text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No alert text provided")

    if not looks_like_a_credit(text):
        logger.info("bank_alert_not_a_credit")
        return BankAlertResult(matched=False, reference=None, reason="Not recognized as a credit alert")

    reference = extract_reference(text)
    if not reference:
        logger.warning("bank_alert_reference_unparseable")
        return BankAlertResult(matched=False, reference=None, reason="Could not parse a reference number")

    amount = extract_amount(text)

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

    # Deliberately does NOT approve or activate anything here -- per
    # explicit instruction, no client ever gets access without a founder
    # approving it, automated verification or not. This marks the claim as
    # bank-verified (strong evidence shown in the founder dashboard) and
    # stops there; api/v1/founder.py's approve_payment_claim (a founder-
    # only, explicitly-confirmed click) is the only thing that can still
    # grant access, via the same activate_manual_subscription() either way
    # calls.
    now = int(time.time() * 1000)
    updated = await database.execute(
        "UPDATE payment_claims SET bank_verified=true, bank_verified_at=%s WHERE reference=%s AND status='pending'",
        (now, reference),
    )
    if not updated:
        # Already approved/rejected, or lost a race with a concurrent
        # alert for the same reference -- not an error either way.
        return BankAlertResult(matched=False, reference=reference, reason="Already handled")

    logger.info("bank_alert_verified_awaiting_founder_approval", extra={"reference": reference})
    return BankAlertResult(matched=True, reference=reference, reason=None)
