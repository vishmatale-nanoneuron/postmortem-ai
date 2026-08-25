"""Manual UPI payment: a client submits a transaction reference, the
founder reviews and approves/rejects, and approval is what actually flips
subscription_status -- real end-to-end against Postgres, no gateway
involved.
"""

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not configured")

CLIENT_EMAIL = "upi-test-client@example.com"
FOUNDER_EMAIL = "upi-test-founder@example.com"


@pytest_asyncio.fixture
async def context(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL or "")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-used")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("FOUNDER_EMAIL", FOUNDER_EMAIL)
    monkeypatch.setenv("FOUNDER_UPI_ID", "founder@upi")
    monkeypatch.setenv("SUBSCRIPTION_PRICE_INR", "999")
    # Deliberately no STRIPE_* vars -- proves the app runs, and this whole
    # flow works, with Stripe entirely unconfigured.
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("STRIPE_PRICE_ID", raising=False)

    from app.database import Database
    from app.main import create_app
    from app.settings import get_settings

    get_settings.cache_clear()
    database = Database(get_settings())
    await database.open()
    await database.execute("DELETE FROM users WHERE email IN (%s, %s)", (CLIENT_EMAIL, FOUNDER_EMAIL))

    application = create_app()
    application.state.database = database

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        yield client, database, application

    await database.close()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_upi_info_reflects_configured_settings(context) -> None:
    client, _, _ = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})

    response = await client.get("/v1/billing/upi/info")
    assert response.status_code == 200
    body = response.json()
    assert body == {"upi_id": "founder@upi", "payee_name": "PostMortem AI", "amount_inr": 999, "configured": True}


@pytest.mark.asyncio
async def test_submitting_a_claim_does_not_itself_grant_access(context) -> None:
    client, _, _ = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})

    claim = await client.post("/v1/billing/upi/claim", json={"reference": "UTR123456789"})
    assert claim.status_code == 201, claim.text
    assert claim.json()["status"] == "pending"

    # Still blocked -- a submitted claim is not the same as an approved one.
    blocked = await client.post("/v1/postmortems/incidents", json={"title": "Should be blocked", "severity": "sev2"})
    assert blocked.status_code == 402


@pytest.mark.asyncio
async def test_a_founder_approving_a_claim_grants_access(context) -> None:
    client, database, application = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})
    claim = await client.post("/v1/billing/upi/claim", json={"reference": "UTR-APPROVE-ME"})
    claim_id = claim.json()["id"]

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as founder_client:
        await founder_client.post(
            "/v1/auth/register", json={"email": FOUNDER_EMAIL, "password": "correct-horse-battery"}
        )
        listing = await founder_client.get("/v1/founder/payment-claims")
        assert listing.status_code == 200
        assert any(c["id"] == claim_id and c["email"] == CLIENT_EMAIL for c in listing.json())

        approved = await founder_client.post(f"/v1/founder/payment-claims/{claim_id}/approve")
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"

    row = await database.fetch_one(
        "SELECT subscription_status, current_period_end FROM users WHERE email=%s", (CLIENT_EMAIL,)
    )
    assert row is not None
    assert row["subscription_status"] == "active"
    assert row["current_period_end"] is not None

    # Now unblocked with the client's own session.
    unblocked = await client.post("/v1/postmortems/incidents", json={"title": "Now allowed", "severity": "sev2"})
    assert unblocked.status_code == 201, unblocked.text


@pytest.mark.asyncio
async def test_a_founder_rejecting_a_claim_leaves_access_blocked(context) -> None:
    client, database, application = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})
    claim = await client.post("/v1/billing/upi/claim", json={"reference": "UTR-REJECT-ME"})
    claim_id = claim.json()["id"]

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as founder_client:
        await founder_client.post(
            "/v1/auth/register", json={"email": FOUNDER_EMAIL, "password": "correct-horse-battery"}
        )
        rejected = await founder_client.post(f"/v1/founder/payment-claims/{claim_id}/reject")
        assert rejected.status_code == 200
        assert rejected.json()["status"] == "rejected"

    row = await database.fetch_one("SELECT subscription_status FROM users WHERE email=%s", (CLIENT_EMAIL,))
    assert row is not None
    assert row["subscription_status"] == "none"

    still_blocked = await client.post(
        "/v1/postmortems/incidents", json={"title": "Still blocked", "severity": "sev2"}
    )
    assert still_blocked.status_code == 402


@pytest.mark.asyncio
async def test_a_non_founder_cannot_see_or_approve_payment_claims(context) -> None:
    client, _, _ = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})

    assert (await client.get("/v1/founder/payment-claims")).status_code == 403
    assert (await client.post("/v1/founder/payment-claims/does-not-matter/approve")).status_code == 403


@pytest.mark.asyncio
async def test_stripe_routes_503_when_unconfigured(context) -> None:
    client, _, _ = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})

    assert (await client.post("/v1/billing/checkout")).status_code == 503
