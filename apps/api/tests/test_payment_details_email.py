"""Self-serve "email me the account details" for UPI/wire (POST
/v1/billing/upi/email-details, /wire/email-details) -- the real UPI ID and
bank/SWIFT details stay founder-only via GET /upi/info, /wire/info (see
those routes' own docstrings), but a client still needs them to actually
pay. These routes send them to the client's own registered email instead
of returning them from an API response, so real Resend sends are replaced
with a fake that records what it would have sent -- no real RESEND_API_KEY
needed, no real email sent.

Also covers the client-facing claim confirmation email (the counterpart to
the founder's own claim-notification email) sent when a UPI/wire claim is
submitted.
"""

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not configured")

CLIENT_EMAIL = "payment-details-email-test-client@example.com"
OTHER_CLIENT_EMAIL = "payment-details-email-test-other@example.com"
FOUNDER_EMAIL = "payment-details-email-test-founder@example.com"


@pytest_asyncio.fixture
async def context(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL or "")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-used")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("FOUNDER_EMAIL", FOUNDER_EMAIL)
    monkeypatch.setenv("FOUNDER_UPI_ID", "founder@upi")
    monkeypatch.setenv("SUBSCRIPTION_PRICE_INR", "999")
    monkeypatch.setenv("FOUNDER_BANK_ACCOUNT_NAME", "NANONEURON SERVICES")
    monkeypatch.setenv("FOUNDER_BANK_ACCOUNT_NUMBER", "922020067340454")
    monkeypatch.setenv("FOUNDER_BANK_NAME", "Axis Bank Ltd")
    monkeypatch.setenv("FOUNDER_BANK_SWIFT_CODE", "AXISINBBA02")
    monkeypatch.setenv("SUBSCRIPTION_PRICE_USD", "15")
    monkeypatch.setenv("WIRE_USD_CORRESPONDENT_BANK", "JP Morgan Chase Bank, New York")
    monkeypatch.setenv("WIRE_USD_CORRESPONDENT_SWIFT", "CHASUS33")
    monkeypatch.setenv("WIRE_USD_NOSTRO_ACCOUNT", "11407376")
    monkeypatch.setenv("WIRE_USD_ABA", "FED ABA 0210-0002-1")
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)

    from app.database import Database
    from app.main import create_app
    from app.settings import get_settings

    upi_emails_sent: list[dict] = []
    wire_emails_sent: list[dict] = []
    confirmations_sent: list[dict] = []

    def fake_send_upi(settings, to_email, request_id, upi_id, payee_name, amount_inr):
        upi_emails_sent.append(
            {"to": to_email, "request_id": request_id, "upi_id": upi_id, "payee_name": payee_name, "amount_inr": amount_inr}
        )

    def fake_send_wire(
        settings,
        to_email,
        request_id,
        currency,
        amount,
        account_name,
        account_number,
        bank_name,
        swift_code,
        correspondent_bank,
        correspondent_swift,
        nostro_account,
        routing_reference,
    ):
        wire_emails_sent.append(
            {"to": to_email, "request_id": request_id, "currency": currency, "amount": amount, "account_number": account_number}
        )

    def fake_send_confirmation(settings, claim_id, to_email, method, currency, amount, reference):
        confirmations_sent.append(
            {"claim_id": claim_id, "to": to_email, "method": method, "currency": currency, "amount": amount, "reference": reference}
        )

    monkeypatch.setattr("app.api.v1.billing.send_upi_payment_details_email", fake_send_upi)
    monkeypatch.setattr("app.api.v1.billing.send_wire_payment_details_email", fake_send_wire)
    monkeypatch.setattr("app.api.v1.billing.send_client_claim_confirmation", fake_send_confirmation)

    get_settings.cache_clear()
    database = Database(get_settings())
    await database.open()
    await database.execute("DELETE FROM users WHERE email IN (%s, %s, %s)", (CLIENT_EMAIL, OTHER_CLIENT_EMAIL, FOUNDER_EMAIL))

    application = create_app()
    application.state.database = database

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        yield client, database, application, upi_emails_sent, wire_emails_sent, confirmations_sent

    await database.close()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_upi_email_details_requires_signing_in(context) -> None:
    client, *_ = context
    response = await client.post("/v1/billing/upi/email-details")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_upi_email_details_sends_to_the_callers_own_registered_email(context) -> None:
    client, _, _, upi_emails_sent, _, _ = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})

    response = await client.post("/v1/billing/upi/email-details")
    assert response.status_code == 200, response.text
    assert response.json() == {"sent": True}

    assert len(upi_emails_sent) == 1
    assert upi_emails_sent[0]["to"] == CLIENT_EMAIL
    assert upi_emails_sent[0]["upi_id"] == "founder@upi"
    assert upi_emails_sent[0]["amount_inr"] == 999


@pytest.mark.asyncio
async def test_upi_email_details_returns_502_on_a_real_resend_failure(context, monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression test: a real Resend-side failure (rejected address, rate
    # limit, outage -- anything other than "not configured at all") used to
    # propagate as an unhandled 500 with no actionable message. Caught this
    # live in production: a scratch test account's own registered email
    # (an @example.com address) was rejected by Resend's own anti-abuse
    # rules with resend.exceptions.ValidationError, which isn't
    # EmailNotConfiguredError and wasn't caught by anything.
    import resend.exceptions

    client, *_ = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})

    def raise_resend_error(*args, **kwargs):
        raise resend.exceptions.ValidationError("Invalid `to` field.", "validation_error", 422)

    monkeypatch.setattr("app.api.v1.billing.send_upi_payment_details_email", raise_resend_error)

    response = await client.post("/v1/billing/upi/email-details")
    assert response.status_code == 502
    assert "try again" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_wire_email_details_returns_502_on_a_real_resend_failure(context, monkeypatch: pytest.MonkeyPatch) -> None:
    import resend.exceptions

    client, *_ = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})

    def raise_resend_error(*args, **kwargs):
        raise resend.exceptions.ValidationError("Invalid `to` field.", "validation_error", 422)

    monkeypatch.setattr("app.api.v1.billing.send_wire_payment_details_email", raise_resend_error)

    response = await client.post("/v1/billing/wire/email-details", json={"currency": "USD"})
    assert response.status_code == 502
    assert "try again" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_upi_email_details_returns_503_when_upi_is_not_configured(context, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _, _, _, _, _ = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})

    monkeypatch.delenv("FOUNDER_UPI_ID", raising=False)
    from app.settings import get_settings

    get_settings.cache_clear()
    response = await client.post("/v1/billing/upi/email-details")
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_upi_email_details_is_rate_limited_per_account(context) -> None:
    # MAX_PAYMENT_DETAILS_EMAILS_PER_WINDOW is 5 -- a genuine client
    # re-checking spam or wanting a second copy is never blocked this
    # quickly, but this can't be used to spam an inbox unbounded.
    client, _, _, upi_emails_sent, _, _ = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})

    for _ in range(5):
        response = await client.post("/v1/billing/upi/email-details")
        assert response.status_code == 200, response.text

    sixth = await client.post("/v1/billing/upi/email-details")
    assert sixth.status_code == 429
    assert len(upi_emails_sent) == 5


@pytest.mark.asyncio
async def test_upi_and_wire_email_details_rate_limits_are_independent(context) -> None:
    # A client who exhausts the UPI limit can still request wire details
    # (and vice versa) -- separate counter actions per method, deliberately.
    client, _, _, _, _, _ = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})

    for _ in range(5):
        assert (await client.post("/v1/billing/upi/email-details")).status_code == 200
    assert (await client.post("/v1/billing/upi/email-details")).status_code == 429

    still_allowed = await client.post("/v1/billing/wire/email-details", json={"currency": "USD"})
    assert still_allowed.status_code == 200, still_allowed.text


@pytest.mark.asyncio
async def test_two_different_accounts_are_rate_limited_independently(context) -> None:
    client, _, application, upi_emails_sent, _, _ = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})
    for _ in range(5):
        assert (await client.post("/v1/billing/upi/email-details")).status_code == 200
    assert (await client.post("/v1/billing/upi/email-details")).status_code == 429

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as other_client:
        await other_client.post("/v1/auth/register", json={"email": OTHER_CLIENT_EMAIL, "password": "correct-horse-battery"})
        response = await other_client.post("/v1/billing/upi/email-details")
        assert response.status_code == 200, response.text

    assert len(upi_emails_sent) == 6
    assert upi_emails_sent[-1]["to"] == OTHER_CLIENT_EMAIL


@pytest.mark.asyncio
async def test_wire_email_details_requires_signing_in(context) -> None:
    client, *_ = context
    response = await client.post("/v1/billing/wire/email-details", json={"currency": "USD"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_wire_email_details_sends_the_correct_currencys_details(context) -> None:
    client, _, _, _, wire_emails_sent, _ = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})

    response = await client.post("/v1/billing/wire/email-details", json={"currency": "USD"})
    assert response.status_code == 200, response.text
    assert response.json() == {"sent": True}

    assert len(wire_emails_sent) == 1
    assert wire_emails_sent[0]["to"] == CLIENT_EMAIL
    assert wire_emails_sent[0]["currency"] == "USD"
    assert wire_emails_sent[0]["amount"] == 15
    assert wire_emails_sent[0]["account_number"] == "922020067340454"


@pytest.mark.asyncio
async def test_wire_email_details_rejects_an_unsupported_currency(context) -> None:
    client, *_ = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})

    response = await client.post("/v1/billing/wire/email-details", json={"currency": "JPY"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_wire_email_details_returns_503_when_wire_is_not_configured(context, monkeypatch: pytest.MonkeyPatch) -> None:
    client, *_ = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})

    monkeypatch.delenv("FOUNDER_BANK_ACCOUNT_NUMBER", raising=False)
    from app.settings import get_settings

    get_settings.cache_clear()
    response = await client.post("/v1/billing/wire/email-details", json={"currency": "USD"})
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_submitting_a_upi_claim_sends_the_client_a_confirmation(context) -> None:
    client, _, _, _, _, confirmations_sent = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})

    claim = await client.post("/v1/billing/upi/claim", json={"reference": "UTR-CONFIRM-ME"})
    assert claim.status_code == 201, claim.text

    assert len(confirmations_sent) == 1
    assert confirmations_sent[0]["to"] == CLIENT_EMAIL
    assert confirmations_sent[0]["method"] == "upi"
    assert confirmations_sent[0]["reference"] == "UTR-CONFIRM-ME"
    assert confirmations_sent[0]["claim_id"] == claim.json()["id"]


@pytest.mark.asyncio
async def test_submitting_a_wire_claim_sends_the_client_a_confirmation(context) -> None:
    client, _, _, _, _, confirmations_sent = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})

    claim = await client.post("/v1/billing/wire/claim", json={"currency": "USD", "reference": "MT103-CONFIRM-ME"})
    assert claim.status_code == 201, claim.text

    assert len(confirmations_sent) == 1
    assert confirmations_sent[0]["to"] == CLIENT_EMAIL
    assert confirmations_sent[0]["method"] == "wire"
    assert confirmations_sent[0]["currency"] == "USD"
    assert confirmations_sent[0]["reference"] == "MT103-CONFIRM-ME"


@pytest.mark.asyncio
async def test_a_claim_is_still_created_even_if_the_confirmation_email_fails(context, monkeypatch: pytest.MonkeyPatch) -> None:
    # Best-effort, non-blocking by design -- same reasoning as the founder
    # notification email right next to it in _insert_claim. A Resend outage
    # must never turn a real, valid claim submission into a failed one.
    client, *_ = context
    await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})

    def raise_error(*args, **kwargs):
        raise RuntimeError("Resend is down")

    monkeypatch.setattr("app.api.v1.billing.send_client_claim_confirmation", raise_error)

    claim = await client.post("/v1/billing/upi/claim", json={"reference": "UTR-CONFIRM-EMAIL-DOWN"})
    assert claim.status_code == 201, claim.text
    assert claim.json()["status"] == "pending"
