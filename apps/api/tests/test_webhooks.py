"""Webhook ingestion: an external tool (no browser session) can create an
incident or append evidence, authenticated by a per-account webhook token
instead of a session cookie. Real end-to-end against Postgres.
"""

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not configured")

CLIENT_EMAIL = "webhook-test-user@example.com"


@pytest_asyncio.fixture
async def context(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL or "")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-used")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("COOKIE_SECURE", "false")

    from app.database import Database
    from app.main import create_app
    from app.settings import get_settings

    get_settings.cache_clear()
    database = Database(get_settings())
    await database.open()
    await database.execute(
        """DELETE FROM incident_postmortems WHERE incident_id IN
           (SELECT id FROM incidents WHERE client_email=%s)""",
        (CLIENT_EMAIL,),
    )
    await database.execute(
        "DELETE FROM incident_evidence WHERE incident_id IN (SELECT id FROM incidents WHERE client_email=%s)",
        (CLIENT_EMAIL,),
    )
    await database.execute("DELETE FROM incidents WHERE client_email=%s", (CLIENT_EMAIL,))
    await database.execute("DELETE FROM users WHERE email=%s", (CLIENT_EMAIL,))

    application = create_app()
    application.state.database = database

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        register = await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"})
        assert register.status_code == 201, register.text
        # Paywall applies to the webhook path exactly like the authenticated
        # routes -- grant a subscription directly, same pattern as
        # test_postmortem_routes.py, since these tests are about the
        # webhook auth/grouping logic, not billing.
        await database.execute("UPDATE users SET subscription_status='active' WHERE email=%s", (CLIENT_EMAIL,))

        token_response = await client.get("/v1/webhooks/token")
        assert token_response.status_code == 200
        token = token_response.json()["token"]

        yield client, database, token

    await database.close()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_a_webhook_event_with_no_incident_id_creates_a_new_incident(context) -> None:
    client, database, token = context
    response = await client.post(
        f"/v1/webhooks/incidents/{token}",
        json={"source": "alert", "summary": "Checkout p99 latency crossed 4s", "title": "Checkout latency spike"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["created_incident"] is True

    incident = await database.fetch_one("SELECT title, client_email, status FROM incidents WHERE id=%s", (body["incident_id"],))
    assert incident is not None
    assert incident["title"] == "Checkout latency spike"
    assert incident["client_email"] == CLIENT_EMAIL
    assert incident["status"] == "open"

    evidence = await database.fetch_one(
        "SELECT summary, source, authorized_by FROM incident_evidence WHERE id=%s", (body["evidence_id"],)
    )
    assert evidence is not None
    assert evidence["summary"] == "Checkout p99 latency crossed 4s"
    assert evidence["authorized_by"] == "webhook"


@pytest.mark.asyncio
async def test_a_webhook_event_with_a_matching_open_incident_id_appends_evidence(context) -> None:
    client, database, token = context
    first = await client.post(
        f"/v1/webhooks/incidents/{token}",
        json={"source": "alert", "summary": "First alert fired", "title": "Ongoing incident"},
    )
    incident_id = first.json()["incident_id"]

    second = await client.post(
        f"/v1/webhooks/incidents/{token}",
        json={"source": "alert", "summary": "Second alert fired, same incident", "incident_id": incident_id},
    )
    assert second.status_code == 201, second.text
    assert second.json()["created_incident"] is False
    assert second.json()["incident_id"] == incident_id

    count = await database.fetch_one("SELECT count(*) AS n FROM incident_evidence WHERE incident_id=%s", (incident_id,))
    assert count is not None
    assert count["n"] == 2


@pytest.mark.asyncio
async def test_a_webhook_event_naming_a_resolved_incident_starts_a_new_one_instead(context) -> None:
    client, database, token = context
    first = await client.post(
        f"/v1/webhooks/incidents/{token}",
        json={"source": "alert", "summary": "Original incident", "title": "Now resolved"},
    )
    incident_id = first.json()["incident_id"]
    await database.execute("UPDATE incidents SET status='resolved' WHERE id=%s", (incident_id,))

    second = await client.post(
        f"/v1/webhooks/incidents/{token}",
        json={"source": "alert", "summary": "New alert after resolution", "incident_id": incident_id},
    )
    assert second.status_code == 201, second.text
    # Not appended to the resolved incident -- a fresh one is started, same
    # as a human would open a new incident rather than reopen a closed one.
    assert second.json()["created_incident"] is True
    assert second.json()["incident_id"] != incident_id


@pytest.mark.asyncio
async def test_an_unknown_webhook_token_is_rejected(context) -> None:
    client, _, _ = context
    response = await client.post(
        "/v1/webhooks/incidents/not-a-real-token",
        json={"source": "alert", "summary": "Should not be accepted"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_a_webhook_event_cannot_touch_another_accounts_open_incident(context) -> None:
    client, database, token = context
    other_email = "webhook-test-other@example.com"
    await database.execute("DELETE FROM incidents WHERE client_email=%s", (other_email,))
    await database.execute(
        """INSERT INTO incidents (id, client_email, title, severity, status, impact, created_at, updated_at)
           VALUES ('inc-other-account', %s, 'Someone else''s incident', 'sev2', 'open', NULL, 0, 0)""",
        (other_email,),
    )

    response = await client.post(
        f"/v1/webhooks/incidents/{token}",
        json={"source": "alert", "summary": "Trying to attach to someone else's incident", "incident_id": "inc-other-account"},
    )
    assert response.status_code == 201, response.text
    # Not appended to the other account's incident -- a new one is created
    # under the caller's own account instead.
    assert response.json()["created_incident"] is True
    assert response.json()["incident_id"] != "inc-other-account"

    await database.execute("DELETE FROM incidents WHERE client_email=%s", (other_email,))


@pytest.mark.asyncio
async def test_an_unpaid_account_is_blocked_from_the_webhook_path(context) -> None:
    client, database, token = context
    await database.execute("UPDATE users SET subscription_status='none' WHERE email=%s", (CLIENT_EMAIL,))

    response = await client.post(
        f"/v1/webhooks/incidents/{token}",
        json={"source": "alert", "summary": "Should be blocked by the paywall"},
    )
    assert response.status_code == 402


@pytest.mark.asyncio
async def test_rotating_the_webhook_token_invalidates_the_old_one(context) -> None:
    client, _, token = context
    rotate = await client.post("/v1/webhooks/token/rotate")
    assert rotate.status_code == 200
    new_token = rotate.json()["token"]
    assert new_token != token

    old_token_response = await client.post(
        f"/v1/webhooks/incidents/{token}",
        json={"source": "alert", "summary": "Using the old, rotated-away token"},
    )
    assert old_token_response.status_code == 404

    new_token_response = await client.post(
        f"/v1/webhooks/incidents/{new_token}",
        json={"source": "alert", "summary": "Using the new token"},
    )
    assert new_token_response.status_code == 201
