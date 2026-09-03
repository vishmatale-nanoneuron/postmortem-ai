"""The free-incident trial is retired for new grants (see auth.py's
User.has_free_incident_available) -- a brand-new unpaid account can no
longer create even one incident without a subscription.

What's deliberately preserved: an account that already has free_incident_id
set from *before* this change can still fully work on that one incident --
evidence, extraction, drafting -- exactly as before. Never publish it,
never touch a different incident_id, never get a second one. There's no
way to mint a new free_incident_id through the API anymore, so the
"legacy" fixture below simulates one the only way left to produce it:
writing it directly, the same shape create_incident used to write before
this change.

Real end-to-end against Postgres; the drafting model is a deterministic
fake, same pattern as test_postmortem_routes.py.
"""

import json
import os
import time

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not configured")

FREE_EMAIL = "free-incident-test@example.com"
LEGACY_EMAIL = "free-incident-legacy-test@example.com"

GOOD_RESPONSE = {
    "summary": {"text": "Checkout latency rose after release 1.2.", "citations": [1]},
    "root_cause": {"text": "The new payment client slowed checkout.", "citations": [1]},
    "detection": {"text": "Alert CHK-LAT fired on p99 latency.", "citations": [1]},
    "resolution": {"text": "Rolling back restored latency.", "citations": [1]},
    "contributing_factors": [],
    "actions": [],
}


class FakeProvider:
    name = "fake"
    model_name = "fake-model-v1"

    def __init__(self, response: object) -> None:
        self.response = response
        self.output_tokens: int | None = 42

    async def complete(self, request):
        from app.ai.provider import ModelResponse

        text = self.response if isinstance(self.response, str) else json.dumps(self.response)
        return ModelResponse(text=text, output_tokens=self.output_tokens)


async def _reset(database, email: str) -> None:
    await database.execute(
        """DELETE FROM incident_postmortems WHERE incident_id IN
           (SELECT id FROM incidents WHERE client_email=%s)""",
        (email,),
    )
    await database.execute(
        "DELETE FROM incident_evidence WHERE incident_id IN (SELECT id FROM incidents WHERE client_email=%s)",
        (email,),
    )
    await database.execute("DELETE FROM incidents WHERE client_email=%s", (email,))
    await database.execute("DELETE FROM users WHERE email=%s", (email,))


@pytest_asyncio.fixture
async def context(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL or "")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-used")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("COOKIE_SECURE", "false")

    from app.api.v1.postmortems import get_model_provider
    from app.database import Database
    from app.main import create_app
    from app.settings import get_settings

    async def fake_embed_text(_client, _text):
        return [0.1] * 768

    monkeypatch.setattr("app.api.v1.postmortems.embed_text", fake_embed_text)
    monkeypatch.setattr("app.ai.rag.embed_text", fake_embed_text)

    get_settings.cache_clear()
    database = Database(get_settings())
    await database.open()
    await _reset(database, FREE_EMAIL)

    provider = FakeProvider(GOOD_RESPONSE)
    application = create_app()
    application.state.database = database
    application.dependency_overrides[get_model_provider] = lambda: provider

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        register = await client.post("/v1/auth/register", json={"email": FREE_EMAIL, "password": "correct-horse-battery"})
        assert register.status_code == 201, register.text
        yield client, database

    await database.close()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_a_new_unpaid_account_has_no_free_incident_available(context) -> None:
    client, _ = context
    me = await client.get("/v1/auth/me")
    body = me.json()
    assert body["has_free_incident_available"] is False
    assert body["has_used_free_incident"] is False


@pytest.mark.asyncio
async def test_a_new_unpaid_account_cannot_create_any_incident(context) -> None:
    client, _ = context
    response = await client.post("/v1/postmortems/incidents", json={"title": "First outage", "severity": "sev2"})
    assert response.status_code == 402
    assert response.json()["detail"] == "An active subscription is required"


@pytest_asyncio.fixture
async def legacy_context(monkeypatch: pytest.MonkeyPatch):
    """An account with a free incident from before the trial was retired --
    simulated by inserting the incident and free_incident_id directly,
    since POST /incidents can no longer produce this state itself."""
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL or "")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-used")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("COOKIE_SECURE", "false")

    from app.api.v1.postmortems import get_model_provider
    from app.database import Database
    from app.main import create_app
    from app.settings import get_settings

    async def fake_embed_text(_client, _text):
        return [0.1] * 768

    monkeypatch.setattr("app.api.v1.postmortems.embed_text", fake_embed_text)
    monkeypatch.setattr("app.ai.rag.embed_text", fake_embed_text)

    get_settings.cache_clear()
    database = Database(get_settings())
    await database.open()
    await _reset(database, LEGACY_EMAIL)

    provider = FakeProvider(GOOD_RESPONSE)
    application = create_app()
    application.state.database = database
    application.dependency_overrides[get_model_provider] = lambda: provider

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        register = await client.post("/v1/auth/register", json={"email": LEGACY_EMAIL, "password": "correct-horse-battery"})
        user_id = register.json()["id"]

        incident_id = "inc-legacy-free-test"
        now = int(time.time() * 1000)
        await database.execute(
            """INSERT INTO incidents (id, client_email, title, severity, status, impact, created_at, updated_at)
               VALUES (%s, %s, %s, %s, 'open', NULL, %s, %s)""",
            (incident_id, LEGACY_EMAIL, "Legacy free-tier outage", "sev1", now, now),
        )
        await database.execute("UPDATE users SET free_incident_id=%s WHERE id=%s", (incident_id, user_id))

        yield client, database, incident_id

    await database.close()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_a_legacy_free_incident_reports_has_used_free_incident(legacy_context) -> None:
    client, _, _ = legacy_context
    me = await client.get("/v1/auth/me")
    body = me.json()
    assert body["has_free_incident_available"] is False
    assert body["has_used_free_incident"] is True


@pytest.mark.asyncio
async def test_a_legacy_free_incident_can_still_receive_evidence_extraction_and_a_draft(legacy_context) -> None:
    # The trial is closed to new grants, but an account that already has
    # one from before still gets the real core loop on it -- evidence in,
    # a grounded draft out -- exactly as it always could.
    client, _, incident_id = legacy_context

    evidence = await client.post(
        f"/v1/postmortems/incidents/{incident_id}/evidence",
        json={"occurred_at": 1_000, "source": "alert", "summary": "Checkout p99 crossed 4s", "detail": None},
    )
    assert evidence.status_code == 201, evidence.text

    extracted = await client.post(
        f"/v1/postmortems/incidents/{incident_id}/evidence/extract",
        json={"text": "03:14 alert fired for checkout latency. 03:22 rolled back release 1.2, latency recovered."},
    )
    assert extracted.status_code == 200, extracted.text

    status_change = await client.patch(f"/v1/postmortems/incidents/{incident_id}/status", json={"status": "resolved"})
    assert status_change.status_code == 200, status_change.text

    draft = await client.post(f"/v1/postmortems/incidents/{incident_id}/draft")
    assert draft.status_code == 201, draft.text


@pytest.mark.asyncio
async def test_a_legacy_free_incident_still_cannot_be_published(legacy_context) -> None:
    client, _, incident_id = legacy_context
    await client.post(
        f"/v1/postmortems/incidents/{incident_id}/evidence",
        json={"occurred_at": 1_000, "source": "alert", "summary": "Checkout p99 crossed 4s", "detail": None},
    )
    draft = await client.post(f"/v1/postmortems/incidents/{incident_id}/draft")
    assert draft.status_code == 201, draft.text

    publish = await client.post(f"/v1/postmortems/incidents/{incident_id}/publish")
    assert publish.status_code == 402
    assert publish.json()["detail"] == "An active subscription is required"


@pytest.mark.asyncio
async def test_a_legacy_free_account_still_cannot_create_a_second_incident(legacy_context) -> None:
    client, _, _ = legacy_context
    response = await client.post("/v1/postmortems/incidents", json={"title": "Second outage", "severity": "sev2"})
    assert response.status_code == 402
    assert response.json()["detail"] == "An active subscription is required"


@pytest.mark.asyncio
async def test_a_legacy_free_incident_cannot_be_used_as_a_skeleton_key_for_another_incident_id(legacy_context) -> None:
    # Even with a free incident on record, it must not be usable against
    # any other incident_id (one owned by someone else, or just made up) --
    # the exception is scoped to exactly the one id in free_incident_id.
    client, _, _ = legacy_context
    response = await client.post(
        "/v1/postmortems/incidents/does-not-exist-and-is-not-the-free-one/evidence",
        json={"occurred_at": 1_000, "source": "alert", "summary": "x", "detail": None},
    )
    assert response.status_code == 402
