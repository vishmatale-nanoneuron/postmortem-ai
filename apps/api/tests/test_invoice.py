"""The invoice: one printable document per payment claim, proforma while
pending and a receipt once approved. What a finance team outside India
needs to raise a wire, and what a buyer anywhere needs to expense it.

Pinned: the two states and the fields each carries, that only the claim's
owner can read it (a neighbour is 404, anonymous is 401), the seller block
from settings with its fallback, and the Airlock line (packs x pack size).
"""

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not configured")

FOUNDER_EMAIL = "invoice-founder@example.com"
BUYER_EMAIL = "invoice-buyer@example.com"
NEIGHBOUR_EMAIL = "invoice-neighbour@example.com"
PASSWORD = "test-password-123"


@pytest_asyncio.fixture
async def context(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL or "")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-used")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-0123456789abcdef0123")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("FOUNDER_EMAIL", FOUNDER_EMAIL)
    monkeypatch.setenv("FOUNDER_UPI_ID", "founder@upi")
    monkeypatch.setenv("FOUNDER_UPI_PAYEE_NAME", "V. Matale")
    monkeypatch.setenv("FOUNDER_BANK_ACCOUNT_NAME", "Beneficiary Name From Bank")
    monkeypatch.setenv("FOUNDER_BANK_ACCOUNT_NUMBER", "000123456789")
    monkeypatch.setenv("FOUNDER_BANK_NAME", "Test Bank")
    monkeypatch.setenv("FOUNDER_BANK_SWIFT_CODE", "TESTINBBXXX")
    monkeypatch.setenv("AIRLOCK_PACK_SCANS", "1000")
    monkeypatch.setenv("AIRLOCK_PACK_PRICE_USD", "15")
    monkeypatch.setenv("SELLER_LEGAL_NAME", "")
    monkeypatch.setenv("SELLER_ADDRESS", "")
    monkeypatch.setenv("SELLER_TAX_ID", "")

    from app.database import Database
    from app.main import create_app
    from app.settings import get_settings

    get_settings.cache_clear()
    database = Database(get_settings())
    await database.open()
    await database.execute("DELETE FROM registration_attempts")
    await database.execute(
        "DELETE FROM users WHERE email = ANY(%s)", ([FOUNDER_EMAIL, BUYER_EMAIL, NEIGHBOUR_EMAIL],)
    )

    application = create_app()
    application.state.database = database
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        yield client, database

    await database.close()
    get_settings.cache_clear()


async def _sign_in_as(client: AsyncClient, email: str) -> str:
    client.cookies.clear()
    credentials = {"email": email, "password": PASSWORD}
    response = await client.post("/v1/auth/register", json=credentials)
    if response.status_code == 409:
        response = await client.post("/v1/auth/login", json=credentials)
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


@pytest.mark.asyncio
async def test_a_subscription_claim_has_a_proforma_that_becomes_a_receipt(context):
    client, database = context
    await _sign_in_as(client, BUYER_EMAIL)
    claim = await client.post("/v1/billing/upi/claim", json={"reference": "UTR-INVOICE-0001", "billing_period": "annual"})
    assert claim.status_code == 201, claim.text
    claim_id = claim.json()["id"]

    invoice = await client.get(f"/v1/billing/claims/{claim_id}/invoice")
    assert invoice.status_code == 200, invoice.text
    body = invoice.json()
    assert body["kind"] == "proforma" and body["status"] == "pending" and body["paid_at"] is None
    assert body["number"].startswith("NN-") and body["number"].endswith(claim_id[:8].upper())
    assert body["buyer_email"] == BUYER_EMAIL
    assert body["line"]["description"] == "PostMortem AI subscription -- annual (12 months)"
    assert body["line"]["quantity"] == 1
    assert body["line"]["amount"] == claim.json()["amount"] == body["line"]["unit_amount"]
    assert body["line"]["currency"] == "INR"
    assert body["method"] == "upi" and body["reference"] == "UTR-INVOICE-0001"
    # No seller identity configured: the bank beneficiary name stands in,
    # and the optional lines are absent rather than blank.
    assert body["seller"] == {"name": "Beneficiary Name From Bank", "address": None, "tax_id": None}
    # Never the payee's account details -- those are emailed on request.
    assert "000123456789" not in invoice.text and "founder@upi" not in invoice.text

    # The founder approves; the same URL is now a receipt with the
    # verification date.
    await _sign_in_as(client, FOUNDER_EMAIL)
    approved = await client.post(f"/v1/founder/payment-claims/{claim_id}/approve")
    assert approved.status_code == 200, approved.text
    await _sign_in_as(client, BUYER_EMAIL)
    receipt = (await client.get(f"/v1/billing/claims/{claim_id}/invoice")).json()
    assert receipt["kind"] == "receipt" and receipt["status"] == "approved"
    assert receipt["paid_at"] is not None and receipt["paid_at"] >= receipt["issued_at"]
    assert receipt["number"] == body["number"], "the number never changes across states"


@pytest.mark.asyncio
async def test_an_airlock_pack_invoice_shows_packs_times_pack_size(context, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SELLER_LEGAL_NAME", "NanoNeuron Test Pvt Ltd")
    monkeypatch.setenv("SELLER_ADDRESS", "1 Test Street, Pune 411001, India")
    monkeypatch.setenv("SELLER_TAX_ID", "27ABCDE1234F1Z5")
    from app.settings import get_settings

    get_settings.cache_clear()
    client, database = context
    await _sign_in_as(client, BUYER_EMAIL)
    claim = await client.post(
        "/v1/airlock/credits/claim", json={"currency": "USD", "reference": "WIRE-INVOICE-0001", "packs": 3}
    )
    assert claim.status_code == 201, claim.text
    body = (await client.get(f"/v1/billing/claims/{claim.json()['id']}/invoice")).json()
    assert body["product"] == "airlock" and body["scan_credits"] == 3000
    assert body["line"] == {
        "description": "Airlock scan credits -- 3,000 credits (3 x 1,000)",
        "quantity": 3,
        "unit_amount": 15,
        "amount": 45,
        "currency": "USD",
    }
    assert body["method"] == "wire"
    assert body["seller"] == {
        "name": "NanoNeuron Test Pvt Ltd",
        "address": "1 Test Street, Pune 411001, India",
        "tax_id": "27ABCDE1234F1Z5",
    }


@pytest.mark.asyncio
async def test_only_the_owner_can_read_an_invoice(context):
    client, database = context
    await _sign_in_as(client, BUYER_EMAIL)
    claim = await client.post("/v1/billing/upi/claim", json={"reference": "UTR-INVOICE-0002"})
    claim_id = claim.json()["id"]

    await _sign_in_as(client, NEIGHBOUR_EMAIL)
    assert (await client.get(f"/v1/billing/claims/{claim_id}/invoice")).status_code == 404
    client.cookies.clear()
    assert (await client.get(f"/v1/billing/claims/{claim_id}/invoice")).status_code == 401
    await _sign_in_as(client, BUYER_EMAIL)
    assert (await client.get("/v1/billing/claims/00000000-0000-0000-0000-000000000000/invoice")).status_code == 404

    # A rejected claim's document is void, not a receipt.
    await _sign_in_as(client, FOUNDER_EMAIL)
    rejected = await client.post(f"/v1/founder/payment-claims/{claim_id}/reject")
    assert rejected.status_code == 200, rejected.text
    await _sign_in_as(client, BUYER_EMAIL)
    assert (await client.get(f"/v1/billing/claims/{claim_id}/invoice")).json()["kind"] == "void"
