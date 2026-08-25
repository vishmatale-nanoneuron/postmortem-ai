"""The actual paywall: an unpaid account cannot create/mutate incidents, and
the founder account is exempt from it. Real end-to-end against Postgres,
with the Stripe network calls themselves not exercised here (checkout/portal
creation and webhook signature verification are covered by unit-level shape
checks below and by manual verification against the real sandbox).
"""

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not configured")

UNPAID_EMAIL = "billing-test-unpaid@example.com"
FOUNDER_EMAIL = "billing-test-founder@example.com"


@pytest_asyncio.fixture
async def context(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL or "")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-used")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_not-called-in-these-tests")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_not-called-in-these-tests")
    monkeypatch.setenv("STRIPE_PRICE_ID", "price_not-called-in-these-tests")
    monkeypatch.setenv("FOUNDER_EMAIL", FOUNDER_EMAIL)

    from app.database import Database
    from app.main import create_app
    from app.settings import get_settings

    get_settings.cache_clear()
    database = Database(get_settings())
    await database.open()
    await database.execute("DELETE FROM users WHERE email IN (%s, %s)", (UNPAID_EMAIL, FOUNDER_EMAIL))

    application = create_app()
    application.state.database = database

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        yield client, database

    await database.close()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_an_unpaid_account_cannot_create_an_incident(context) -> None:
    client, _ = context
    await client.post("/v1/auth/register", json={"email": UNPAID_EMAIL, "password": "correct-horse-battery"})

    response = await client.post("/v1/postmortems/incidents", json={"title": "Should be blocked", "severity": "sev2"})
    assert response.status_code == 402
    assert "subscription" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_an_unpaid_account_can_still_read_its_own_history(context) -> None:
    client, _ = context
    await client.post("/v1/auth/register", json={"email": UNPAID_EMAIL, "password": "correct-horse-battery"})

    # Read routes stay reachable even without a subscription -- a lapsed
    # account can still see what it already has and be prompted to resubscribe.
    assert (await client.get("/v1/postmortems/incidents")).status_code == 200
    assert (await client.get("/v1/postmortems/summary")).status_code == 200


@pytest.mark.asyncio
async def test_the_founder_account_is_exempt_from_the_paywall(context) -> None:
    client, _ = context
    register = await client.post(
        "/v1/auth/register", json={"email": FOUNDER_EMAIL, "password": "correct-horse-battery"}
    )
    assert register.json()["is_founder"] is True

    response = await client.post(
        "/v1/postmortems/incidents", json={"title": "Founder-created incident", "severity": "sev2"}
    )
    assert response.status_code == 201, response.text


@pytest.mark.asyncio
async def test_checkout_is_refused_for_an_already_subscribed_account(context) -> None:
    client, database = context
    await client.post("/v1/auth/register", json={"email": UNPAID_EMAIL, "password": "correct-horse-battery"})
    await database.execute("UPDATE users SET subscription_status='active' WHERE email=%s", (UNPAID_EMAIL,))

    # Requires an outbound Stripe API call for a *new* customer, but an
    # already-active account is refused before that call is ever made --
    # this leg is reachable without real Stripe network access.
    response = await client.post("/v1/billing/checkout")
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_the_billing_portal_404s_before_any_checkout_has_happened(context) -> None:
    client, _ = context
    await client.post("/v1/auth/register", json={"email": UNPAID_EMAIL, "password": "correct-horse-battery"})

    response = await client.post("/v1/billing/portal")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_a_manually_approved_subscription_stops_granting_access_after_its_period_ends(context) -> None:
    # Regression for a real bug: approve_payment_claim (founder.py) computes
    # a 30-day current_period_end but, before this fix, nothing ever
    # compared it to now -- subscription_status='active' alone granted
    # access forever, so a single UPI/wire payment bought permanent access
    # instead of the one month it was actually billed for.
    client, database = context
    await client.post("/v1/auth/register", json={"email": UNPAID_EMAIL, "password": "correct-horse-battery"})
    await database.execute(
        "UPDATE users SET subscription_status='active', current_period_end=%s WHERE email=%s",
        (1, UNPAID_EMAIL),  # 1 = Unix epoch second 1, unambiguously in the past
    )

    response = await client.post(
        "/v1/postmortems/incidents", json={"title": "Should be blocked -- period lapsed", "severity": "sev2"}
    )
    assert response.status_code == 402


@pytest.mark.asyncio
async def test_an_expired_subscription_is_honestly_reported_not_shown_as_stale_active(context) -> None:
    # Regression for a real UX gap: subscription_status stays 'active' in
    # the database forever after a manual period lapses (there's no
    # recurring billing to flip it back) -- without this, /me and
    # /billing/status would keep telling the client "active" long after
    # access was actually cut off, which is actively misleading.
    client, database = context
    await client.post("/v1/auth/register", json={"email": UNPAID_EMAIL, "password": "correct-horse-battery"})
    await database.execute(
        "UPDATE users SET subscription_status='active', current_period_end=%s WHERE email=%s",
        (1, UNPAID_EMAIL),
    )

    me = await client.get("/v1/auth/me")
    assert me.json()["subscription_status"] == "expired"
    assert me.json()["has_active_subscription"] is False

    billing_status = await client.get("/v1/billing/status")
    assert billing_status.json()["subscription_status"] == "expired"


@pytest.mark.asyncio
async def test_a_manually_approved_subscription_grants_access_while_its_period_is_still_open(context) -> None:
    client, database = context
    await client.post("/v1/auth/register", json={"email": UNPAID_EMAIL, "password": "correct-horse-battery"})
    far_future = 4102444800  # 2100-01-01, unambiguously not-yet-expired
    await database.execute(
        "UPDATE users SET subscription_status='active', current_period_end=%s WHERE email=%s",
        (far_future, UNPAID_EMAIL),
    )

    response = await client.post(
        "/v1/postmortems/incidents", json={"title": "Should be allowed", "severity": "sev2"}
    )
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_a_webhook_with_an_invalid_signature_is_rejected(context) -> None:
    client, _ = context
    response = await client.post(
        "/v1/billing/webhook",
        content=b'{"type": "checkout.session.completed"}',
        headers={"stripe-signature": "t=1,v1=not-a-real-signature"},
    )
    assert response.status_code == 400
