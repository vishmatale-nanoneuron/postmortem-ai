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
    # sk_live_ prefix, not sk_test_ -- card_pricing/`_client` (billing.py)
    # both now require this exact prefix to treat Stripe as genuinely
    # configured (a real test-mode key produces a real, unmistakably
    # TestMode checkout session that cannot process real money, confirmed
    # live before that fix existed). This key is still never actually
    # called in these tests -- only its shape matters here.
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_not-called-in-these-tests")
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
async def test_an_unpaid_account_cannot_create_any_incident(context) -> None:
    # The free-incident trial is retired for new grants (see
    # test_free_incident.py) -- a brand new unpaid account is paywalled
    # starting from its very first incident, not just the second.
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
async def test_card_pricing_reports_configured_when_stripe_env_is_set(context) -> None:
    # Public, unauthenticated -- the frontend uses this to decide whether to
    # show a "Card" subscribe option at all, without needing to sign in or
    # trigger the 503 from POST /checkout just to find out.
    client, _ = context
    response = await client.get("/v1/billing/card/pricing")
    assert response.status_code == 200
    assert response.json() == {"configured": True}


@pytest.mark.asyncio
async def test_card_pricing_reports_unconfigured_without_a_stripe_price_id(context, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.settings import get_settings

    monkeypatch.delenv("STRIPE_PRICE_ID", raising=False)
    get_settings.cache_clear()
    client, _ = context
    response = await client.get("/v1/billing/card/pricing")
    assert response.status_code == 200
    assert response.json() == {"configured": False}


@pytest.mark.asyncio
async def test_a_test_mode_stripe_key_reports_unconfigured_not_a_false_positive(
    context, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real bug this covers: a test-mode key (sk_test_...) makes real,
    real-shaped Stripe API calls that succeed and produce a real Checkout
    Session URL -- nothing about the response shape reveals it can't
    process real money. configured=True here would tell a real client
    "card payment works," and only Stripe's own checkout page (unmistakably
    marked TestMode) would ever reveal otherwise -- caught live in
    production, not by this test alone."""
    from app.settings import get_settings

    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_looks-configured-but-is-not-live")
    get_settings.cache_clear()
    client, _ = context
    response = await client.get("/v1/billing/card/pricing")
    assert response.status_code == 200
    assert response.json() == {"configured": False}


@pytest.mark.asyncio
async def test_checkout_refuses_to_create_a_session_on_a_test_mode_key(
    context, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defense in depth beyond card_pricing's own check above: even a
    caller that never looked at /card/pricing first (a stale cached
    frontend build, a direct API call, an MCP tool) must not be able to
    create a real Checkout Session URL on a test-mode key."""
    from app.settings import get_settings

    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_looks-configured-but-is-not-live")
    get_settings.cache_clear()
    client, _ = context
    await client.post("/v1/auth/register", json={"email": UNPAID_EMAIL, "password": "correct-horse-battery"})

    response = await client.post("/v1/billing/checkout")
    assert response.status_code == 503
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_a_live_restricted_key_reports_configured_not_a_false_negative(
    context, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The opposite bug from the test-mode case above: Stripe's own docs
    recommend a restricted key (rk_live_...) over a full secret key
    wherever possible, and Vercel's Stripe Marketplace integration may
    provision one. A genuinely live rk_live_ key being reported as
    unconfigured -- because an earlier version of this check only
    recognized the sk_live_ prefix -- would block real revenue for a
    caller who followed Stripe's own security recommendation."""
    from app.settings import get_settings

    monkeypatch.setenv("STRIPE_SECRET_KEY", "rk_live_a-real-restricted-key-would-look-like-this")
    get_settings.cache_clear()
    client, _ = context
    response = await client.get("/v1/billing/card/pricing")
    assert response.status_code == 200
    assert response.json() == {"configured": True}
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_a_test_mode_restricted_key_still_reports_unconfigured(
    context, monkeypatch: pytest.MonkeyPatch
) -> None:
    """rk_test_ must be rejected exactly like sk_test_ -- broadening the
    check to accept restricted keys must not accidentally broaden it to
    accept test-mode ones too."""
    from app.settings import get_settings

    monkeypatch.setenv("STRIPE_SECRET_KEY", "rk_test_looks-configured-but-is-not-live")
    get_settings.cache_clear()
    client, _ = context
    response = await client.get("/v1/billing/card/pricing")
    assert response.status_code == 200
    assert response.json() == {"configured": False}
    get_settings.cache_clear()


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
