"""End-to-end postmortem tests against a real PostgreSQL instance.

The drafting model is a deterministic fake, so the whole flow -- evidence,
grounding, storage, publication -- is verifiable with no real API key.
Skipped unless TEST_DATABASE_URL is set.
"""

import json
import os
import time

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not configured")

INCIDENT = "pm-incident-1"
CLIENT_EMAIL = "postmortem-test-user@example.com"
TEST_PASSWORD = "correct-horse-battery-staple"

GOOD_RESPONSE = {
    "summary": {"text": "Checkout latency rose after release 1.2.", "citations": [1, 2]},
    "root_cause": {"text": "The new payment client slowed checkout.", "citations": [2]},
    "detection": {"text": "Alert CHK-LAT fired on p99 latency.", "citations": [1]},
    "resolution": {"text": "Rolling back restored latency.", "citations": [2]},
    "contributing_factors": [{"text": "The release changed the payment client.", "citations": [2]}],
    "actions": [
        {
            "title": "Load-test the payment client before release",
            "rationale": "The regression reached production undetected.",
            "owner": "ops@example.com",
            "citations": [2],
        }
    ],
}


class FakeProvider:
    name = "fake"

    def __init__(self, response: object) -> None:
        self.response = response
        self.last_request = None

    async def complete(self, request) -> str:
        self.last_request = request
        return self.response if isinstance(self.response, str) else json.dumps(self.response)


@pytest_asyncio.fixture
async def context(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL or "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("COOKIE_SECURE", "false")

    from app.api.v1.postmortems import get_model_provider
    from app.database import Database
    from app.main import create_app
    from app.settings import get_settings

    get_settings.cache_clear()
    database = Database(get_settings())
    await database.open()

    await database.execute("DELETE FROM incident_postmortems WHERE incident_id=%s", (INCIDENT,))
    await database.execute("DELETE FROM incident_evidence WHERE incident_id=%s", (INCIDENT,))
    await database.execute("DELETE FROM incidents WHERE id=%s", (INCIDENT,))
    await database.execute("DELETE FROM users WHERE email=%s", (CLIENT_EMAIL,))

    provider = FakeProvider(GOOD_RESPONSE)
    application = create_app()
    application.state.database = database
    application.dependency_overrides[get_model_provider] = lambda: provider

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        register = await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": TEST_PASSWORD})
        assert register.status_code == 201, register.text

        now = int(time.time() * 1000)
        await database.execute(
            """INSERT INTO incidents (id, client_email, title, severity, status, impact, created_at, updated_at)
               VALUES (%s, %s, 'Checkout outage', 'sev1', 'open', 'All checkouts', %s, %s)""",
            (INCIDENT, CLIENT_EMAIL, now, now),
        )

        yield client, provider, database, application

    await database.close()
    get_settings.cache_clear()


async def add_evidence(client, **overrides) -> dict:
    payload = {"occurred_at": 1_000, "source": "alert", "summary": "Checkout p99 latency crossed 4s", "detail": None}
    payload.update(overrides)
    response = await client.post(f"/v1/postmortems/incidents/{INCIDENT}/evidence", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def seed_two_entries(client) -> None:
    await add_evidence(client)
    await add_evidence(client, occurred_at=1_100, source="deploy", summary="Release 1.2 shipped", detail=None)


@pytest.mark.asyncio
async def test_an_incident_can_be_created_and_listed(context) -> None:
    client, _, _, _ = context
    response = await client.post(
        "/v1/postmortems/incidents", json={"title": "New outage", "severity": "sev2", "impact": "Some users"}
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["title"] == "New outage"

    listing = await client.get("/v1/postmortems/incidents")
    assert listing.status_code == 200
    assert any(row["id"] == created["id"] for row in listing.json())


@pytest.mark.asyncio
async def test_drafting_without_evidence_is_refused(context) -> None:
    client, _, _, _ = context
    response = await client.post(f"/v1/postmortems/incidents/{INCIDENT}/draft")
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_a_grounded_draft_is_stored_with_its_citations(context) -> None:
    client, _, _, _ = context
    await seed_two_entries(client)
    response = await client.post(f"/v1/postmortems/incidents/{INCIDENT}/draft")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "draft"
    assert "latency" in body["summary"].lower()
    assert len(body["actions"]) == 1


@pytest.mark.asyncio
async def test_an_uncited_root_cause_never_reaches_the_database(context) -> None:
    client, provider, _, _ = context
    await seed_two_entries(client)
    provider.response = {"root_cause": {"text": "Made up cause.", "citations": []}}
    response = await client.post(f"/v1/postmortems/incidents/{INCIDENT}/draft")
    assert response.status_code == 201
    assert response.json()["root_cause"] == "Not established by the recorded evidence."


@pytest.mark.asyncio
async def test_an_uncited_action_is_never_stored(context) -> None:
    client, provider, _, _ = context
    await seed_two_entries(client)
    provider.response = {
        "actions": [{"title": "Do it", "rationale": "Because", "owner": "ops", "citations": []}],
    }
    response = await client.post(f"/v1/postmortems/incidents/{INCIDENT}/draft")
    assert response.status_code == 201
    assert response.json()["actions"] == []


@pytest.mark.asyncio
async def test_an_unreadable_model_response_is_a_bad_gateway_not_an_empty_draft(context) -> None:
    client, provider, _, _ = context
    await seed_two_entries(client)
    provider.response = "not json"
    response = await client.post(f"/v1/postmortems/incidents/{INCIDENT}/draft")
    assert response.status_code == 502
    check = await client.get(f"/v1/postmortems/incidents/{INCIDENT}")
    assert check.status_code == 404


@pytest.mark.asyncio
async def test_a_provider_http_failure_is_a_bad_gateway_not_a_crash(context) -> None:
    client, provider, _, _ = context
    await seed_two_entries(client)

    async def failing_complete(request):
        raise httpx.ConnectTimeout("timed out")

    provider.complete = failing_complete
    response = await client.post(f"/v1/postmortems/incidents/{INCIDENT}/draft")
    assert response.status_code == 502


@pytest.mark.asyncio
async def test_a_gemini_sdk_error_is_a_bad_gateway_not_a_crash(context) -> None:
    # google.genai.errors.APIError (auth errors, rate limits, server
    # errors) is NOT a subclass of httpx.HTTPError -- this codebase
    # previously ran the same swap against Anthropic, where a live smoke
    # test against a real (invalid) API key surfaced an uncaught 500 before
    # the equivalent catch was added; covering it here so the same gap
    # can't silently reappear if the provider is ever swapped again.
    from google.genai import errors as genai_errors

    client, provider, _, _ = context
    await seed_two_entries(client)

    async def failing_complete(request):
        raise genai_errors.ClientError(code=401, response_json={"error": {"message": "invalid API key"}})

    provider.complete = failing_complete
    response = await client.post(f"/v1/postmortems/incidents/{INCIDENT}/draft")
    assert response.status_code == 502


@pytest.mark.asyncio
async def test_evidence_is_bounded_to_the_most_recent_entries(context) -> None:
    from app.api.v1.postmortems import MAX_DRAFT_EVIDENCE_ENTRIES

    client, provider, database, _ = context
    total = MAX_DRAFT_EVIDENCE_ENTRIES + 5
    for occurred_at in range(1, total + 1):
        await database.execute(
            """INSERT INTO incident_evidence
                 (incident_id,client_email,occurred_at,source,summary,detail,authorized_by,recorded_at)
               VALUES (%s,%s,%s,'alert',%s,NULL,%s,%s)""",
            (INCIDENT, CLIENT_EMAIL, occurred_at, f"entry-{occurred_at}", CLIENT_EMAIL, occurred_at),
        )

    response = await client.post(f"/v1/postmortems/incidents/{INCIDENT}/draft")
    assert response.status_code == 201, response.text

    body = provider.last_request.messages[0].content
    dropped_count = total - MAX_DRAFT_EVIDENCE_ENTRIES
    for occurred_at in range(1, dropped_count + 1):
        assert f"at {occurred_at})" not in body
    assert f"at {total})" in body


@pytest.mark.asyncio
async def test_publish_requires_a_draft_to_exist(context) -> None:
    client, _, _, _ = context
    response = await client.post(f"/v1/postmortems/incidents/{INCIDENT}/publish")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_publishing_records_a_named_approver(context) -> None:
    client, _, _, _ = context
    await seed_two_entries(client)
    await client.post(f"/v1/postmortems/incidents/{INCIDENT}/draft")
    response = await client.post(f"/v1/postmortems/incidents/{INCIDENT}/publish")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "published"
    assert body["approved_by"] == CLIENT_EMAIL
    assert body["approved_at"] is not None


@pytest.mark.asyncio
async def test_redrafting_a_published_postmortem_returns_it_to_draft(context) -> None:
    client, _, _, _ = context
    await seed_two_entries(client)
    await client.post(f"/v1/postmortems/incidents/{INCIDENT}/draft")
    await client.post(f"/v1/postmortems/incidents/{INCIDENT}/publish")
    response = await client.post(f"/v1/postmortems/incidents/{INCIDENT}/draft")
    assert response.status_code == 201
    assert response.json()["status"] == "draft"


@pytest.mark.asyncio
async def test_a_different_user_cannot_see_or_act_on_this_incident(context) -> None:
    # This is the actual point of the auth work: incidents are scoped to
    # the authenticated caller, not merely gated behind "is signed in at
    # all." A second registered user must get a 404 (not a leak, not a 403
    # that confirms the incident exists) on every route touching this
    # incident.
    _, _, database, application = context
    other_email = "postmortem-test-other-user@example.com"
    await database.execute("DELETE FROM users WHERE email=%s", (other_email,))

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as other:
        register = await other.post("/v1/auth/register", json={"email": other_email, "password": TEST_PASSWORD})
        assert register.status_code == 201

        assert (await other.get(f"/v1/postmortems/incidents/{INCIDENT}/evidence")).status_code == 404
        assert (await other.post(f"/v1/postmortems/incidents/{INCIDENT}/draft")).status_code == 404
        assert (await other.get(f"/v1/postmortems/incidents/{INCIDENT}")).status_code == 404
        assert (await other.post(f"/v1/postmortems/incidents/{INCIDENT}/publish")).status_code == 404

        listing = await other.get("/v1/postmortems/incidents")
        assert listing.status_code == 200
        assert all(row["id"] != INCIDENT for row in listing.json())
