"""A client editing or withdrawing their own pending UPI/wire claim --
PATCH/DELETE on /v1/billing/claims/{id}, real end-to-end against Postgres.
"""

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not configured")

CLIENT_EMAIL = "claim-crud-client@example.com"
OTHER_CLIENT_EMAIL = "claim-crud-other@example.com"


@pytest_asyncio.fixture
async def context(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL or "")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-used")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("FOUNDER_UPI_ID", "founder@upi")
    monkeypatch.setenv("SUBSCRIPTION_PRICE_INR", "999")
    monkeypatch.setenv("FOUNDER_BANK_ACCOUNT_NUMBER", "000111222333")
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("STRIPE_PRICE_ID", raising=False)

    from app.database import Database
    from app.main import create_app
    from app.settings import get_settings

    get_settings.cache_clear()
    database = Database(get_settings())
    await database.open()
    await database.execute("DELETE FROM users WHERE email IN (%s, %s)", (CLIENT_EMAIL, OTHER_CLIENT_EMAIL))

    application = create_app()
    application.state.database = database

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        yield client, database

    await database.close()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_a_pending_claims_reference_can_be_edited(context) -> None:
    client, _ = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})
    claim = await client.post("/v1/billing/upi/claim", json={"reference": "ORIGINALREF123"})
    claim_id = claim.json()["id"]

    response = await client.patch(f"/v1/billing/claims/{claim_id}", json={"reference": "EDITEDREF456"})
    assert response.status_code == 200, response.text
    assert response.json()["reference"] == "EDITEDREF456"

    claims = await client.get("/v1/billing/upi/claims")
    assert claims.json()[0]["reference"] == "EDITEDREF456"


@pytest.mark.asyncio
async def test_a_pending_claim_can_be_withdrawn(context) -> None:
    client, database = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})
    claim = await client.post("/v1/billing/upi/claim", json={"reference": "WITHDRAWME789"})
    claim_id = claim.json()["id"]

    response = await client.delete(f"/v1/billing/claims/{claim_id}")
    assert response.status_code == 204

    row = await database.fetch_one("SELECT status FROM payment_claims WHERE id=%s", (claim_id,))
    assert row["status"] == "rejected"

    # The row is kept (not hard-deleted) for the audit trail.
    events = await database.fetch_all(
        "SELECT event_type FROM payment_claim_events WHERE claim_id=%s ORDER BY created_at", (claim_id,)
    )
    assert [e["event_type"] for e in events] == ["created", "rejected"]


@pytest.mark.asyncio
async def test_a_non_pending_claim_cannot_be_edited_or_withdrawn(context) -> None:
    client, database = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})
    claim = await client.post("/v1/billing/upi/claim", json={"reference": "ALREADYREJECTED"})
    claim_id = claim.json()["id"]
    await database.execute("UPDATE payment_claims SET status='rejected' WHERE id=%s", (claim_id,))

    edit = await client.patch(f"/v1/billing/claims/{claim_id}", json={"reference": "TOOLATE"})
    assert edit.status_code == 409

    cancel = await client.delete(f"/v1/billing/claims/{claim_id}")
    assert cancel.status_code == 409


@pytest.mark.asyncio
async def test_a_different_client_cannot_edit_or_withdraw_someone_elses_claim(context) -> None:
    client, _ = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})
    claim = await client.post("/v1/billing/upi/claim", json={"reference": "NOTYOURSATALL"})
    claim_id = claim.json()["id"]
    client.cookies.clear()

    await client.post("/v1/auth/register", json={"email": OTHER_CLIENT_EMAIL, "password": "correct-horse-battery"})
    edit = await client.patch(f"/v1/billing/claims/{claim_id}", json={"reference": "HIJACKED"})
    assert edit.status_code == 404
    cancel = await client.delete(f"/v1/billing/claims/{claim_id}")
    assert cancel.status_code == 404


@pytest.mark.asyncio
async def test_editing_into_a_reference_already_used_by_another_claim_is_a_conflict(context) -> None:
    client, _ = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})
    await client.post("/v1/billing/upi/claim", json={"reference": "TAKENALREADY01"})
    second = await client.post("/v1/billing/wire/claim", json={"currency": "USD", "reference": "MYOWNREF02"})
    second_id = second.json()["id"]

    response = await client.patch(f"/v1/billing/claims/{second_id}", json={"reference": "TAKENALREADY01"})
    assert response.status_code == 409
