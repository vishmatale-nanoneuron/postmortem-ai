"""End-to-end: a forwarded bank alert auto-approves a matching pending
claim and grants real access, through the real route -- not just the
parser in isolation (test_bank_alerts.py).
"""

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not configured")

CLIENT_EMAIL = "bank-alert-test-client@example.com"
WEBHOOK_SECRET = "test-bank-alert-secret"


@pytest_asyncio.fixture
async def context(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL or "")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-used")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("FOUNDER_UPI_ID", "founder@upi")
    monkeypatch.setenv("SUBSCRIPTION_PRICE_INR", "999")
    monkeypatch.setenv("BANK_ALERT_WEBHOOK_SECRET", WEBHOOK_SECRET)

    from app.database import Database
    from app.main import create_app
    from app.settings import get_settings

    get_settings.cache_clear()
    database = Database(get_settings())
    await database.open()
    await database.execute("DELETE FROM users WHERE email=%s", (CLIENT_EMAIL,))

    application = create_app()
    application.state.database = database

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        yield client, database

    await database.close()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_a_real_matching_bank_alert_auto_approves_and_grants_access(context) -> None:
    client, _ = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})

    claim = await client.post("/v1/billing/upi/claim", json={"reference": "AUTOAPPROVE123456"})
    assert claim.status_code == 201, claim.text

    # Not yet active -- the submitted claim alone never grants access.
    me_before = await client.get("/v1/auth/me")
    assert me_before.json()["has_active_subscription"] is False

    alert_text = (
        "Dear Customer, Rs.999.00 credited to your A/c No XX0454 on 25-08-26 "
        "through UPI Ref No AUTOAPPROVE123456. -Axis Bank"
    )
    webhook_response = await client.post(
        "/v1/billing/bank-alert", json={"text": alert_text}, headers={"x-bank-alert-secret": WEBHOOK_SECRET}
    )
    assert webhook_response.status_code == 200, webhook_response.text
    body = webhook_response.json()
    assert body["matched"] is True
    assert body["reference"] == "AUTOAPPROVE123456"

    me_after = await client.get("/v1/auth/me")
    assert me_after.json()["has_active_subscription"] is True


@pytest.mark.asyncio
async def test_the_webhook_rejects_a_wrong_secret(context) -> None:
    client, _ = context
    response = await client.post(
        "/v1/billing/bank-alert",
        json={"text": "Rs.999.00 credited. UPI Ref No 111222333444"},
        headers={"x-bank-alert-secret": "wrong-secret"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_a_debit_alert_never_auto_approves_anything(context) -> None:
    # The one check that would be actively dangerous to get wrong -- proven
    # through the real route, not just the parser function.
    client, _ = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})
    await client.post("/v1/billing/upi/claim", json={"reference": "DEBITTEST123456"})

    response = await client.post(
        "/v1/billing/bank-alert",
        json={"text": "Rs.999.00 debited from your A/c No XX0454. UPI Ref No DEBITTEST123456."},
        headers={"x-bank-alert-secret": WEBHOOK_SECRET},
    )
    assert response.status_code == 200
    assert response.json()["matched"] is False

    me = await client.get("/v1/auth/me")
    assert me.json()["has_active_subscription"] is False


@pytest.mark.asyncio
async def test_an_amount_mismatch_refuses_to_auto_approve(context) -> None:
    client, _ = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})
    await client.post("/v1/billing/upi/claim", json={"reference": "MISMATCH123456"})

    response = await client.post(
        "/v1/billing/bank-alert",
        # Real claim is for Rs.999 -- this alert claims a different amount.
        json={"text": "Rs.1.00 credited to your account. UPI Ref No MISMATCH123456."},
        headers={"x-bank-alert-secret": WEBHOOK_SECRET},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["matched"] is False
    assert "amount" in (body["reason"] or "").lower()

    me = await client.get("/v1/auth/me")
    assert me.json()["has_active_subscription"] is False


@pytest.mark.asyncio
async def test_a_reference_with_no_matching_pending_claim_does_not_error(context) -> None:
    client, _ = context
    response = await client.post(
        "/v1/billing/bank-alert",
        json={"text": "Rs.999.00 credited to your account. UPI Ref No NOMATCH000000"},
        headers={"x-bank-alert-secret": WEBHOOK_SECRET},
    )
    assert response.status_code == 200
    assert response.json()["matched"] is False
