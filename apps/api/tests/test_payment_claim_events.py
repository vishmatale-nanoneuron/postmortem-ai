"""The append-only audit ledger (migration 0016, services/billing.py's
record_claim_event) -- proves the full real lifecycle of a claim is
reconstructable afterward, not just its current overwritten state.
"""

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not configured")

CLIENT_EMAIL = "claim-events-test-client@example.com"
FOUNDER_EMAIL = "claim-events-test-founder@example.com"
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
async def test_the_full_lifecycle_is_recorded_in_order_and_never_overwritten(context) -> None:
    client, _ = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})
    claim = await client.post("/v1/billing/upi/claim", json={"reference": "LEDGERCHECK123456"})
    claim_id = claim.json()["id"]
    client.cookies.clear()

    await client.post(
        "/v1/billing/bank-alert",
        json={"text": "Rs.999.00 credited to your account. UPI Ref No LEDGERCHECK123456."},
        headers={"x-bank-alert-secret": WEBHOOK_SECRET},
    )

    await client.post("/v1/auth/register", json={"email": FOUNDER_EMAIL, "password": "correct-horse-battery"})
    approve = await client.post(f"/v1/founder/payment-claims/{claim_id}/approve")
    assert approve.status_code == 200, approve.text

    events = await client.get(f"/v1/founder/payment-claims/{claim_id}/events")
    assert events.status_code == 200, events.text
    body = events.json()

    event_types = [e["event_type"] for e in body]
    assert event_types == ["created", "bank_verified", "approved"]

    assert body[0]["actor"] == CLIENT_EMAIL
    assert body[1]["actor"] == "system:bank-alert"
    assert body[2]["actor"] == FOUNDER_EMAIL

    # Timestamps are strictly non-decreasing in the order events actually
    # happened -- the whole point of an append-only ledger.
    timestamps = [e["created_at"] for e in body]
    assert timestamps == sorted(timestamps)


@pytest.mark.asyncio
async def test_a_rejected_claim_is_also_recorded(context) -> None:
    client, _ = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})
    claim = await client.post("/v1/billing/upi/claim", json={"reference": "REJECTLEDGER123"})
    claim_id = claim.json()["id"]
    client.cookies.clear()

    await client.post("/v1/auth/register", json={"email": FOUNDER_EMAIL, "password": "correct-horse-battery"})
    reject = await client.post(f"/v1/founder/payment-claims/{claim_id}/reject")
    assert reject.status_code == 200, reject.text

    events = await client.get(f"/v1/founder/payment-claims/{claim_id}/events")
    event_types = [e["event_type"] for e in events.json()]
    assert event_types == ["created", "rejected"]


@pytest.mark.asyncio
async def test_annotate_appends_a_note_without_touching_status(context) -> None:
    client, database = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})
    claim = await client.post("/v1/billing/upi/claim", json={"reference": "ANNOTATELEDGER1"})
    claim_id = claim.json()["id"]
    client.cookies.clear()

    await client.post("/v1/auth/register", json={"email": FOUNDER_EMAIL, "password": "correct-horse-battery"})
    reject = await client.post(f"/v1/founder/payment-claims/{claim_id}/reject")
    assert reject.status_code == 200, reject.text

    note = await client.post(
        f"/v1/founder/payment-claims/{claim_id}/annotate",
        json={"detail": "Correction: reverted, no real payment was ever received."},
    )
    assert note.status_code == 200, note.text
    assert note.json()["actor"] == FOUNDER_EMAIL

    events = await client.get(f"/v1/founder/payment-claims/{claim_id}/events")
    event_types = [e["event_type"] for e in events.json()]
    assert event_types == ["created", "rejected", "annotated"]

    row = await database.fetch_one("SELECT status FROM payment_claims WHERE id=%s", (claim_id,))
    assert row["status"] == "rejected"  # annotate must never change status


@pytest.mark.asyncio
async def test_annotate_requires_founder_auth(context) -> None:
    client, _ = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})
    claim = await client.post("/v1/billing/upi/claim", json={"reference": "ANNOTATEAUTHCHK"})
    claim_id = claim.json()["id"]

    response = await client.post(f"/v1/founder/payment-claims/{claim_id}/annotate", json={"detail": "nope"})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_events_endpoint_requires_founder_auth(context) -> None:
    client, _ = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})
    claim = await client.post("/v1/billing/upi/claim", json={"reference": "AUTHCHECKLEDGER"})
    claim_id = claim.json()["id"]

    # The claim's own owner is not the founder -- must not see the ledger.
    response = await client.get(f"/v1/founder/payment-claims/{claim_id}/events")
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Client notification on the founder's decision. Until this existed, a client
# submitted a claim, got "you'll be able to see the outcome in your dashboard"
# (send_client_claim_confirmation), and was then never told the outcome had
# arrived -- polling the dashboard was the only way to learn your access had
# turned on, on a rail where a human approves by hand hours later.
# ---------------------------------------------------------------------------


async def _submit_claim(client, reference: str) -> str:
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})
    claim = await client.post("/v1/billing/upi/claim", json={"reference": reference})
    assert claim.status_code == 201, claim.text
    client.cookies.clear()
    await client.post("/v1/auth/register", json={"email": FOUNDER_EMAIL, "password": "correct-horse-battery"})
    return claim.json()["id"]


@pytest.mark.asyncio
async def test_approving_a_claim_emails_the_client(context, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = context
    sent: list[tuple] = []
    monkeypatch.setattr(
        "app.api.v1.founder.send_client_claim_approved_email",
        lambda settings, claim_id, to_email, method: sent.append((claim_id, to_email, method)),
    )

    claim_id = await _submit_claim(client, "APPROVEMAIL123456")
    approve = await client.post(f"/v1/founder/payment-claims/{claim_id}/approve")
    assert approve.status_code == 200, approve.text

    assert len(sent) == 1, sent
    assert sent[0][0] == claim_id
    assert sent[0][1] == CLIENT_EMAIL  # always the claim owner, never the founder
    assert sent[0][2] == "upi"


@pytest.mark.asyncio
async def test_rejecting_a_claim_emails_the_client(context, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = context
    sent: list[tuple] = []
    monkeypatch.setattr(
        "app.api.v1.founder.send_client_claim_rejected_email",
        lambda settings, claim_id, to_email, method: sent.append((claim_id, to_email, method)),
    )

    claim_id = await _submit_claim(client, "REJECTMAIL1234567")
    reject = await client.post(f"/v1/founder/payment-claims/{claim_id}/reject")
    assert reject.status_code == 200, reject.text

    assert len(sent) == 1, sent
    assert sent[0][1] == CLIENT_EMAIL


@pytest.mark.asyncio
async def test_an_email_failure_never_breaks_the_approval(context, monkeypatch: pytest.MonkeyPatch) -> None:
    """The property that actually matters: the access grant is already
    committed before the email is attempted. A Resend outage must never turn
    a successful approval into a 500 -- which would leave the founder unsure
    whether the customer got access, on the one action that takes money."""
    client, database = context

    def blow_up(*_args, **_kwargs):
        raise RuntimeError("resend is down")

    monkeypatch.setattr("app.api.v1.founder.send_client_claim_approved_email", blow_up)

    claim_id = await _submit_claim(client, "EMAILFAILS1234567")
    approve = await client.post(f"/v1/founder/payment-claims/{claim_id}/approve")
    assert approve.status_code == 200, approve.text
    assert approve.json()["status"] == "approved"

    # And the grant is real, not just a 200: the account is actually active.
    row = await database.fetch_one("SELECT subscription_status FROM users WHERE email=%s", (CLIENT_EMAIL,))
    assert row is not None and row["subscription_status"] == "active"
