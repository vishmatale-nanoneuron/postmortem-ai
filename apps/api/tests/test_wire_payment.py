"""Manual international SWIFT wire payment -- the second manual payment
method alongside UPI, for clients outside India where UPI can't reach
(it requires an Indian bank account on the payer's side). Same claim/
review table and founder-approval flow as UPI, just a different method.
"""

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not configured")

CLIENT_EMAIL = "wire-test-client@example.com"
FOUNDER_EMAIL = "wire-test-founder@example.com"


@pytest_asyncio.fixture
async def context(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL or "")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-used")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("FOUNDER_EMAIL", FOUNDER_EMAIL)
    monkeypatch.setenv("FOUNDER_BANK_ACCOUNT_NAME", "NANONEURON SERVICES")
    monkeypatch.setenv("FOUNDER_BANK_ACCOUNT_NUMBER", "922020067340454")
    monkeypatch.setenv("FOUNDER_BANK_NAME", "Axis Bank Ltd")
    monkeypatch.setenv("FOUNDER_BANK_SWIFT_CODE", "AXISINBBA02")
    monkeypatch.setenv("SUBSCRIPTION_PRICE_USD", "15")
    monkeypatch.setenv("WIRE_USD_CORRESPONDENT_BANK", "JP Morgan Chase Bank, New York")
    monkeypatch.setenv("WIRE_USD_CORRESPONDENT_SWIFT", "CHASUS33")
    monkeypatch.setenv("WIRE_USD_NOSTRO_ACCOUNT", "11407376")
    monkeypatch.setenv("WIRE_USD_ABA", "FED ABA 0210-0002-1")
    monkeypatch.delenv("FOUNDER_UPI_ID", raising=False)

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
async def test_wire_info_reflects_configured_beneficiary_and_correspondent_details_for_the_founder(context) -> None:
    client, _, _ = context
    await client.post("/v1/auth/register", json={"email": FOUNDER_EMAIL, "password": "correct-horse-battery"})

    response = await client.get("/v1/billing/wire/info")
    assert response.status_code == 200
    body = response.json()
    assert body["account_name"] == "NANONEURON SERVICES"
    assert body["account_number"] == "922020067340454"
    assert body["swift_code"] == "AXISINBBA02"
    assert body["configured"] is True
    usd = next(c for c in body["currencies"] if c["currency"] == "USD")
    assert usd["amount"] == 15
    assert usd["correspondent_swift"] == "CHASUS33"


@pytest.mark.asyncio
async def test_wire_info_is_not_reachable_by_a_regular_signed_in_client(context) -> None:
    # Regression for a second real gap: requiring "any signed-in user"
    # wasn't a real barrier either, since registration is free and instant
    # -- a client account, however genuine, must never get the real bank
    # details from this route. Only the founder can.
    client, _, _ = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})

    response = await client.get("/v1/billing/wire/info")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_wire_info_is_not_reachable_without_signing_in(context) -> None:
    # Regression for a real bug: this route previously had no auth
    # dependency at all -- the real bank account number and SWIFT code
    # were fetchable by anyone on the internet with a single
    # unauthenticated GET.
    client, _, _ = context
    response = await client.get("/v1/billing/wire/info")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_wire_pricing_is_public_and_never_includes_real_bank_details(context) -> None:
    # The public /pricing page needs prices to render without requiring a
    # login -- this is the safe, unauthenticated shape: currency/amount
    # only, no account number, no SWIFT code, no correspondent details.
    client, _, _ = context
    response = await client.get("/v1/billing/wire/pricing")
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True
    usd = next(c for c in body["currencies"] if c["currency"] == "USD")
    assert usd == {"currency": "USD", "amount": 15}
    assert "account_number" not in body
    assert "swift_code" not in body
    assert "correspondent_swift" not in usd


@pytest.mark.asyncio
async def test_a_wire_claim_requires_a_supported_currency(context) -> None:
    client, _, _ = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})

    response = await client.post("/v1/billing/wire/claim", json={"currency": "JPY", "reference": "WIRE-REF-1"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_a_founder_approving_a_wire_claim_grants_access(context) -> None:
    client, database, application = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})

    claim = await client.post("/v1/billing/wire/claim", json={"currency": "USD", "reference": "SWIFT-REF-99"})
    assert claim.status_code == 201, claim.text
    assert claim.json() == {
        "id": claim.json()["id"],
        "method": "wire",
        "currency": "USD",
        "amount": 15,
        "reference": "SWIFT-REF-99",
        "status": "pending",
        "created_at": claim.json()["created_at"],
    }
    claim_id = claim.json()["id"]

    # A pending, unapproved claim must not itself grant access -- blocked
    # until a founder approves it, exactly like an unapproved UPI claim.
    blocked = await client.post("/v1/postmortems/incidents", json={"title": "Should be blocked", "severity": "sev2"})
    assert blocked.status_code == 402

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as founder_client:
        await founder_client.post(
            "/v1/auth/register", json={"email": FOUNDER_EMAIL, "password": "correct-horse-battery"}
        )
        listing = await founder_client.get("/v1/founder/payment-claims")
        assert any(c["id"] == claim_id and c["method"] == "wire" and c["currency"] == "USD" for c in listing.json())

        approved = await founder_client.post(f"/v1/founder/payment-claims/{claim_id}/approve")
        assert approved.status_code == 200, approved.text

    row = await database.fetch_one("SELECT subscription_status FROM users WHERE email=%s", (CLIENT_EMAIL,))
    assert row is not None
    assert row["subscription_status"] == "active"

    unblocked = await client.post("/v1/postmortems/incidents", json={"title": "Now allowed", "severity": "sev2"})
    assert unblocked.status_code == 201, unblocked.text
