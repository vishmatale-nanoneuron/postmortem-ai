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
    # httpx's ASGITransport sends "test" as the Host header (from
    # base_url="http://test" below) -- the MCP SDK's DNS-rebinding
    # protection (settings.mcp_allowed_hosts) would 421 every request in
    # this file otherwise. Production's real default is the actual API
    # domain (see settings.py); this is a test-only addition, same as
    # COOKIE_SECURE=false above.
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "test,postmortem-ai-api.vercel.app,127.0.0.1:8000,localhost:8000")

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
    # account_activity_log.client_email is a plain column, not a foreign
    # key (deliberately -- see migration 0024's own comment: history must
    # survive even an account being deleted) -- so deleting the users rows
    # above does NOT cascade-clean this table. Without this, a second test
    # run would see a previous run's rows too, breaking the exact-count
    # assertions in the agent-accountability tests below.
    await cleanup_database.execute(
        "DELETE FROM account_activity_log WHERE client_email IN (%s, %s)", (FOUNDER_EMAIL, CLIENT_EMAIL)
    )
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
async def test_a_brand_new_unpaid_client_cannot_create_an_incident_via_mcp(context) -> None:
    """The free-incident trial is retired for new grants (see
    test_free_incident.py on the REST side, and auth.py's
    has_free_incident_available docstring) -- a brand-new signup calling
    this tool via an MCP client (Claude Desktop, etc.) is blocked from its
    very first call, the same as POST /v1/postmortems/incidents. This test
    used to assert the opposite (that a free incident was granted); it was
    updated to match the policy change, not a regression caught here --
    confirmed via the actual error message below, not just isError."""
    app, _founder_token, client_token = context
    async with mcp_session(app, token=client_token) as session:
        result = await session.call_tool("create_incident", {"title": "Should be blocked", "severity": "sev2"})
    assert result.isError is True
    assert "subscription" in str(result.content).lower()


@pytest.mark.asyncio
async def test_an_account_that_already_spent_its_free_slot_is_blocked_via_mcp(context) -> None:
    from app.database import Database
    from app.settings import get_settings

    app, _founder_token, client_token = context
    database = Database(get_settings())
    await database.open()
    try:
        # incidents.client_email isn't a cascading FK (kept as historical
        # record even after the account that created it is deleted, by
        # design) -- clean up this hardcoded id explicitly so a prior
        # run's leftover row can't collide with this one.
        await database.execute("DELETE FROM incidents WHERE id='mcp-free-slot-used'")
        await database.execute(
            """INSERT INTO incidents (id, client_email, title, severity, status, created_at, updated_at)
               VALUES ('mcp-free-slot-used', %s, 'Used elsewhere', 'sev3', 'open', 0, 0)""",
            (CLIENT_EMAIL,),
        )
        await database.execute(
            "UPDATE users SET free_incident_id='mcp-free-slot-used' WHERE email=%s", (CLIENT_EMAIL,)
        )
    finally:
        await database.close()

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


# ---------------------------------------------------------------------------
# Agent accountability: every MCP tool call now writes a durable row into
# account_activity_log (source='mcp_agent') -- the same real, queryable
# audit trail REST actions already wrote into, extended to answer "was
# this a human in the browser, or an agent acting on their account."
# ---------------------------------------------------------------------------


async def _activity_log_rows(client_email: str) -> list[dict]:
    from app.database import Database
    from app.settings import get_settings

    database = Database(get_settings())
    await database.open()
    try:
        return await database.fetch_all(
            "SELECT action, incident_id, detail, source FROM account_activity_log"
            " WHERE client_email=%s ORDER BY created_at ASC",
            (client_email,),
        )
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_a_successful_tool_call_is_recorded_with_source_mcp_agent(context) -> None:
    app, _founder_token, client_token = context
    async with mcp_session(app, token=client_token) as session:
        result = await session.call_tool("list_incidents", {})
    assert result.isError is not True

    rows = await _activity_log_rows(CLIENT_EMAIL)
    assert any(r["action"] == "agent_list_incidents" and r["source"] == "mcp_agent" for r in rows), rows


@pytest.mark.asyncio
async def test_a_denied_tool_call_is_also_recorded(context) -> None:
    """The actual authorization-layer half of accountability: a non-founder
    account calling a founder-only tool is blocked (proven elsewhere in
    this file), but until this feature, that blocked attempt left no
    trace anywhere queryable -- only successes were ever visible."""
    app, _founder_token, client_token = context
    async with mcp_session(app, token=client_token) as session:
        result = await session.call_tool("get_founder_summary", {})
    assert result.isError is True

    rows = await _activity_log_rows(CLIENT_EMAIL)
    denied = [r for r in rows if r["action"] == "agent_get_founder_summary_denied"]
    assert len(denied) == 1, rows
    assert denied[0]["source"] == "mcp_agent"
    assert "founder" in denied[0]["detail"].lower()


@pytest.mark.asyncio
async def test_create_incident_via_mcp_writes_exactly_one_row_not_two(context) -> None:
    """create_incident is one of the two tools whose shared REST route body
    already logs its own success -- proving here that MCP doesn't ALSO log
    a second, redundant row is what actually confirms the double-counting
    bug this design deliberately avoids, not just that logging happens at
    all (test_a_successful_tool_call_is_recorded... already covers that
    for an ordinary tool)."""
    app, founder_token, _client_token = context
    # The founder account is exempt from the subscription paywall (see
    # test_a_founder_can_create_and_list_their_own_incident_via_mcp), so
    # this exercises the success path without needing a real payment.
    async with mcp_session(app, token=founder_token) as session:
        result = await session.call_tool(
            "create_incident", {"title": "Accountability test incident", "severity": "sev3"}
        )
    assert result.isError is not True

    rows = await _activity_log_rows(FOUNDER_EMAIL)
    created = [r for r in rows if r["action"] == "incident_created"]
    assert len(created) == 1, rows
    assert created[0]["source"] == "mcp_agent"
    # And no second, generic "agent_create_incident" row alongside it.
    assert not any(r["action"] == "agent_create_incident" for r in rows), rows


@pytest.mark.asyncio
async def test_create_incident_denied_via_mcp_is_still_recorded(context) -> None:
    """The other half of the create_incident/publish_postmortem exception:
    success is self-logged by the REST route body, but a denial never
    reaches that body at all (require_mcp_active_subscription_or_free_slot
    raises first) -- so it must still go through the normal wrapper path,
    not be silently dropped just because the tool's happy path is
    self-logged elsewhere."""
    app, _founder_token, client_token = context
    # CLIENT_EMAIL has no subscription and the free-incident trial is
    # retired for new grants (see test_free_incident.py) -- genuinely
    # unpaid, the real case this is meant to catch.
    async with mcp_session(app, token=client_token) as session:
        result = await session.call_tool(
            "create_incident", {"title": "Should be denied", "severity": "sev3"}
        )
    assert result.isError is True

    rows = await _activity_log_rows(CLIENT_EMAIL)
    denied = [r for r in rows if r["action"] == "agent_create_incident_denied"]
    assert len(denied) == 1, rows
    assert denied[0]["source"] == "mcp_agent"
    assert not any(r["action"] == "incident_created" for r in rows), rows


@pytest.mark.asyncio
async def test_web_and_mcp_agent_actions_are_distinguishable_via_rest(context) -> None:
    """The actual point of all of this: GET /v1/postmortems/activity-log
    (the same endpoint the client's own dashboard already calls) can now
    tell the two apart, not just the raw database table."""
    app, founder_token, _client_token = context
    async with mcp_session(app, token=founder_token) as session:
        await session.call_tool("list_incidents", {})

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        login = await http.post(
            "/v1/auth/login", json={"email": FOUNDER_EMAIL, "password": "correct-horse-battery"}
        )
        assert login.status_code == 200, login.text
        response = await http.get("/v1/postmortems/activity-log")
        assert response.status_code == 200, response.text
        entries = response.json()

    assert any(e["action"] == "agent_list_incidents" and e["source"] == "mcp_agent" for e in entries), entries
