"""Billing: the manual UPI and international-wire rails, and nothing else.

No payment gateway, no card processor. A client pays the founder's UPI ID
or bank account directly and submits the transaction reference; the founder
reviews and approves from the founder dashboard (api/v1/founder.py), which
is the only thing that ever grants access. The card-processor integration
that used to live here was removed on 2026-09-13 on the owner's instruction;
it had only ever run in test mode in production and no real customer was
ever billed through it.
"""

import logging
from datetime import UTC, datetime
import secrets
import time

import resend.exceptions
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from typing import Literal

from pydantic import BaseModel, Field

from ...auth import User, current_founder, current_user
from ...database import Database
from ...dependencies import get_database
from ...security.rate_limit import try_record_action
from ...services.billing import record_claim_event
from ...services.email import (
    EmailNotConfiguredError,
    send_client_claim_confirmation,
    send_founder_claim_notification,
    send_upi_payment_details_email,
    send_wire_payment_details_email,
)
from ...settings import Settings, get_settings

logger = logging.getLogger("postmortem_ai")

router = APIRouter(prefix="/v1/billing", tags=["billing"])

# Deliberately a Literal, not a plain str: FastAPI rejects anything else
# at the edge with a 422, which together with migration 0029's CHECK
# constraint means an invalid period can neither be sent nor stored.
BillingPeriod = Literal["monthly", "annual"]


# The single projection every ClaimOut is built from. A code-review pass found
# this had already drifted: the INSERT returned billing_period while the PATCH
# and both list endpoints silently omitted it, so a Rs.9990 annual claim was
# reported back to its own owner as "monthly". Exactly the "two
# implementations of one read that drift apart" problem the CQRS split in
# cqrs/activity.py exists to prevent -- so the read side is defined once here
# and reused, rather than hand-written per endpoint.
_CLAIM_COLUMNS = (
    "id::text, method, currency, amount_inr AS amount, reference, status, created_at, billing_period,"
    " product, scan_credits"
)

RATE_LIMITED_DETAIL = "Too many requests. Try again later."

# Sending the real account details is the one client-facing side effect of
# this action (unlike a claim submission, which is real regardless of
# whether its notification email goes out) -- bounded per-account so it
# can't be used to spam an inbox, generous enough that a genuine client
# checking spam or wanting a second copy isn't blocked.
MAX_PAYMENT_DETAILS_EMAILS_PER_WINDOW = 5
PAYMENT_DETAILS_EMAIL_WINDOW_MS = 60 * 60 * 1000

class BillingStatusOut(BaseModel):
    subscription_status: str
    current_period_end: int | None
    has_active_subscription: bool


@router.get("/status", response_model=BillingStatusOut)
async def billing_status(user: User = Depends(current_user)) -> BillingStatusOut:
    # user already carries subscription_status/current_period_end from its
    # own DB read in current_user() -- no need for a second, separate
    # fetch_one that could theoretically read a different row (e.g. if a
    # concurrent write landed between the two queries). effective_status
    # honestly reports "expired" rather than a stale "active" past the
    # real period_end -- see auth.py's User.effective_status.
    return BillingStatusOut(
        subscription_status=user.effective_status,
        current_period_end=user.current_period_end,
        has_active_subscription=user.has_active_subscription,
    )


# ---------------------------------------------------------------------------
# Manual UPI payment: no gateway, no KYC. The client pays the founder's UPI
# ID directly and submits a transaction reference; the founder reviews and
# approves from the founder dashboard (see api/v1/founder.py), which is what
# actually flips subscription_status to 'active' -- submitting a claim here
# does not itself grant access.
# ---------------------------------------------------------------------------


class UpiInfoOut(BaseModel):
    upi_id: str
    payee_name: str
    amount_inr: int
    configured: bool


class UpiClaimIn(BaseModel):
    reference: str = Field(min_length=4, max_length=200)
    # Defaults to monthly so an older client that doesn't send the field
    # keeps working unchanged, and can only ever get the smaller grant.
    billing_period: BillingPeriod = "monthly"


class ClaimOut(BaseModel):
    id: str
    method: str
    currency: str
    amount: int
    reference: str
    status: str
    created_at: int
    # "monthly" or "annual" -- what the client actually paid for, and what
    # approve_payment_claim will grant. Defaulted rather than required so a
    # row read back from before migration 0029 still deserialises.
    billing_period: str = "monthly"
    # 'postmortem' (a subscription period) or 'airlock' (a pack of scans).
    # Same defaulting reason as billing_period, for migration 0032.
    product: str = "postmortem"
    # Only ever set on an Airlock claim: the number of scans approval grants.
    scan_credits: int | None = None


def annual_price(monthly: int, settings: Settings) -> int:
    """Annual price derived from the monthly one, so the two can never drift.
    settings.annual_months_charged defaults to 10 -- the conventional "two
    months free" discount."""
    return monthly * settings.annual_months_charged


def price_for(monthly: int, period: str, settings: Settings) -> int:
    return annual_price(monthly, settings) if period == "annual" else monthly


async def _insert_claim(
    database: Database,
    settings: Settings,
    user: User,
    method: str,
    currency: str,
    amount: int,
    reference: str,
    billing_period: str = "monthly",
    *,
    product: str = "postmortem",
    scan_credits: int | None = None,
) -> ClaimOut:
    # A real UPI/wire transaction reference is unique per transaction --
    # amount and currency are already server-derived (never client input,
    # so a bogus amount can't be submitted at all), but nothing previously
    # stopped the same reference string from being reused across multiple
    # claims (same or different accounts), which can only mean a mistake
    # or an attempt to get approved twice off one real payment. Rejected
    # automatically at submission, before it ever becomes a pending claim
    # a founder could accidentally approve.
    existing = await database.fetch_one(
        "SELECT id FROM payment_claims WHERE reference=%s AND status != 'rejected'", (reference,)
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This reference has already been submitted. Contact the founder if this is a mistake.",
        )

    now = int(time.time() * 1000)
    row = await database.fetch_one(
        """INSERT INTO payment_claims
             (user_id, amount_inr, currency, method, reference, status, created_at, billing_period,
              product, scan_credits)
           VALUES (%s, %s, %s, %s, %s, 'pending', %s, %s, %s, %s)
           RETURNING """
        + _CLAIM_COLUMNS,
        (user.id, amount, currency, method, reference, now, billing_period, product, scan_credits),
    )
    assert row is not None
    what = f"{scan_credits} Airlock scans" if product == "airlock" else billing_period
    await record_claim_event(database, row["id"], "created", user.email, f"{currency} {amount} via {method} ({what})")

    # Best-effort, never blocks the claim: the claim row above is already
    # committed and is the real record a founder can act on from the
    # dashboard regardless of whether this email goes out. Resend being
    # unconfigured (fresh dev environment, an outage, a bad key) must never
    # turn a real customer's payment claim into a 500.
    try:
        send_founder_claim_notification(settings, row["id"], method, currency, amount, reference, user.email)
    except EmailNotConfiguredError:
        logger.info("founder_claim_notification_skipped", extra={"reason": "email_not_configured"})
    except Exception:
        logger.warning("founder_claim_notification_failed", extra={"claim_id": row["id"]}, exc_info=True)

    # Same best-effort reasoning as the founder notification above, for the
    # same claim -- the client-facing courtesy copy (see
    # send_client_claim_confirmation's own docstring). A Resend outage or
    # unconfigured environment must never turn an already-committed, real
    # claim into a failed submission for the customer.
    try:
        send_client_claim_confirmation(settings, row["id"], user.email, method, currency, amount, reference)
    except EmailNotConfiguredError:
        logger.info("client_claim_confirmation_skipped", extra={"reason": "email_not_configured"})
    except Exception:
        logger.warning("client_claim_confirmation_failed", extra={"claim_id": row["id"]}, exc_info=True)

    return ClaimOut(**row)


class PatchClaimIn(BaseModel):
    reference: str = Field(min_length=4, max_length=200)


# ---------------------------------------------------------------------------
# The invoice. One document per claim, in two states: a proforma invoice
# while the claim is pending (what a finance team needs to raise a wire),
# and a receipt once the founder has approved it (what they need to
# expense it). Rejected claims render as void. Readable only by the claim's
# owner; the founder reads claims from the founder dashboard instead.
#
# Payee bank details are NOT on this document -- they are emailed to the
# account's own address on request (email_upi_details / email_wire_details),
# which keeps the existing posture of never serving the real account
# numbers from a page. The proforma says so and names the reference the
# wire must carry.
# ---------------------------------------------------------------------------


class InvoiceSellerOut(BaseModel):
    name: str
    address: str | None
    tax_id: str | None


class InvoiceLineOut(BaseModel):
    description: str
    quantity: int
    unit_amount: int
    amount: int
    currency: str


class InvoiceOut(BaseModel):
    number: str
    # "proforma" while pending, "receipt" once approved, "void" if rejected.
    kind: str
    status: str
    issued_at: int
    paid_at: int | None
    seller: InvoiceSellerOut
    buyer_email: str
    line: InvoiceLineOut
    method: str
    reference: str
    product: str
    billing_period: str | None
    scan_credits: int | None


def _invoice_number(claim_id: str, created_at: int) -> str:
    """Stable, derived from the claim, never reissued: the date the claim
    was raised plus the first eight characters of its id. Not a sequential
    tax-invoice series -- that numbering is a bookkeeping decision the
    founder makes outside this app; this is the document's reference."""
    day = datetime.fromtimestamp(created_at / 1000, tz=UTC).strftime("%Y%m%d")
    return f"NN-{day}-{claim_id[:8].upper()}"


def _describe(settings: Settings, product: str, billing_period: str | None, scan_credits: int | None) -> tuple[str, int]:
    if product == "airlock":
        credits = int(scan_credits or 0)
        packs = max(1, credits // max(1, settings.airlock_pack_scans))
        return f"Airlock scan credits -- {credits:,} credits ({packs} x {settings.airlock_pack_scans:,})", packs
    period = "annual (12 months)" if billing_period == "annual" else "monthly (30 days)"
    return f"PostMortem AI subscription -- {period}", 1


@router.get("/claims/{claim_id}/invoice", response_model=InvoiceOut, responses={404: {"description": "Not your claim, or no such claim."}})
async def claim_invoice(
    claim_id: str,
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
    user: User = Depends(current_user),
) -> InvoiceOut:
    row = await database.fetch_one(
        f"""SELECT {_CLAIM_COLUMNS}, reviewed_at
            FROM payment_claims WHERE id=%s AND user_id=%s""",
        (claim_id, user.id),
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    product = row.get("product") or "postmortem"
    description, quantity = _describe(settings, product, row.get("billing_period"), row.get("scan_credits"))
    amount = int(row["amount"])
    kind = {"pending": "proforma", "approved": "receipt", "rejected": "void"}.get(row["status"], "proforma")
    seller_name = settings.seller_legal_name or settings.founder_bank_account_name or settings.founder_upi_payee_name
    return InvoiceOut(
        number=_invoice_number(row["id"], int(row["created_at"])),
        kind=kind,
        status=row["status"],
        issued_at=int(row["created_at"]),
        paid_at=int(row["reviewed_at"]) if row["status"] == "approved" and row.get("reviewed_at") else None,
        seller=InvoiceSellerOut(
            name=seller_name or "NanoNeuron",
            address=settings.seller_address or None,
            tax_id=settings.seller_tax_id or None,
        ),
        buyer_email=user.email,
        line=InvoiceLineOut(
            description=description,
            quantity=quantity,
            unit_amount=amount // quantity if quantity else amount,
            amount=amount,
            currency=row["currency"],
        ),
        method=row["method"],
        reference=row["reference"],
        product=product,
        billing_period=row.get("billing_period"),
        scan_credits=row.get("scan_credits"),
    )


@router.patch("/claims/{claim_id}", response_model=ClaimOut)
async def update_my_claim(
    claim_id: str,
    payload: PatchClaimIn,
    database: Database = Depends(get_database),
    user: User = Depends(current_user),
) -> ClaimOut:
    """Lets a client fix a typo'd reference on their own claim -- only
    while it's still pending. Once bank_verified or approved/rejected, the
    reference is exactly what a real bank alert matched against or what a
    founder reviewed; changing it after the fact would break that link, so
    this is refused past pending (mirrors why record_claim_event never lets
    the past be rewritten, just appended to)."""
    existing = await database.fetch_one(
        "SELECT id, status FROM payment_claims WHERE id=%s AND user_id=%s", (claim_id, user.id)
    )
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    if existing["status"] != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only a pending claim can be edited")

    duplicate = await database.fetch_one(
        "SELECT id FROM payment_claims WHERE reference=%s AND status != 'rejected' AND id<>%s",
        (payload.reference, claim_id),
    )
    if duplicate:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This reference has already been submitted")

    row = await database.fetch_one(
        """UPDATE payment_claims SET reference=%s WHERE id=%s
           RETURNING """
        + _CLAIM_COLUMNS,
        (payload.reference, claim_id),
    )
    assert row is not None
    await record_claim_event(database, claim_id, "annotated", user.email, f"Reference edited to {payload.reference}")
    return ClaimOut(**row)


@router.delete("/claims/{claim_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_my_claim(
    claim_id: str,
    database: Database = Depends(get_database),
    user: User = Depends(current_user),
) -> None:
    """Lets a client withdraw their own claim -- only while pending, same
    reasoning as the PATCH above. This is a real status transition (not a
    row delete) so the ledger keeps the full history; the row itself is
    kept too, both for the audit trail and so the reference can't be
    silently freed up for reuse."""
    existing = await database.fetch_one(
        "SELECT id, status FROM payment_claims WHERE id=%s AND user_id=%s", (claim_id, user.id)
    )
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    if existing["status"] != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only a pending claim can be cancelled")

    now = int(time.time() * 1000)
    await database.execute(
        "UPDATE payment_claims SET status='rejected', reviewed_by=%s, reviewed_at=%s WHERE id=%s",
        (user.email, now, claim_id),
    )
    await record_claim_event(database, claim_id, "rejected", user.email, "Cancelled by client")


class UpiPricingOut(BaseModel):
    amount_inr: int
    # Derived from the monthly price (see annual_price) rather than stored,
    # so the two can't drift apart.
    amount_inr_annual: int = 0
    configured: bool


@router.get("/upi/pricing", response_model=UpiPricingOut)
async def upi_pricing(settings: Settings = Depends(get_settings)) -> UpiPricingOut:
    """Public, unauthenticated -- price only, no real UPI ID. Backs the
    public /pricing page, which never needs the actual account to render a
    price."""
    return UpiPricingOut(
        amount_inr=settings.subscription_price_inr,
        amount_inr_annual=annual_price(settings.subscription_price_inr, settings),
        configured=bool(settings.founder_upi_id),
    )


@router.get("/upi/info", response_model=UpiInfoOut)
async def upi_info(
    settings: Settings = Depends(get_settings),
    _founder: User = Depends(current_founder),
) -> UpiInfoOut:
    """Founder-only -- this is the real UPI ID and payee name to pay real
    money to. First fixed to require any signed-in caller, which turned out
    not to be a real barrier: registration is free and instant, so any
    client (even a throwaway account created seconds earlier) could still
    reach it. Tightened to founder-only on direct instruction -- no client
    account, however genuine, gets this from the app anymore. A client who
    wants to pay gets the same details emailed to their own registered
    address instead (POST /upi/email-details below), rather than reading
    them back from an API response. The public price-only shape stays at
    /upi/pricing above."""
    return UpiInfoOut(
        upi_id=settings.founder_upi_id,
        payee_name=settings.founder_upi_payee_name,
        amount_inr=settings.subscription_price_inr,
        configured=bool(settings.founder_upi_id),
    )


@router.post("/upi/claim", status_code=status.HTTP_201_CREATED, response_model=ClaimOut)
async def submit_upi_claim(
    payload: UpiClaimIn,
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
    user: User = Depends(current_user),
) -> ClaimOut:
    if not settings.founder_upi_id:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="UPI payment is not configured")
    # The amount is derived server-side from the period, never taken from the
    # client -- the same reason every other price here comes from settings:
    # a client-supplied amount would let anyone claim a year for the price of
    # a month.
    amount = price_for(settings.subscription_price_inr, payload.billing_period, settings)
    return await _insert_claim(
        database, settings, user, "upi", "INR", amount, payload.reference, payload.billing_period
    )


class EmailDetailsOut(BaseModel):
    sent: bool


class UpiEmailDetailsIn(BaseModel):
    """Optional body so an older client that posts nothing still works."""

    billing_period: BillingPeriod = "monthly"


@router.post("/upi/email-details", response_model=EmailDetailsOut)
async def email_upi_details(
    payload: UpiEmailDetailsIn = UpiEmailDetailsIn(),
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
    user: User = Depends(current_user),
) -> EmailDetailsOut:
    """Self-serve replacement for a client having to email the founder to
    receive the real UPI ID before they can pay -- see upi_info's docstring
    for why the account itself stays founder-only. Any signed-in client can
    call this (unlike GET /upi/info); what's actually rate-limited is
    getting the real account sent anywhere, and the destination is always
    the caller's own registered email, never a client-supplied address."""
    if not settings.founder_upi_id:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="UPI payment is not configured")
    allowed = await try_record_action(
        database, user.id, "upi_details_email", MAX_PAYMENT_DETAILS_EMAILS_PER_WINDOW, PAYMENT_DETAILS_EMAIL_WINDOW_MS
    )
    if not allowed:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=RATE_LIMITED_DETAIL)
    try:
        await run_in_threadpool(
            send_upi_payment_details_email,
            settings,
            user.email,
            secrets.token_hex(8),
            settings.founder_upi_id,
            settings.founder_upi_payee_name,
            # Must match what submit_upi_claim will record for the same
            # period. Quoting the monthly price for an annual claim puts a
            # pre-filled deep link of Rs.999 in front of a customer whose
            # claim is Rs.9990, so the credited amount never matches in
            # bank_alerts.py and auto-verification silently never fires --
            # exactly the failure the deep link exists to remove.
            price_for(settings.subscription_price_inr, payload.billing_period, settings),
        )
    except EmailNotConfiguredError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Email is not configured") from error
    except resend.exceptions.ResendError as error:
        # Unlike the founder-notification/client-confirmation emails, this
        # response IS the deliverable -- there's no already-committed record
        # underneath it to fall back on, so a real Resend-side failure (rate
        # limit, a rejected address, an outage) must be reported honestly as
        # failed, not swallowed into a false "sent: true". 502, not 500: this
        # is a real, anticipated failure mode of a specific downstream
        # dependency, not an unexpected bug -- the client still has the
        # mailto fallback link in the UI for exactly this case.
        logger.warning("upi_payment_details_email_failed", extra={"user_id": user.id}, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not send the email right now. Try again, or email the founder directly.",
        ) from error
    return EmailDetailsOut(sent=True)


@router.get("/upi/claims", response_model=list[ClaimOut])
async def my_upi_claims(
    database: Database = Depends(get_database),
    user: User = Depends(current_user),
) -> list[ClaimOut]:
    rows = await database.fetch_all(
        f"""SELECT {_CLAIM_COLUMNS}
           FROM payment_claims WHERE user_id=%s AND method='upi' AND product='postmortem'
           ORDER BY created_at DESC""",
        (user.id,),
    )
    return [ClaimOut(**row) for row in rows]


# ---------------------------------------------------------------------------
# Manual international wire (SWIFT): same pattern as UPI, for clients
# outside India where UPI cannot reach (it requires an Indian bank account
# on the payer's side -- no workaround). Correspondent bank details differ
# per currency; beneficiary details are shared.
# ---------------------------------------------------------------------------

WIRE_CURRENCIES = ("USD", "GBP", "EUR")


class WireCurrencyDetails(BaseModel):
    currency: str
    amount: int
    correspondent_bank: str
    correspondent_swift: str
    nostro_account: str
    routing_reference: str  # ABA for USD, IBAN for GBP/EUR -- label kept generic, meaning shown in the value


class WireInfoOut(BaseModel):
    account_name: str
    account_number: str
    bank_name: str
    swift_code: str
    configured: bool
    currencies: list[WireCurrencyDetails]


class WireClaimIn(BaseModel):
    currency: str = Field(pattern="^(USD|GBP|EUR)$")
    reference: str = Field(min_length=4, max_length=200)
    billing_period: BillingPeriod = "monthly"


def _wire_currency_details(settings: Settings) -> list[WireCurrencyDetails]:
    return [
        WireCurrencyDetails(
            currency="USD",
            amount=settings.subscription_price_usd,
            correspondent_bank=settings.wire_usd_correspondent_bank,
            correspondent_swift=settings.wire_usd_correspondent_swift,
            nostro_account=settings.wire_usd_nostro_account,
            routing_reference=settings.wire_usd_aba,
        ),
        WireCurrencyDetails(
            currency="GBP",
            amount=settings.subscription_price_gbp,
            correspondent_bank=settings.wire_gbp_correspondent_bank,
            correspondent_swift=settings.wire_gbp_correspondent_swift,
            nostro_account=settings.wire_gbp_nostro_account,
            routing_reference=settings.wire_gbp_iban,
        ),
        WireCurrencyDetails(
            currency="EUR",
            amount=settings.subscription_price_eur,
            correspondent_bank=settings.wire_eur_correspondent_bank,
            correspondent_swift=settings.wire_eur_correspondent_swift,
            nostro_account=settings.wire_eur_nostro_account,
            routing_reference=settings.wire_eur_iban,
        ),
    ]


class CurrencyPricingOut(BaseModel):
    currency: str
    amount: int
    amount_annual: int = 0


class WirePricingOut(BaseModel):
    configured: bool
    currencies: list[CurrencyPricingOut]


@router.get("/wire/pricing", response_model=WirePricingOut)
async def wire_pricing(settings: Settings = Depends(get_settings)) -> WirePricingOut:
    """Public, unauthenticated -- prices only, no real bank account/SWIFT
    details. Backs the public /pricing page."""
    return WirePricingOut(
        configured=bool(settings.founder_bank_account_number),
        currencies=[
            CurrencyPricingOut(
                currency=c.currency, amount=c.amount, amount_annual=annual_price(c.amount, settings)
            )
            for c in _wire_currency_details(settings)
        ],
    )


@router.get("/wire/info", response_model=WireInfoOut)
async def wire_info(
    settings: Settings = Depends(get_settings),
    _founder: User = Depends(current_founder),
) -> WireInfoOut:
    """Founder-only -- this is the real bank account number, SWIFT code,
    and correspondent-bank routing details to wire real money to. First
    fixed to require any signed-in caller, which turned out not to be a
    real barrier: registration is free and instant, so any client (even a
    throwaway account created seconds earlier) could still reach it.
    Tightened to founder-only on direct instruction -- no client account,
    however genuine, gets this from the app anymore. A client who wants to
    pay gets the same details emailed to their own registered address
    instead (POST /wire/email-details below), rather than reading them back
    from an API response. The public price-only shape stays at
    /wire/pricing above."""
    return WireInfoOut(
        account_name=settings.founder_bank_account_name,
        account_number=settings.founder_bank_account_number,
        bank_name=settings.founder_bank_name,
        swift_code=settings.founder_bank_swift_code,
        configured=bool(settings.founder_bank_account_number),
        currencies=_wire_currency_details(settings),
    )


@router.post("/wire/claim", status_code=status.HTTP_201_CREATED, response_model=ClaimOut)
async def submit_wire_claim(
    payload: WireClaimIn,
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
    user: User = Depends(current_user),
) -> ClaimOut:
    if not settings.founder_bank_account_number:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Wire payment is not configured")
    amounts = {d.currency: d.amount for d in _wire_currency_details(settings)}
    # Annual matters most on this rail: an OUR-charge wire costs the sender
    # roughly USD 15-40 in fees, which is a >100% surcharge on a monthly
    # subscription but a one-off on an annual one.
    amount = price_for(amounts[payload.currency], payload.billing_period, settings)
    return await _insert_claim(
        database, settings, user, "wire", payload.currency, amount, payload.reference, payload.billing_period
    )


class WireEmailDetailsIn(BaseModel):
    currency: str = Field(pattern="^(USD|GBP|EUR)$")
    billing_period: BillingPeriod = "monthly"


@router.post("/wire/email-details", response_model=EmailDetailsOut)
async def email_wire_details(
    payload: WireEmailDetailsIn,
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
    user: User = Depends(current_user),
) -> EmailDetailsOut:
    """Wire equivalent of email_upi_details above -- same self-serve
    reasoning, same per-account rate limit (shared counter action name is
    deliberately different per method so a client exhausting the UPI limit
    can still request wire details, and vice versa)."""
    if not settings.founder_bank_account_number:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Wire payment is not configured")
    allowed = await try_record_action(
        database, user.id, "wire_details_email", MAX_PAYMENT_DETAILS_EMAILS_PER_WINDOW, PAYMENT_DETAILS_EMAIL_WINDOW_MS
    )
    if not allowed:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=RATE_LIMITED_DETAIL)
    details = next(d for d in _wire_currency_details(settings) if d.currency == payload.currency)
    try:
        await run_in_threadpool(
            send_wire_payment_details_email,
            settings,
            user.email,
            secrets.token_hex(8),
            details.currency,
            # Same reasoning as the UPI path above: the quoted amount must
            # match what submit_wire_claim records for this period, or the
            # credited amount can never match the claim.
            price_for(details.amount, payload.billing_period, settings),
            settings.founder_bank_account_name,
            settings.founder_bank_account_number,
            settings.founder_bank_name,
            settings.founder_bank_swift_code,
            details.correspondent_bank,
            details.correspondent_swift,
            details.nostro_account,
            details.routing_reference,
        )
    except EmailNotConfiguredError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Email is not configured") from error
    except resend.exceptions.ResendError as error:
        # Same reasoning as email_upi_details' identical except block above.
        logger.warning("wire_payment_details_email_failed", extra={"user_id": user.id}, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not send the email right now. Try again, or email the founder directly.",
        ) from error
    return EmailDetailsOut(sent=True)


@router.get("/wire/claims", response_model=list[ClaimOut])
async def my_wire_claims(
    database: Database = Depends(get_database),
    user: User = Depends(current_user),
) -> list[ClaimOut]:
    rows = await database.fetch_all(
        f"""SELECT {_CLAIM_COLUMNS}
           FROM payment_claims WHERE user_id=%s AND method='wire' AND product='postmortem'
           ORDER BY created_at DESC""",
        (user.id,),
    )
    return [ClaimOut(**row) for row in rows]
