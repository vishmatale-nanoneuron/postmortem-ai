"""Real Stripe subscription billing -- Checkout for signup, the Customer
Portal for self-service management, and a signature-verified webhook as the
actual source of truth for subscription state (per Stripe's own guidance:
a subscription integration isn't complete without one -- renewals, failed
payments, and cancellations happen asynchronously and are otherwise
invisible to this backend).
"""

import logging

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from ...auth import User, current_user
from ...database import Database
from ...dependencies import get_database
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
async def billing_status(
    database: Database = Depends(get_database),
    user: User = Depends(current_user),
) -> BillingStatusOut:
    row = await database.fetch_one(
        "SELECT subscription_status, current_period_end FROM users WHERE id=%s", (user.id,)
    )
    row = row or {}
    return BillingStatusOut(
        subscription_status=row.get("subscription_status", "none"),
        current_period_end=row.get("current_period_end"),
        has_active_subscription=user.has_active_subscription,
    )


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
