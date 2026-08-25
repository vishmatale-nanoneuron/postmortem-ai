"""End-to-end MCP tests: a real MCP client (the official SDK's streamable-
HTTP client) talking to the real mounted /mcp server, in-process via
ASGITransport (no real network server needed) but exercising the actual
wire protocol -- initialize handshake, tools/list, tools/call -- not a
shortcut around it. Real Postgres via TEST_DATABASE_URL.

Known noise, not a real failure: every test here also reports a teardown
ERROR ("Attempted to exit cancel scope in a different task", or an
"Event loop is closed" psycopg_pool warning depending on run). This is an
anyio/pytest-asyncio artifact of driving FastMCP's own background task
group (session_manager.run()) across an in-process ASGITransport rather
than a real socket -- confirmed harmless: the actual test body and every
assertion in it complete and pass before teardown runs, reproduced
consistently across multiple runs and two different fixture structures.
Production is unaffected -- it runs over real per-request ASGI hosting on
Vercel, not this in-process test harness's specific teardown ordering.
"""

import json
import os
from contextlib import asynccontextmanager

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not configured")

FOUNDER_EMAIL = "mcp-test-founder@example.com"
CLIENT_EMAIL = "mcp-test-client@example.com"


@pytest_asyncio.fixture
async def context(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL or "")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-used")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("FOUNDER_EMAIL", FOUNDER_EMAIL)

    # RAG's embedding call (draft/publish) is best-effort but would
    # otherwise attempt a real network call in every test here -- fake it
    # deterministically, same as test_postmortem_routes.py.
    async def fake_embed_text(_client, _text):
        return [0.1] * 768

    monkeypatch.setattr("app.api.v1.postmortems.embed_text", fake_embed_text)
    monkeypatch.setattr("app.ai.rag.embed_text", fake_embed_text)

    from app.database import Database
    from app.main import create_app
    from app.settings import get_settings

    get_settings.cache_clear()

    # Throwaway pool just for pre-test cleanup -- opened and closed before
    # the app's own lifespan (and its own pool) starts, so exactly one
    # pool is ever live at a time instead of two competing ones.
    cleanup_database = Database(get_settings())
    await cleanup_database.open()
    await cleanup_database.execute("DELETE FROM users WHERE email IN (%s, %s)", (FOUNDER_EMAIL, CLIENT_EMAIL))
    await cleanup_database.close()

    application = create_app()

    # The MCP session manager's own lifespan (session_manager.run()) --
    # and this app's own database pool -- only start inside create_app()'s
    # lifespan context, which AsyncClient(transport=ASGITransport(...))
    # does NOT enter on its own; drive it explicitly, and do everything
    # (registration included) inside it, so there is exactly one pool for
    # the whole test.
    async with application.router.lifespan_context(application):
        async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as http:
            founder_register = await http.post(
                "/v1/auth/register", json={"email": FOUNDER_EMAIL, "password": "correct-horse-battery"}
            )
            assert founder_register.status_code == 201
            founder_token = http.cookies.get("session_token")
            assert founder_token

            http.cookies.clear()
            client_register = await http.post(
                "/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "correct-horse-battery"}
            )
            assert client_register.status_code == 201
            client_token = http.cookies.get("session_token")
            assert client_token

            yield application, founder_token, client_token

    get_settings.cache_clear()


def _mcp_http_client_factory(app):
    def factory(headers=None, timeout=None, auth=None):
        kwargs = {"transport": ASGITransport(app=app), "base_url": "http://test", "follow_redirects": True}
        if headers is not None:
            kwargs["headers"] = headers
        if timeout is not None:
            kwargs["timeout"] = timeout
        if auth is not None:
            kwargs["auth"] = auth
        return httpx.AsyncClient(**kwargs)

    return factory


@asynccontextmanager
async def mcp_session(app, token: str | None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with streamablehttp_client(
        "http://test/mcp/", headers=headers, httpx_client_factory=_mcp_http_client_factory(app)
    ) as (read, write, _get_session_id):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


@pytest.mark.asyncio
async def test_an_unauthenticated_call_is_rejected(context) -> None:
    app, _founder_token, _client_token = context
    with pytest.raises(Exception):
        async with mcp_session(app, token=None) as session:
            await session.list_tools()


@pytest.mark.asyncio
async def test_tools_are_listed_and_include_the_expected_names(context) -> None:
    app, founder_token, _client_token = context
    async with mcp_session(app, token=founder_token) as session:
        result = await session.list_tools()
    names = {tool.name for tool in result.tools}
    assert "get_founder_summary" in names
    assert "list_incidents" in names
    assert "create_incident" in names
    assert "run_read_only_sql" in names
    assert "find_similar_incidents" in names


@pytest.mark.asyncio
async def test_a_non_founder_cannot_call_founder_tools(context) -> None:
    app, _founder_token, client_token = context
    async with mcp_session(app, token=client_token) as session:
        result = await session.call_tool("get_founder_summary", {})
    assert result.isError is True
    assert "founder" in str(result.content).lower()


@pytest.mark.asyncio
async def test_a_founder_can_call_get_founder_summary(context) -> None:
    app, founder_token, _client_token = context
    async with mcp_session(app, token=founder_token) as session:
        result = await session.call_tool("get_founder_summary", {})
    assert result.isError is not True
    assert "total_users" in str(result.content)


@pytest.mark.asyncio
async def test_an_unpaid_client_cannot_create_an_incident_via_mcp(context) -> None:
    app, _founder_token, client_token = context
    async with mcp_session(app, token=client_token) as session:
        result = await session.call_tool("create_incident", {"title": "Should be blocked", "severity": "sev2"})
    assert result.isError is True
    assert "subscription" in str(result.content).lower()


@pytest.mark.asyncio
async def test_a_founder_can_create_and_list_their_own_incident_via_mcp(context) -> None:
    app, founder_token, _client_token = context
    async with mcp_session(app, token=founder_token) as session:
        created = await session.call_tool(
            "create_incident", {"title": "MCP-created incident", "severity": "sev2"}
        )
        assert created.isError is not True

        listed = await session.call_tool("list_incidents", {})
    assert "MCP-created incident" in str(listed.content)


@pytest.mark.asyncio
async def test_publish_postmortem_via_mcp_fails_cleanly_not_with_a_missing_argument_error(context) -> None:
    # Regression test: the publish_postmortem MCP tool wrapper was missing
    # settings= after postmortems.py's route gained that parameter (found
    # and fixed twice now, same class of bug as draft_postmortem earlier).
    # Calling it on an incident with no draft yet should fail with a clean
    # "no draft to publish" tool error, never a raw Python TypeError about
    # a missing required argument.
    app, founder_token, _client_token = context
    async with mcp_session(app, token=founder_token) as session:
        created = await session.call_tool(
            "create_incident", {"title": "No draft yet", "severity": "sev3"}
        )
        assert created.isError is not True
        created_body = json.loads(created.content[0].text)  # type: ignore[union-attr]
        incident_id = created_body["id"]

        result = await session.call_tool("publish_postmortem", {"incident_id": incident_id})
    assert result.isError is True
    text = str(result.content)
    assert "TypeError" not in text
    assert "missing" not in text.lower()


@pytest.mark.asyncio
async def test_get_and_update_integrations_via_mcp(context) -> None:
    app, founder_token, _client_token = context
    async with mcp_session(app, token=founder_token) as session:
        initial = await session.call_tool("get_integrations", {})
        assert initial.isError is not True
        assert "false" in str(initial.content).lower()  # not connected yet

        updated = await session.call_tool(
            "update_integrations",
            {"slack_webhook_url": "https://hooks.example.com/slack", "linear_team_id": "team-1"},
        )
        assert updated.isError is not True
        assert "true" in str(updated.content).lower()  # slack now connected


@pytest.mark.asyncio
async def test_run_read_only_sql_rejects_a_write_statement(context) -> None:
    app, founder_token, _client_token = context
    async with mcp_session(app, token=founder_token) as session:
        result = await session.call_tool("run_read_only_sql", {"sql": "DELETE FROM users"})
    assert result.isError is True


@pytest.mark.asyncio
async def test_run_read_only_sql_rejects_a_data_modifying_cte(context) -> None:
    # A WITH clause can legally contain a data-modifying CTE -- single
    # statement, starts with "with", would otherwise pass the naive check.
    app, founder_token, _client_token = context
    async with mcp_session(app, token=founder_token) as session:
        result = await session.call_tool(
            "run_read_only_sql", {"sql": "WITH d AS (DELETE FROM users RETURNING id) SELECT * FROM d"}
        )
    assert result.isError is True


@pytest.mark.asyncio
async def test_run_read_only_sql_is_bounded_by_a_statement_timeout(context) -> None:
    # Regression for a real gap: read_only_transaction() blocked a *write*
    # but not an expensive-to-compute SELECT. The connection pool here is
    # only max_size=5 (see database.py), so an unbounded pg_sleep() would
    # hold one of five connections indefinitely -- one or two such calls
    # starve every other request on the whole API, not just this tool's
    # caller. A 5s SET LOCAL statement_timeout means this legal single
    # SELECT still gets cancelled server-side rather than hanging forever.
    app, founder_token, _client_token = context
    async with mcp_session(app, token=founder_token) as session:
        result = await session.call_tool("run_read_only_sql", {"sql": "SELECT pg_sleep(30)"})
    assert result.isError is True


@pytest.mark.asyncio
async def test_run_read_only_sql_redacts_password_hash(context) -> None:
    app, founder_token, _client_token = context
    async with mcp_session(app, token=founder_token) as session:
        result = await session.call_tool(
            "run_read_only_sql", {"sql": "SELECT email, password_hash FROM users WHERE email = 'mcp-test-founder@example.com'"}
        )
    assert result.isError is not True
    text = str(result.content)
    assert "[redacted]" in text
    assert "scrypt$" not in text
