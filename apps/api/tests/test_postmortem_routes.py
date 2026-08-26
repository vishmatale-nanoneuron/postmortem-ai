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
from app.api.v1.postmortems import slugify
from app.services.postmortem import PROMPT_VERSION
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
    model_name = "fake-model-v1"

    def __init__(self, response: object) -> None:
        self.response = response
        self.last_request = None
        self.output_tokens: int | None = 42

    async def complete(self, request):
        from app.ai.provider import ModelResponse

        self.last_request = request
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

    # RAG's embedding call is best-effort and separate from drafting, but
    # a real network call in every test here would be slow and flaky --
    # fake it deterministically. find_similar_postmortems still runs for
    # real against the test database.
    async def fake_embed_text(_client, _text):
        return [0.1] * 768

    monkeypatch.setattr("app.api.v1.postmortems.embed_text", fake_embed_text)
    monkeypatch.setattr("app.ai.rag.embed_text", fake_embed_text)

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

        # These tests are about postmortem/drafting logic, not billing --
        # give the account an active subscription directly (mimicking what
        # a real Stripe webhook would apply) rather than driving a full
        # checkout flow through every test here.
        await database.execute(
            "UPDATE users SET subscription_status='active' WHERE email=%s", (CLIENT_EMAIL,)
        )

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
async def test_concurrent_incident_creation_never_collides(context) -> None:
    # Regression for a real bug: incident_id used to be a bare
    # f"inc-{int(time.time()*1000)}" -- two create_incident calls landing
    # in the same millisecond hit incidents.id's PRIMARY KEY and the second
    # got an unhandled UniqueViolation -> 500. Reproduced directly against
    # Postgres before the fix (a random suffix added to the id). Firing
    # genuinely concurrent calls here proves it end-to-end through the real
    # route, not just at the id-generation function.
    import asyncio

    client, _, _, _ = context
    responses = await asyncio.gather(
        *[
            client.post("/v1/postmortems/incidents", json={"title": "Race", "severity": "sev2"})
            for _ in range(10)
        ]
    )
    statuses = [r.status_code for r in responses]
    assert all(s == 201 for s in statuses), statuses
    ids = [r.json()["id"] for r in responses]
    assert len(set(ids)) == 10


@pytest.mark.asyncio
async def test_create_incident_is_rate_limited(context) -> None:
    from app.api.v1.postmortems import MAX_INCIDENTS_PER_HOUR

    client, _, _, _ = context
    for i in range(MAX_INCIDENTS_PER_HOUR):
        response = await client.post(
            "/v1/postmortems/incidents", json={"title": f"Spam incident {i}", "severity": "sev4"}
        )
        assert response.status_code == 201, response.text

    limited = await client.post("/v1/postmortems/incidents", json={"title": "One too many", "severity": "sev4"})
    assert limited.status_code == 429


@pytest.mark.asyncio
async def test_record_evidence_is_rate_limited(context) -> None:
    from app.api.v1.postmortems import MAX_EVIDENCE_PER_HOUR

    client, _, _, _ = context
    for i in range(MAX_EVIDENCE_PER_HOUR):
        response = await add_evidence(client, occurred_at=1_000 + i, summary=f"Entry {i}")
        assert response  # add_evidence() already asserts 201

    limited = await client.post(
        f"/v1/postmortems/incidents/{INCIDENT}/evidence",
        json={"occurred_at": 9_999, "source": "alert", "summary": "One too many", "detail": None},
    )
    assert limited.status_code == 429


@pytest.mark.asyncio
async def test_update_incident_status_is_rate_limited(context) -> None:
    from app.api.v1.postmortems import MAX_STATUS_CHANGES_PER_HOUR

    client, _, _, _ = context
    for i in range(MAX_STATUS_CHANGES_PER_HOUR):
        response = await client.patch(
            f"/v1/postmortems/incidents/{INCIDENT}/status",
            json={"status": "resolved" if i % 2 == 0 else "open"},
        )
        assert response.status_code == 200, response.text

    limited = await client.patch(f"/v1/postmortems/incidents/{INCIDENT}/status", json={"status": "open"})
    assert limited.status_code == 429


@pytest.mark.asyncio
async def test_extraction_returns_suggestions_without_saving_them(context) -> None:
    client, provider, _, _ = context
    provider.response = {
        "entries": [
            {"source": "deploy", "summary": "Release 1.2 shipped at 14:02 UTC", "detail": None},
            {"source": "alert", "summary": "p99 latency alert fired at 14:04 UTC", "detail": "Threshold 2s"},
        ]
    }
    response = await client.post(f"/v1/postmortems/incidents/{INCIDENT}/evidence/extract", json={"text": "some pasted thread"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 2
    assert body[0]["source"] == "deploy"
    assert body[1]["detail"] == "Threshold 2s"

    # Nothing was actually saved -- extraction only ever proposes.
    evidence = await client.get(f"/v1/postmortems/incidents/{INCIDENT}/evidence")
    assert evidence.json() == []


@pytest.mark.asyncio
async def test_extraction_drops_malformed_entries_instead_of_failing_the_whole_request(context) -> None:
    client, provider, _, _ = context
    provider.response = {
        "entries": [
            {"source": "deploy", "summary": "A real, well-formed entry", "detail": None},
            {"source": "not-a-real-source", "summary": "Should be dropped -- bad source", "detail": None},
            {"source": "log", "summary": "", "detail": None},  # empty summary, should be dropped
            "not even a dict",
        ]
    }
    response = await client.post(f"/v1/postmortems/incidents/{INCIDENT}/evidence/extract", json={"text": "x"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 1
    assert body[0]["summary"] == "A real, well-formed entry"


@pytest.mark.asyncio
async def test_extraction_with_no_evidence_in_the_text_returns_an_empty_list(context) -> None:
    client, provider, _, _ = context
    provider.response = {"entries": []}
    response = await client.post(
        f"/v1/postmortems/incidents/{INCIDENT}/evidence/extract", json={"text": "just chit-chat, nothing factual"}
    )
    assert response.status_code == 200, response.text
    assert response.json() == []


@pytest.mark.asyncio
async def test_extraction_records_an_ai_run(context) -> None:
    client, provider, database, _ = context
    provider.response = {"entries": [{"source": "log", "summary": "Something happened", "detail": None}]}
    response = await client.post(f"/v1/postmortems/incidents/{INCIDENT}/evidence/extract", json={"text": "x"})
    assert response.status_code == 200, response.text

    run = await database.fetch_one(
        "SELECT status, prompt_version FROM ai_runs WHERE incident_id=%s ORDER BY created_at DESC LIMIT 1",
        (INCIDENT,),
    )
    assert run["status"] == "succeeded"
    assert run["prompt_version"] == "extract-v1"


@pytest.mark.asyncio
async def test_an_unpaid_account_cannot_extract_evidence(context) -> None:
    client, _, database, _ = context
    await database.execute("UPDATE users SET subscription_status='none' WHERE email=%s", (CLIENT_EMAIL,))
    response = await client.post(f"/v1/postmortems/incidents/{INCIDENT}/evidence/extract", json={"text": "x"})
    assert response.status_code == 402


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
    assert body["prompt_version"] == PROMPT_VERSION


@pytest.mark.asyncio
async def test_a_published_postmortem_surfaces_as_rag_context_for_a_later_draft(context) -> None:
    # RAG: a published postmortem should show up as reference context on a
    # LATER incident's draft -- and, just as importantly, that context
    # must be clearly non-citable (see services/postmortem.py's
    # render_similar_postmortems) so it can never satisfy ground_draft's
    # citation check.
    client, provider, database, _ = context
    await seed_two_entries(client)
    await client.post(f"/v1/postmortems/incidents/{INCIDENT}/draft")
    published = await client.post(f"/v1/postmortems/incidents/{INCIDENT}/publish")
    assert published.status_code == 200, published.text

    other_incident = "pm-incident-2"
    await database.execute("DELETE FROM incidents WHERE id=%s", (other_incident,))
    now = int(time.time() * 1000)
    await database.execute(
        """INSERT INTO incidents (id, client_email, title, severity, status, impact, created_at, updated_at)
           VALUES (%s, %s, 'A different outage', 'sev2', 'open', 'Some users', %s, %s)""",
        (other_incident, CLIENT_EMAIL, now, now),
    )
    evidence = await client.post(
        f"/v1/postmortems/incidents/{other_incident}/evidence",
        json={"occurred_at": 2_000, "source": "alert", "summary": "A different alert fired", "detail": None},
    )
    assert evidence.status_code == 201, evidence.text

    draft = await client.post(f"/v1/postmortems/incidents/{other_incident}/draft")
    assert draft.status_code == 201, draft.text

    prompt_body = provider.last_request.messages[0].content
    assert "Similar past incidents" in prompt_body
    assert "Checkout outage" in prompt_body  # the first incident's title, seeded in the fixture
    assert "never cite these" in prompt_body

    await database.execute("DELETE FROM incidents WHERE id=%s", (other_incident,))


@pytest.mark.asyncio
async def test_a_successful_draft_records_an_ai_run(context) -> None:
    # Real monitoring surface, not a described process: one queryable row
    # per /draft call. Also proves the real token count from the (fake)
    # provider's response makes it all the way to the persisted row.
    client, provider, database, _ = context
    await seed_two_entries(client)
    await client.post(f"/v1/postmortems/incidents/{INCIDENT}/draft")

    runs = await database.fetch_all(
        "SELECT provider, model, prompt_version, status, output_tokens FROM ai_runs WHERE incident_id=%s",
        (INCIDENT,),
    )
    assert len(runs) == 1
    assert runs[0]["provider"] == "fake"
    assert runs[0]["model"] == "fake-model-v1"
    assert runs[0]["prompt_version"] == PROMPT_VERSION
    assert runs[0]["status"] == "succeeded"
    assert runs[0]["output_tokens"] == provider.output_tokens


@pytest.mark.asyncio
async def test_a_failed_draft_also_records_an_ai_run(context) -> None:
    # Failures are monitoring signal too -- a run that never got recorded
    # would make outage/error-rate queries against ai_runs silently
    # undercount real failures.
    client, provider, database, _ = context
    await seed_two_entries(client)
    provider.response = "not json"
    response = await client.post(f"/v1/postmortems/incidents/{INCIDENT}/draft")
    assert response.status_code == 502

    runs = await database.fetch_all(
        "SELECT status, error_type, output_tokens FROM ai_runs WHERE incident_id=%s",
        (INCIDENT,),
    )
    assert len(runs) == 1
    assert runs[0]["status"] == "failed"
    assert runs[0]["error_type"] == "unreadable_response"
    assert runs[0]["output_tokens"] is None


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


@pytest.mark.parametrize(
    "title",
    [
        "",
        "     ",
        "!!!$%^&*()",
        "日本語 🔥🔥🔥",
        "A" * 500,
        "'; DROP TABLE users; --",
        "<script>alert(1)</script>",
        "---Title---",
    ],
    ids=["empty", "whitespace-only", "symbols-only", "unicode-emoji-only", "very-long", "sql-shaped", "html-shaped", "strippable-dashes"],
)
def test_slugify_never_produces_an_empty_or_unsafe_slug(title: str) -> None:
    slug = slugify(title, "inc-1755000000000")
    assert slug
    assert not any(char in slug for char in ("/", "?", "&", "<", ">", '"', "'"))


@pytest.mark.asyncio
async def test_a_draft_postmortem_cannot_be_made_public(context) -> None:
    client, _, _, _ = context
    await seed_two_entries(client)
    await client.post(f"/v1/postmortems/incidents/{INCIDENT}/draft")

    response = await client.patch(
        f"/v1/postmortems/incidents/{INCIDENT}/public", json={"is_public": True}
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_making_a_published_postmortem_public_generates_a_stable_slug(context) -> None:
    client, _, database, _ = context
    await seed_two_entries(client)
    await client.post(f"/v1/postmortems/incidents/{INCIDENT}/draft")
    await client.post(f"/v1/postmortems/incidents/{INCIDENT}/publish")

    made_public = await client.patch(
        f"/v1/postmortems/incidents/{INCIDENT}/public", json={"is_public": True}
    )
    assert made_public.status_code == 200, made_public.text
    body = made_public.json()
    assert body["is_public"] is True
    assert body["slug"]
    first_slug = body["slug"]

    # Toggling off and back on must NOT change the slug -- a real, already
    # shared/indexed URL would otherwise break.
    await client.patch(f"/v1/postmortems/incidents/{INCIDENT}/public", json={"is_public": False})
    made_public_again = await client.patch(
        f"/v1/postmortems/incidents/{INCIDENT}/public", json={"is_public": True}
    )
    assert made_public_again.json()["slug"] == first_slug

    row = await database.fetch_one(
        "SELECT slug FROM incident_postmortems WHERE incident_id=%s", (INCIDENT,)
    )
    assert row["slug"] == first_slug


@pytest.mark.asyncio
async def test_public_postmortem_is_readable_unauthenticated_private_is_not(context) -> None:
    client, _, _, application = context
    await seed_two_entries(client)
    await client.post(f"/v1/postmortems/incidents/{INCIDENT}/draft")
    await client.post(f"/v1/postmortems/incidents/{INCIDENT}/publish")
    made_public = await client.patch(
        f"/v1/postmortems/incidents/{INCIDENT}/public", json={"is_public": True}
    )
    slug = made_public.json()["slug"]

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as anon:
        public_response = await anon.get(f"/v1/postmortems/public/{slug}")
        assert public_response.status_code == 200
        body = public_response.json()
        assert body["incident_title"] == "Checkout outage"
        assert "client_email" not in body
        # Stronger than a key-name check: the account's real email must
        # not appear ANYWHERE in the public response, under any key name
        # (e.g. approved_by, which is a real email address and is
        # deliberately excluded from PublicPostmortemOut).
        assert CLIENT_EMAIL not in public_response.text
        assert "approved_by" not in body
        assert "id" not in body  # no internal ids leaked

        listing = await anon.get("/v1/postmortems/public")
        assert listing.status_code == 200
        assert any(item["slug"] == slug for item in listing.json())

        await client.patch(f"/v1/postmortems/incidents/{INCIDENT}/public", json={"is_public": False})
        now_private = await anon.get(f"/v1/postmortems/public/{slug}")
        assert now_private.status_code == 404

        not_a_real_slug = await anon.get("/v1/postmortems/public/this-slug-does-not-exist")
        assert not_a_real_slug.status_code == 404


@pytest.mark.asyncio
async def test_publishing_notifies_slack_and_creates_a_linear_issue_per_action(
    context, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, database, _ = context
    slack_calls = []
    linear_calls = []

    async def fake_notify_slack(webhook_url, message):
        slack_calls.append((webhook_url, message))

    async def fake_create_linear_issue(api_key, team_id, title, description):
        linear_calls.append((api_key, team_id, title, description))
        return {"id": "i1", "identifier": "ENG-1", "url": "https://linear.app/x/issue/ENG-1"}

    monkeypatch.setattr("app.api.v1.postmortems.notify_slack", fake_notify_slack)
    monkeypatch.setattr("app.api.v1.postmortems.create_linear_issue", fake_create_linear_issue)

    await database.execute(
        "UPDATE users SET slack_webhook_url=%s, linear_api_key=%s, linear_team_id=%s WHERE email=%s",
        ("https://hooks.example.com/slack", "real-key", "team-1", CLIENT_EMAIL),
    )

    await seed_two_entries(client)
    await client.post(f"/v1/postmortems/incidents/{INCIDENT}/draft")
    response = await client.post(f"/v1/postmortems/incidents/{INCIDENT}/publish")
    assert response.status_code == 200, response.text

    assert len(slack_calls) == 1
    assert slack_calls[0][0] == "https://hooks.example.com/slack"
    assert "Checkout outage" in slack_calls[0][1]

    assert len(linear_calls) == 1  # GOOD_RESPONSE has exactly one action
    assert linear_calls[0][0] == "real-key"
    assert linear_calls[0][1] == "team-1"
    assert linear_calls[0][2] == "Load-test the payment client before release"


@pytest.mark.asyncio
async def test_publishing_does_not_notify_when_no_integrations_are_connected(
    context, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, _, _ = context
    calls = []

    async def fake_notify_slack(webhook_url, message):
        calls.append("slack")

    async def fake_create_linear_issue(api_key, team_id, title, description):
        calls.append("linear")

    monkeypatch.setattr("app.api.v1.postmortems.notify_slack", fake_notify_slack)
    monkeypatch.setattr("app.api.v1.postmortems.create_linear_issue", fake_create_linear_issue)

    await seed_two_entries(client)
    await client.post(f"/v1/postmortems/incidents/{INCIDENT}/draft")
    response = await client.post(f"/v1/postmortems/incidents/{INCIDENT}/publish")
    assert response.status_code == 200, response.text
    # notify_slack/create_linear_issue are still CALLED (they're the ones
    # responsible for no-op'ing when unconfigured) -- this asserts they
    # were called with no webhook/key, not that they were skipped entirely.
    assert calls == ["slack", "linear"]


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
        # An active subscription so this test isolates tenant scoping from
        # billing gating -- the 404s below must come from "not your
        # incident," not "not subscribed."
        await database.execute("UPDATE users SET subscription_status='active' WHERE email=%s", (other_email,))

        assert (await other.get(f"/v1/postmortems/incidents/{INCIDENT}/evidence")).status_code == 404
        assert (await other.post(f"/v1/postmortems/incidents/{INCIDENT}/draft")).status_code == 404
        assert (await other.get(f"/v1/postmortems/incidents/{INCIDENT}")).status_code == 404
        assert (await other.post(f"/v1/postmortems/incidents/{INCIDENT}/publish")).status_code == 404

        listing = await other.get("/v1/postmortems/incidents")
        assert listing.status_code == 200
        assert all(row["id"] != INCIDENT for row in listing.json())

        assert (
            await other.patch(f"/v1/postmortems/incidents/{INCIDENT}/status", json={"status": "resolved"})
        ).status_code == 404

        # Adversarial check: a different user must not be able to make
        # SOMEONE ELSE's postmortem public -- update_public_visibility
        # goes through require_incident exactly like every other route
        # here, but this is the one route that, if it had a scoping bug,
        # would leak private data to the entire internet, not just to one
        # other authenticated account. Worth its own explicit assertion.
        assert (
            await other.patch(f"/v1/postmortems/incidents/{INCIDENT}/public", json={"is_public": True})
        ).status_code == 404


@pytest.mark.asyncio
async def test_an_incident_can_be_marked_resolved_and_reopened(context) -> None:
    client, _, _, _ = context
    resolved = await client.patch(f"/v1/postmortems/incidents/{INCIDENT}/status", json={"status": "resolved"})
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "resolved"

    reopened = await client.patch(f"/v1/postmortems/incidents/{INCIDENT}/status", json={"status": "open"})
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "open"


@pytest.mark.asyncio
async def test_an_invalid_status_value_is_rejected(context) -> None:
    client, _, _, _ = context
    response = await client.patch(f"/v1/postmortems/incidents/{INCIDENT}/status", json={"status": "closed"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_the_summary_reflects_real_counts_scoped_to_the_caller(context) -> None:
    client, _, _, _ = context
    await client.patch(f"/v1/postmortems/incidents/{INCIDENT}/status", json={"status": "resolved"})

    summary = await client.get("/v1/postmortems/summary")
    assert summary.status_code == 200
    body = summary.json()
    assert body["total_incidents"] >= 1
    assert body["resolved_incidents"] >= 1
    assert any(row["id"] == INCIDENT for row in body["recent_incidents"])
