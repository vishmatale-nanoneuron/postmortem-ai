"""End-to-end: a forwarded bank alert marks a matching pending claim
bank_verified, through the real route (not just the parser in isolation,
test_bank_alerts.py) -- and, per explicit instruction, never grants access
by itself. Only a founder approving the claim (api/v1/founder.py) does
that, proven here by chaining webhook -> founder approve -> access.
"""

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not configured")

CLIENT_EMAIL = "bank-alert-test-client@example.com"
FOUNDER_EMAIL = "bank-alert-test-founder@example.com"
WEBHOOK_SECRET = "test-bank-alert-secret"


@pytest_asyncio.fixture
async def context(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL or "")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-used")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("FOUNDER_EMAIL", FOUNDER_EMAIL)
    monkeypatch.setenv("FOUNDER_UPI_ID", "founder@upi")
    monkeypatch.setenv("SUBSCRIPTION_PRICE_INR", "999")
    monkeypatch.setenv("BANK_ALERT_WEBHOOK_SECRET", WEBHOOK_SECRET)

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
        yield client, database

    await database.close()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_a_matching_bank_alert_verifies_but_does_not_grant_access(context) -> None:
    client, database = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})

    claim = await client.post("/v1/billing/upi/claim", json={"reference": "VERIFYONLY123456"})
    assert claim.status_code == 201, claim.text

    alert_text = (
        "Dear Customer, Rs.999.00 credited to your A/c No XX0454 on 25-08-26 "
        "through UPI Ref No VERIFYONLY123456. -Axis Bank"
    )
    webhook_response = await client.post(
        "/v1/billing/bank-alert", json={"text": alert_text}, headers={"x-bank-alert-secret": WEBHOOK_SECRET}
    )
    assert webhook_response.status_code == 200, webhook_response.text
    body = webhook_response.json()
    assert body["matched"] is True
    assert body["reference"] == "VERIFYONLY123456"

    # Verified, but NOT approved and NOT granted access -- the whole point.
    me = await client.get("/v1/auth/me")
    assert me.json()["has_active_subscription"] is False

    row = await database.fetch_one(
        "SELECT status, bank_verified FROM payment_claims WHERE reference=%s", ("VERIFYONLY123456",)
    )
    assert row["status"] == "pending"
    assert row["bank_verified"] is True


@pytest.mark.asyncio
async def test_a_founder_still_must_explicitly_approve_a_bank_verified_claim(context) -> None:
    # The full real chain: webhook verifies -> a founder still has to
    # approve -> only then does access exist. Bank-verification is a
    # signal shown to the founder, never a bypass of their approval.
    client, _ = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})
    claim = await client.post("/v1/billing/upi/claim", json={"reference": "CHAINCHECK123456"})
    claim_id = claim.json()["id"]
    client.cookies.clear()

    await client.post(
        "/v1/billing/bank-alert",
        json={"text": "Rs.999.00 credited to your account. UPI Ref No CHAINCHECK123456."},
        headers={"x-bank-alert-secret": WEBHOOK_SECRET},
    )

    await client.post("/v1/auth/register", json={"email": FOUNDER_EMAIL, "password": "correct-horse-battery"})
    listing = await client.get("/v1/founder/payment-claims")
    matching = next(c for c in listing.json() if c["id"] == claim_id)
    assert matching["bank_verified"] is True
    assert matching["status"] == "pending"

    approve = await client.post(f"/v1/founder/payment-claims/{claim_id}/approve")
    assert approve.status_code == 200, approve.text
    assert approve.json()["status"] == "approved"


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
async def test_a_debit_alert_is_never_treated_as_a_verification(context) -> None:
    # The one check that would be actively dangerous to get wrong -- proven
    # through the real route, not just the parser function.
    client, database = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})
    await client.post("/v1/billing/upi/claim", json={"reference": "DEBITTEST123456"})

    response = await client.post(
        "/v1/billing/bank-alert",
        json={"text": "Rs.999.00 debited from your A/c No XX0454. UPI Ref No DEBITTEST123456."},
        headers={"x-bank-alert-secret": WEBHOOK_SECRET},
    )
    assert response.status_code == 200
    assert response.json()["matched"] is False

    row = await database.fetch_one(
        "SELECT bank_verified FROM payment_claims WHERE reference=%s", ("DEBITTEST123456",)
    )
    assert row["bank_verified"] is False


@pytest.mark.asyncio
async def test_an_amount_mismatch_refuses_to_verify(context) -> None:
    client, database = context
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

    row = await database.fetch_one(
        "SELECT bank_verified FROM payment_claims WHERE reference=%s", ("MISMATCH123456",)
    )
    assert row["bank_verified"] is False


@pytest.mark.asyncio
async def test_a_matching_alert_via_query_param_secret_and_form_body(context) -> None:
    # SMS-forwarder apps typically can't set custom headers or build JSON
    # -- a fixed webhook URL with the secret as a query param, and the
    # message as a form field, is the shape those apps can actually send.
    client, database = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})
    await client.post("/v1/billing/upi/claim", json={"reference": "SMSFORM123456"})

    response = await client.post(
        f"/v1/billing/bank-alert?secret={WEBHOOK_SECRET}",
        data={"message": "Rs.999.00 credited to your A/c. UPI Ref No SMSFORM123456."},
    )
    assert response.status_code == 200, response.text
    assert response.json()["matched"] is True

    row = await database.fetch_one("SELECT bank_verified FROM payment_claims WHERE reference=%s", ("SMSFORM123456",))
    assert row["bank_verified"] is True


@pytest.mark.asyncio
async def test_a_matching_alert_via_raw_plain_text_body(context) -> None:
    # The simplest possible contract: an app that can only POST the raw
    # SMS text with no structure at all, secret in the query string.
    client, database = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})
    await client.post("/v1/billing/upi/claim", json={"reference": "SMSPLAIN123456"})

    response = await client.post(
        f"/v1/billing/bank-alert?secret={WEBHOOK_SECRET}",
        content=b"Rs.999.00 credited to your A/c. UPI Ref No SMSPLAIN123456.",
        headers={"content-type": "text/plain"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["matched"] is True

    row = await database.fetch_one("SELECT bank_verified FROM payment_claims WHERE reference=%s", ("SMSPLAIN123456",))
    assert row["bank_verified"] is True


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
