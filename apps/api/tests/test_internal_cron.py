"""Free-incident nudge cron: end-to-end against real Postgres. The actual
Resend API call is replaced with a fake that records what it would have
sent (same pattern as test_password_reset.py), so these tests need no
real RESEND_API_KEY and send no real email.
"""

import json
import os
import secrets
import time

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not configured")

CRON_SECRET = "test-cron-secret"

# A minimal, valid grounded response -- these tests only care that a draft
# exists at all (the eligibility condition), not its content, unlike
# test_postmortem_routes.py's own much more detailed fake.
DRAFT_RESPONSE = {
    "summary": {"text": "Something happened.", "citations": [1]},
    "root_cause": {"text": "Unclear.", "citations": [1]},
    "detection": {"text": "A human noticed.", "citations": [1]},
    "resolution": {"text": "It was noted.", "citations": [1]},
    "contributing_factors": [],
    "actions": [],
}


class FakeProvider:
    name = "fake"
    model_name = "fake-model-v1"

    async def complete(self, request):
        from app.ai.provider import ModelResponse

        return ModelResponse(text=json.dumps(DRAFT_RESPONSE), output_tokens=10)


@pytest_asyncio.fixture
async def context(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL or "")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-used")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("RESEND_API_KEY", "test-key-not-used")
    monkeypatch.setenv("RESEND_EMAIL_DOMAIN", "test.example.com")
    monkeypatch.setenv("CRON_SECRET", CRON_SECRET)

    from app.api.v1.postmortems import get_model_provider
    from app.database import Database
    from app.main import create_app
    from app.settings import get_settings

    sent: list[dict] = []

    def fake_send(settings, to_email, incident_title, user_id):
        sent.append({"to": to_email, "incident_title": incident_title, "user_id": user_id})

    monkeypatch.setattr("app.api.v1.internal.send_free_incident_nudge_email", fake_send)

    # RAG's embedding call is best-effort and separate from drafting -- fake
    # it deterministically rather than make a real network call per test.
    async def fake_embed_text(_client, _text):
        return [0.1] * 768

    monkeypatch.setattr("app.api.v1.postmortems.embed_text", fake_embed_text)
    monkeypatch.setattr("app.ai.rag.embed_text", fake_embed_text)

    get_settings.cache_clear()
    database = Database(get_settings())
    await database.open()
    # free_incident_id's FK is ON DELETE SET NULL, not CASCADE -- deleting
    # the user row wouldn't clean up the incidents rows these tests insert
    # directly, and the fixed incident ids below would collide with
    # themselves on the next run.
    await database.execute("DELETE FROM incidents WHERE client_email LIKE %s", ("cron-test-%",))
    await database.execute("DELETE FROM users WHERE email LIKE %s", ("cron-test-%",))

    application = create_app()
    application.state.database = database
    application.dependency_overrides[get_model_provider] = lambda: FakeProvider()

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        yield client, database, sent

    await database.close()
    get_settings.cache_clear()


async def _register_with_free_incident(client: AsyncClient, database, email: str, incident_age_ms: int) -> str:
    """Registers, gives the account a free incident, backdates it to look
    `incident_age_ms` old, and drafts a real postmortem for it so the
    account has actually gotten value -- returns the incident id.

    The free-incident trial is retired for new grants (see
    test_free_incident.py) -- POST /incidents can no longer produce this
    state, so the incident and free_incident_id are inserted directly, the
    same shape create_incident used to write before that change. This cron
    only ever fires for accounts with a free_incident_id already on record
    (see api/v1/internal.py), so that's the real state it needs to test
    against regardless of how it's produced."""
    register = await client.post("/v1/auth/register", json={"email": email, "password": "correct-horse-battery"})
    assert register.status_code == 201, register.text
    user_id = register.json()["id"]

    incident_id = f"inc-cron-test-{secrets.token_hex(6)}"
    created_at = int(time.time() * 1000) - incident_age_ms
    await database.execute(
        """INSERT INTO incidents (id, client_email, title, severity, status, impact, created_at, updated_at)
           VALUES (%s, %s, %s, 'sev3', 'open', NULL, %s, %s)""",
        (incident_id, email, f"Free incident for {email}", created_at, created_at),
    )
    await database.execute("UPDATE users SET free_incident_id=%s WHERE id=%s", (incident_id, user_id))
    await client.post(
        "/v1/postmortems/incidents/{}/evidence".format(incident_id),
        json={"occurred_at": int(time.time() * 1000), "source": "human_note", "summary": "Something happened."},
    )
    draft = await client.post(f"/v1/postmortems/incidents/{incident_id}/draft")
    assert draft.status_code == 201, draft.text
    await client.post("/v1/auth/logout")
    return incident_id


@pytest.mark.asyncio
async def test_the_cron_endpoint_requires_the_real_secret(context) -> None:
    client, _, _ = context
    no_auth = await client.post("/v1/internal/cron/free-incident-nudge")
    assert no_auth.status_code == 401

    wrong_secret = await client.post(
        "/v1/internal/cron/free-incident-nudge", headers={"Authorization": "Bearer wrong-secret"}
    )
    assert wrong_secret.status_code == 401


@pytest.mark.asyncio
async def test_nudges_an_eligible_account_and_never_double_sends(context) -> None:
    client, database, sent = context
    day_ms = 24 * 60 * 60 * 1000
    await _register_with_free_incident(client, database, "cron-test-eligible@example.com", incident_age_ms=day_ms + 1000)

    headers = {"Authorization": f"Bearer {CRON_SECRET}"}
    first_run = await client.post("/v1/internal/cron/free-incident-nudge", headers=headers)
    assert first_run.status_code == 200, first_run.text
    body = first_run.json()
    assert body["emails_sent"] == 1
    assert body["emails_failed"] == 0
    assert len(sent) == 1
    assert sent[0]["to"] == "cron-test-eligible@example.com"

    # A second run must not re-send -- free_incident_reminder_sent_at is
    # now set, which is the entire point of tracking it.
    second_run = await client.post("/v1/internal/cron/free-incident-nudge", headers=headers)
    assert second_run.status_code == 200, second_run.text
    assert second_run.json()["emails_sent"] == 0
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_does_not_nudge_a_too_recent_incident_or_one_with_no_draft(context) -> None:
    client, database, sent = context

    # Too recent: created 1 hour ago, well under the 24h floor.
    await _register_with_free_incident(client, database, "cron-test-too-recent@example.com", incident_age_ms=60 * 60 * 1000)

    # Old enough, but never drafted -- no real value delivered yet.
    register = await client.post(
        "/v1/auth/register", json={"email": "cron-test-no-draft@example.com", "password": "correct-horse-battery"}
    )
    assert register.status_code == 201
    user_id = register.json()["id"]
    incident_id = "inc-cron-test-no-draft"
    created_at = int(time.time() * 1000) - 2 * 24 * 60 * 60 * 1000
    await database.execute(
        """INSERT INTO incidents (id, client_email, title, severity, status, impact, created_at, updated_at)
           VALUES (%s, %s, 'Never drafted', 'sev3', 'open', NULL, %s, %s)""",
        (incident_id, "cron-test-no-draft@example.com", created_at, created_at),
    )
    await database.execute("UPDATE users SET free_incident_id=%s WHERE id=%s", (incident_id, user_id))
    await client.post("/v1/auth/logout")

    headers = {"Authorization": f"Bearer {CRON_SECRET}"}
    run = await client.post("/v1/internal/cron/free-incident-nudge", headers=headers)
    assert run.status_code == 200, run.text
    assert run.json()["emails_sent"] == 0
    assert sent == []


@pytest.mark.asyncio
async def test_does_not_nudge_an_account_that_already_paid(context) -> None:
    client, database, sent = context
    day_ms = 24 * 60 * 60 * 1000
    await _register_with_free_incident(client, database, "cron-test-paid@example.com", incident_age_ms=day_ms + 1000)
    await database.execute(
        "UPDATE users SET subscription_status='active', current_period_end=%s WHERE email=%s",
        (9999999999, "cron-test-paid@example.com"),
    )

    headers = {"Authorization": f"Bearer {CRON_SECRET}"}
    run = await client.post("/v1/internal/cron/free-incident-nudge", headers=headers)
    assert run.status_code == 200, run.text
    assert run.json()["emails_sent"] == 0
    assert sent == []
