"""Annual billing on the manual (UPI/wire) rails.

The driver is international wire economics: an OUR-charge SWIFT wire costs
the sender roughly USD 15-40 in fees, which is a >100% surcharge on a monthly
subscription but a one-off on an annual one.
"""

import os
import time

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not configured")

CLIENT_EMAIL = "annual-test-client@example.com"
FOUNDER_EMAIL = "annual-test-founder@example.com"


@pytest_asyncio.fixture
async def context(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL or "")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-used")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("FOUNDER_EMAIL", FOUNDER_EMAIL)
    monkeypatch.setenv("FOUNDER_UPI_ID", "founder@upi")
    monkeypatch.setenv("SUBSCRIPTION_PRICE_INR", "999")

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
async def test_an_annual_claim_is_priced_at_ten_months_not_twelve(context) -> None:
    client, _ = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})
    claim = await client.post(
        "/v1/billing/upi/claim", json={"reference": "ANNUALPRICE12345", "billing_period": "annual"}
    )
    assert claim.status_code == 201, claim.text
    body = claim.json()
    assert body["amount"] == 9990  # 999 x 10, the "two months free" discount
    assert body["billing_period"] == "annual"


@pytest.mark.asyncio
async def test_a_client_cannot_buy_a_year_at_the_monthly_price(context) -> None:
    """The security property. The amount is derived server-side from the
    period; a client-supplied amount would let anyone claim a year for the
    price of a month. Sending an amount must simply be ignored."""
    client, _ = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})
    claim = await client.post(
        "/v1/billing/upi/claim",
        json={"reference": "CHEAPYEAR1234567", "billing_period": "annual", "amount": 999, "amount_inr": 999},
    )
    assert claim.status_code == 201, claim.text
    assert claim.json()["amount"] == 9990  # the injected 999 was ignored


@pytest.mark.asyncio
async def test_omitting_the_period_still_works_and_stays_monthly(context) -> None:
    """An older client that doesn't know about the field must keep working,
    and must get the smaller grant rather than a free year."""
    client, _ = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})
    claim = await client.post("/v1/billing/upi/claim", json={"reference": "NOPERIODFIELD123"})
    assert claim.status_code == 201, claim.text
    assert claim.json()["billing_period"] == "monthly"
    assert claim.json()["amount"] == 999


@pytest.mark.asyncio
async def test_an_invalid_period_is_rejected_at_the_edge(context) -> None:
    client, _ = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})
    claim = await client.post(
        "/v1/billing/upi/claim", json={"reference": "BADPERIOD1234567", "billing_period": "forever"}
    )
    assert claim.status_code == 422


@pytest.mark.asyncio
async def test_approving_an_annual_claim_grants_a_year_not_a_month(context) -> None:
    """The whole point: what gets granted must match what was paid for, and
    the period comes from the stored claim rather than the approving
    request."""
    client, database = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})
    claim = await client.post(
        "/v1/billing/upi/claim", json={"reference": "GRANTAYEAR123456", "billing_period": "annual"}
    )
    claim_id = claim.json()["id"]
    client.cookies.clear()

    await client.post("/v1/auth/register", json={"email": FOUNDER_EMAIL, "password": "correct-horse-battery"})
    approve = await client.post(f"/v1/founder/payment-claims/{claim_id}/approve")
    assert approve.status_code == 200, approve.text

    row = await database.fetch_one(
        "SELECT subscription_status, current_period_end FROM users WHERE email=%s", (CLIENT_EMAIL,)
    )
    assert row is not None and row["subscription_status"] == "active"
    days_granted = (row["current_period_end"] - int(time.time())) / 86400
    assert 360 < days_granted <= 365, days_granted


@pytest.mark.asyncio
async def test_approving_a_monthly_claim_still_grants_only_a_month(context) -> None:
    client, database = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})
    claim = await client.post("/v1/billing/upi/claim", json={"reference": "STILLMONTHLY1234"})
    claim_id = claim.json()["id"]
    client.cookies.clear()

    await client.post("/v1/auth/register", json={"email": FOUNDER_EMAIL, "password": "correct-horse-battery"})
    await client.post(f"/v1/founder/payment-claims/{claim_id}/approve")

    row = await database.fetch_one("SELECT current_period_end FROM users WHERE email=%s", (CLIENT_EMAIL,))
    days_granted = (row["current_period_end"] - int(time.time())) / 86400
    assert 25 < days_granted <= 30, days_granted


@pytest.mark.asyncio
async def test_pricing_endpoints_publish_the_annual_price(context) -> None:
    client, _ = context
    upi = await client.get("/v1/billing/upi/pricing")
    assert upi.json()["amount_inr_annual"] == 9990
    wire = await client.get("/v1/billing/wire/pricing")
    for c in wire.json()["currencies"]:
        assert c["amount_annual"] == c["amount"] * 10
