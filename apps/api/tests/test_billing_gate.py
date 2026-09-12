"""The actual paywall: an unpaid account cannot create/mutate incidents, the
founder account is exempt from it, and a manually approved (UPI/wire)
subscription grants access for exactly its period. Real end-to-end against
Postgres. The only payment rails are the manual ones; there is no card
processor and no webhook-driven subscription state.
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
    # Spend the free incident first, so what follows exercises the real
    # paywall and not the one-incident trial (restored 2026-09-10 -- see
    # auth.py's has_free_incident_available).
    await client.post("/v1/postmortems/incidents", json={"title": "Trial incident", "severity": "sev4"})

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
async def test_a_manually_approved_subscription_stops_granting_access_after_its_period_ends(context) -> None:
    # Regression for a real bug: approve_payment_claim (founder.py) computes
    # a 30-day current_period_end but, before this fix, nothing ever
    # compared it to now -- subscription_status='active' alone granted
    # access forever, so a single UPI/wire payment bought permanent access
    # instead of the one month it was actually billed for.
    client, database = context
    await client.post("/v1/auth/register", json={"email": UNPAID_EMAIL, "password": "correct-horse-battery"})
    # Spend the free incident first, so what follows exercises the real
    # paywall and not the one-incident trial (restored 2026-09-10 -- see
    # auth.py's has_free_incident_available).
    await client.post("/v1/postmortems/incidents", json={"title": "Trial incident", "severity": "sev4"})
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
