"""The free-tier boundary: an unpaid account may create and fully work on
exactly one incident (evidence, extraction, drafting) but never a second
one, and never publish it. Real end-to-end against Postgres; the drafting
model is a deterministic fake, same pattern as test_postmortem_routes.py.
"""

import json
import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not configured")

FREE_EMAIL = "free-incident-test@example.com"

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
    await database.execute(
        """DELETE FROM incident_postmortems WHERE incident_id IN
           (SELECT id FROM incidents WHERE client_email=%s)""",
        (FREE_EMAIL,),
    )
    await database.execute(
        "DELETE FROM incident_evidence WHERE incident_id IN (SELECT id FROM incidents WHERE client_email=%s)",
        (FREE_EMAIL,),
    )
    await database.execute("DELETE FROM incidents WHERE client_email=%s", (FREE_EMAIL,))
    await database.execute("DELETE FROM users WHERE email=%s", (FREE_EMAIL,))

    provider = FakeProvider(GOOD_RESPONSE)
    application = create_app()
    application.state.database = database
    application.dependency_overrides[get_model_provider] = lambda: provider

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        register = await client.post("/v1/auth/register", json={"email": FREE_EMAIL, "password": "correct-horse-battery"})
        assert register.status_code == 201, register.text
        # Never granted a subscription here -- that's the whole point of
        # this file: everything below happens on a genuinely unpaid account.
        yield client, database

    await database.close()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_a_new_unpaid_account_reports_a_free_incident_available(context) -> None:
    client, _ = context
    me = await client.get("/v1/auth/me")
    assert me.json()["has_free_incident_available"] is True


@pytest.mark.asyncio
async def test_an_unpaid_account_can_create_exactly_one_incident(context) -> None:
    client, _ = context
    first = await client.post("/v1/postmortems/incidents", json={"title": "First outage", "severity": "sev2"})
    assert first.status_code == 201, first.text

    me = await client.get("/v1/auth/me")
    assert me.json()["has_free_incident_available"] is False

    second = await client.post("/v1/postmortems/incidents", json={"title": "Second outage", "severity": "sev2"})
    assert second.status_code == 402
    assert second.json()["detail"] == "An active subscription is required"


@pytest.mark.asyncio
async def test_the_free_incident_can_receive_evidence_extraction_and_a_draft(context) -> None:
    # The actual point of the feature: a prospect can see the real core
    # loop -- evidence in, a grounded draft out -- with no payment.
    client, _ = context
    created = await client.post("/v1/postmortems/incidents", json={"title": "Free-tier outage", "severity": "sev1"})
    incident_id = created.json()["id"]

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
async def test_the_free_incident_cannot_be_published(context) -> None:
    client, _ = context
    created = await client.post("/v1/postmortems/incidents", json={"title": "Free-tier outage", "severity": "sev1"})
    incident_id = created.json()["id"]
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
async def test_an_unpaid_account_cannot_touch_a_different_incident_via_its_free_slot(context) -> None:
    # Even though the account has a free incident, it must not be usable as
    # a skeleton key for some other incident_id that just happens to exist
    # (e.g. one owned by a different client, or malformed input) -- the
    # free-tier exception is scoped to exactly the one incident_id recorded
    # in free_incident_id, checked by require_active_subscription_or_free_incident.
    client, _ = context
    created = await client.post("/v1/postmortems/incidents", json={"title": "My free incident", "severity": "sev2"})
    assert created.status_code == 201

    response = await client.post(
        "/v1/postmortems/incidents/does-not-exist-and-is-not-the-free-one/evidence",
        json={"occurred_at": 1_000, "source": "alert", "summary": "x", "detail": None},
    )
    assert response.status_code == 402
