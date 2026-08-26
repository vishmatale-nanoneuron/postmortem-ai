"""Real Stripe subscription billing -- Checkout for signup, the Customer
Portal for self-service management, and a signature-verified webhook as the
actual source of truth for subscription state (per Stripe's own guidance:
a subscription integration isn't complete without one -- renewals, failed
payments, and cancellations happen asynchronously and are otherwise
invisible to this backend).
"""

import logging
import time

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from ...auth import User, current_founder, current_user
from ...database import Database
from ...dependencies import get_database
from ...services.billing import record_claim_event
from ...settings import Settings, get_settings

logger = logging.getLogger("postmortem_ai")

router = APIRouter(prefix="/v1/billing", tags=["billing"])

# Subscription lifecycle events only -- checkout completing, a renewal or
# plan change, and cancellation/non-renewal. invoice.payment_failed is
# handled too so a past-due account is reflected immediately rather than
# waiting for Stripe's own retry schedule to eventually fire
# customer.subscription.updated.
HANDLED_EVENTS = {
    "checkout.session.completed",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "invoice.payment_failed",
}


class CheckoutOut(BaseModel):
    url: str


class BillingStatusOut(BaseModel):
    subscription_status: str
    current_period_end: int | None
    has_active_subscription: bool


def _client(settings: Settings) -> stripe.StripeClient:
    if not settings.stripe_secret_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Card payments are not available yet -- use UPI (/v1/billing/upi/info)",
        )
    return stripe.StripeClient(api_key=settings.stripe_secret_key)


async def _get_or_create_customer(
    database: Database, client: stripe.StripeClient, user: User, existing_customer_id: str | None
) -> str:
    if existing_customer_id:
        return existing_customer_id
    customer = client.customers.create(params={"email": user.email, "metadata": {"user_id": user.id}})
    await database.execute("UPDATE users SET stripe_customer_id=%s WHERE id=%s", (customer.id, user.id))
    return customer.id


@router.post("/checkout", response_model=CheckoutOut)
async def create_checkout_session(
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
    user: User = Depends(current_user),
) -> CheckoutOut:
    if user.has_active_subscription:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already subscribed")

    row = await database.fetch_one("SELECT stripe_customer_id FROM users WHERE id=%s", (user.id,))
    client = _client(settings)
    customer_id = await _get_or_create_customer(database, client, user, (row or {}).get("stripe_customer_id"))

    session = client.checkout.sessions.create(
        params={
            "mode": "subscription",
            "customer": customer_id,
            # No payment_method_types -- Stripe determines eligible payment
            # methods dynamically from Dashboard settings.
            "line_items": [{"price": settings.stripe_price_id, "quantity": 1}],
            "success_url": f"{settings.frontend_url}/?checkout=success",
            "cancel_url": f"{settings.frontend_url}/?checkout=cancelled",
        }
    )
    assert session.url is not None
    return CheckoutOut(url=session.url)


@router.post("/portal", response_model=CheckoutOut)
async def create_portal_session(
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
    user: User = Depends(current_user),
) -> CheckoutOut:
    row = await database.fetch_one("SELECT stripe_customer_id FROM users WHERE id=%s", (user.id,))
    customer_id = (row or {}).get("stripe_customer_id")
    if not customer_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No billing account yet")

    client = _client(settings)
    session = client.billing_portal.sessions.create(
        params={"customer": customer_id, "return_url": settings.frontend_url}
    )
    return CheckoutOut(url=session.url)


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


class CardPricingOut(BaseModel):
    configured: bool


@router.get("/card/pricing", response_model=CardPricingOut)
async def card_pricing(settings: Settings = Depends(get_settings)) -> CardPricingOut:
    """Public, unauthenticated -- same shape/purpose as /upi/pricing and
    /wire/pricing below: lets the frontend decide whether to show a 'Card'
    option at all, without needing to be signed in (or triggering the 503
    from POST /checkout) just to find out Stripe isn't configured in this
    environment. The real Stripe integration (checkout/portal/webhook above)
    existed for a long time with no frontend surface calling it at all --
    every client only ever saw the manual UPI/wire tabs, so self-serve card
    payment and self-serve subscription management (cancel, update card,
    view invoices via the Customer Portal) were both effectively dead code
    from a client's perspective. This endpoint is what lets the frontend
    turn that back on safely, everywhere it's actually configured."""
    return CardPricingOut(configured=bool(settings.stripe_secret_key and settings.stripe_price_id))


async def _apply_subscription(database: Database, customer_id: str, subscription: stripe.Subscription) -> None:
    updated = await database.execute(
        """UPDATE users SET stripe_subscription_id=%s, subscription_status=%s, current_period_end=%s
           WHERE stripe_customer_id=%s""",
        (subscription.id, subscription.status, subscription.current_period_end, customer_id),
    )
    if not updated:
        # A webhook can arrive for a customer this backend doesn't
        # recognize (e.g. a Dashboard-created test event) -- log and move
        # on rather than raising, since raising would make Stripe retry a
        # webhook that will never succeed.
        logger.warning("Stripe webhook for unknown customer_id=%s", customer_id)


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> dict[str, bool]:
    if not settings.stripe_webhook_secret:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Stripe is not configured")

    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, signature, settings.stripe_webhook_secret)
    except (ValueError, stripe.SignatureVerificationError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook signature") from exc

    if event["type"] not in HANDLED_EVENTS:
        return {"ok": True}

    client = _client(settings)
    data = event["data"]["object"]

    if event["type"] == "checkout.session.completed":
        customer_id = data["customer"]
        subscription_id = data.get("subscription")
        if subscription_id:
            subscription = client.subscriptions.retrieve(subscription_id)
            await _apply_subscription(database, customer_id, subscription)
    elif event["type"] in ("customer.subscription.updated", "customer.subscription.deleted"):
        await _apply_subscription(database, data["customer"], data)
    elif event["type"] == "invoice.payment_failed":
        subscription_id = data.get("subscription")
        if subscription_id:
            subscription = client.subscriptions.retrieve(subscription_id)
            await _apply_subscription(database, data["customer"], subscription)

    logger.info("stripe_webhook_handled type=%s", event["type"])
    return {"ok": True}


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


class ClaimOut(BaseModel):
    id: str
    method: str
    currency: str
    amount: int
    reference: str
    status: str
    created_at: int


async def _insert_claim(
    database: Database, user: User, method: str, currency: str, amount: int, reference: str
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
        """INSERT INTO payment_claims (user_id, amount_inr, currency, method, reference, status, created_at)
           VALUES (%s, %s, %s, %s, %s, 'pending', %s)
           RETURNING id::text, method, currency, amount_inr AS amount, reference, status, created_at""",
        (user.id, amount, currency, method, reference, now),
    )
    assert row is not None
    await record_claim_event(database, row["id"], "created", user.email, f"{currency} {amount} via {method}")
    return ClaimOut(**row)


class PatchClaimIn(BaseModel):
    reference: str = Field(min_length=4, max_length=200)


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
           RETURNING id::text, method, currency, amount_inr AS amount, reference, status, created_at""",
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
    configured: bool


@router.get("/upi/pricing", response_model=UpiPricingOut)
async def upi_pricing(settings: Settings = Depends(get_settings)) -> UpiPricingOut:
    """Public, unauthenticated -- price only, no real UPI ID. Backs the
    public /pricing page, which never needs the actual account to render a
    price."""
    return UpiPricingOut(amount_inr=settings.subscription_price_inr, configured=bool(settings.founder_upi_id))


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
    wants to pay is told to contact the founder directly (see workspace.tsx
    UpiPayment/WirePayment) instead of self-serving the account details.
    The public price-only shape stays at /upi/pricing above."""
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
    return await _insert_claim(database, user, "upi", "INR", settings.subscription_price_inr, payload.reference)


@router.get("/upi/claims", response_model=list[ClaimOut])
async def my_upi_claims(
    database: Database = Depends(get_database),
    user: User = Depends(current_user),
) -> list[ClaimOut]:
    rows = await database.fetch_all(
        """SELECT id::text, method, currency, amount_inr AS amount, reference, status, created_at
           FROM payment_claims WHERE user_id=%s AND method='upi' ORDER BY created_at DESC""",
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


class WirePricingOut(BaseModel):
    configured: bool
    currencies: list[CurrencyPricingOut]


@router.get("/wire/pricing", response_model=WirePricingOut)
async def wire_pricing(settings: Settings = Depends(get_settings)) -> WirePricingOut:
    """Public, unauthenticated -- prices only, no real bank account/SWIFT
    details. Backs the public /pricing page."""
    return WirePricingOut(
        configured=bool(settings.founder_bank_account_number),
        currencies=[CurrencyPricingOut(currency=c.currency, amount=c.amount) for c in _wire_currency_details(settings)],
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
    pay is told to contact the founder directly (see workspace.tsx
    UpiPayment/WirePayment) instead of self-serving the account details.
    The public price-only shape stays at /wire/pricing above."""
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
    return await _insert_claim(database, user, "wire", payload.currency, amounts[payload.currency], payload.reference)


@router.get("/wire/claims", response_model=list[ClaimOut])
async def my_wire_claims(
    database: Database = Depends(get_database),
    user: User = Depends(current_user),
) -> list[ClaimOut]:
    rows = await database.fetch_all(
        """SELECT id::text, method, currency, amount_inr AS amount, reference, status, created_at
           FROM payment_claims WHERE user_id=%s AND method='wire' ORDER BY created_at DESC""",
        (user.id,),
    )
    return [ClaimOut(**row) for row in rows]
