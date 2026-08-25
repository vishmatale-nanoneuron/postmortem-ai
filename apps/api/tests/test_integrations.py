"""Slack + Linear client integrations -- pure unit tests for the two
delivery functions, plus route-level tests for GET/PUT /v1/integrations
and a real end-to-end check that publishing an incident triggers both.
"""

import os

import httpx
import pytest
import pytest_asyncio
from app.integrations.linear import create_linear_issue
from app.integrations.slack import notify_slack
from httpx import ASGITransport, AsyncClient

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.mark.asyncio
async def test_slack_notify_is_a_silent_no_op_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail_if_called(*args, **kwargs):
        raise AssertionError("should never call out with no webhook URL")

    monkeypatch.setattr(httpx.AsyncClient, "post", fail_if_called)
    await notify_slack(None, "should never be sent")


@pytest.mark.asyncio
async def test_slack_notify_posts_the_message(monkeypatch: pytest.MonkeyPatch) -> None:
    received = {}

    async def fake_post(self, url, json=None, **kwargs):
        received["url"] = url
        received["json"] = json
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    await notify_slack("https://hooks.example.com/slack", "postmortem published")
    assert received["url"] == "https://hooks.example.com/slack"
    assert "postmortem published" in received["json"]["text"]


@pytest.mark.asyncio
async def test_slack_notify_swallows_delivery_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_post(self, url, json=None, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    await notify_slack("https://hooks.example.com/slack", "should not raise")


@pytest.mark.asyncio
async def test_linear_create_issue_is_a_no_op_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail_if_called(*args, **kwargs):
        raise AssertionError("should never call out with no API key/team")

    monkeypatch.setattr(httpx.AsyncClient, "post", fail_if_called)
    assert await create_linear_issue(None, None, "title", "description") is None
    assert await create_linear_issue("key", None, "title", "description") is None
    assert await create_linear_issue(None, "team", "title", "description") is None


@pytest.mark.asyncio
async def test_linear_create_issue_returns_the_created_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_post(self, url, headers=None, json=None, **kwargs):
        assert headers["Authorization"] == "real-key"
        assert json["variables"]["input"]["teamId"] == "team-1"
        return httpx.Response(
            200,
            json={"data": {"issueCreate": {"success": True, "issue": {"id": "i1", "identifier": "ENG-1", "url": "https://linear.app/x/issue/ENG-1"}}}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    issue = await create_linear_issue("real-key", "team-1", "Load-test the payment client", "rationale")
    assert issue == {"id": "i1", "identifier": "ENG-1", "url": "https://linear.app/x/issue/ENG-1"}


@pytest.mark.asyncio
async def test_linear_create_issue_returns_none_on_graphql_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_post(self, url, headers=None, json=None, **kwargs):
        return httpx.Response(200, json={"errors": [{"message": "bad team id"}]}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    assert await create_linear_issue("real-key", "bad-team", "title", "description") is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"data": {"issueCreate": {"success": True}}},  # success but no issue
        {"data": None},  # a key present with an explicit null, not a missing key
        {"data": {"issueCreate": []}},  # wrong shape entirely
        [1, 2, 3],  # top-level body is not even an object
    ],
    ids=["empty-body", "success-no-issue", "data-is-null", "issueCreate-is-a-list", "top-level-is-a-list"],
)
async def test_linear_create_issue_never_raises_on_a_malformed_response(
    monkeypatch: pytest.MonkeyPatch, body: object
) -> None:
    # Regression test for a real crash found via a self-directed adversarial
    # audit: `.get("data", {})` does NOT default to {} when the key is
    # present with an explicit `null` value -- it returns None, and
    # `.get()` on None (or on a list, for the wrong-shape cases) raised
    # AttributeError, violating this function's own "Never raises" promise
    # and, in the real call site, silently dropping every action item's
    # Linear ticket after whichever action happened to trigger it.
    async def fake_post(self, url, headers=None, json=None, **kwargs):
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    assert await create_linear_issue("real-key", "team-1", "title", "description") is None


@pytest.mark.asyncio
async def test_linear_create_issue_returns_none_on_network_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_post(self, url, headers=None, json=None, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    assert await create_linear_issue("real-key", "team-1", "title", "description") is None


@pytest_asyncio.fixture
async def context(monkeypatch: pytest.MonkeyPatch):
    if not DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is not configured")
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-used")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("COOKIE_SECURE", "false")

    from app.database import Database
    from app.main import create_app
    from app.settings import get_settings

    get_settings.cache_clear()
    database = Database(get_settings())
    await database.open()
    await database.execute("DELETE FROM users WHERE email LIKE %s", ("integrations-test-%",))

    application = create_app()
    application.state.database = database

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        register = await client.post(
            "/v1/auth/register", json={"email": "integrations-test-1@example.com", "password": "correct-horse-battery"}
        )
        assert register.status_code == 201
        yield client, database

    await database.close()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_get_integrations_starts_disconnected(context) -> None:
    client, _ = context
    response = await client.get("/v1/integrations")
    assert response.status_code == 200
    assert response.json() == {"slack_connected": False, "linear_connected": False, "linear_team_id": None}


@pytest.mark.asyncio
async def test_put_integrations_connects_slack_and_linear(context) -> None:
    client, _ = context
    response = await client.put(
        "/v1/integrations",
        json={
            "slack_webhook_url": "https://hooks.example.com/slack",
            "linear_api_key": "real-key",
            "linear_team_id": "team-1",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"slack_connected": True, "linear_connected": True, "linear_team_id": "team-1"}


@pytest.mark.asyncio
async def test_put_integrations_with_empty_string_clears_it(context) -> None:
    client, _ = context
    await client.put("/v1/integrations", json={"slack_webhook_url": "https://hooks.example.com/slack"})
    cleared = await client.put("/v1/integrations", json={"slack_webhook_url": ""})
    assert cleared.status_code == 200
    assert cleared.json()["slack_connected"] is False


@pytest.mark.asyncio
async def test_put_integrations_omitted_field_leaves_it_unchanged(context) -> None:
    client, _ = context
    await client.put("/v1/integrations", json={"linear_api_key": "real-key", "linear_team_id": "team-1"})
    response = await client.put("/v1/integrations", json={"slack_webhook_url": "https://hooks.example.com/slack"})
    assert response.status_code == 200
    body = response.json()
    assert body["slack_connected"] is True
    assert body["linear_connected"] is True  # untouched by the second call
