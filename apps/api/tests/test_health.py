"""/health is a real database round-trip, not a static {"status": "ok"} --
that static version would have kept reporting healthy straight through
this project's own real db() outage (see CLAUDE.md's "Resolved: db()
site-wide outage"), where the database was unreachable while every other
route 500'd. A status page can only be honest if this check actually
proves the thing it claims.
"""

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not configured")


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

    application = create_app()
    application.state.database = database

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        yield client, database

    await database.close()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_health_reports_ok_when_the_database_is_actually_reachable(context) -> None:
    client, _ = context
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "reachable"


@pytest.mark.asyncio
async def test_health_reports_degraded_when_the_database_query_fails(context) -> None:
    client, database = context
    # Close the real connection out from under the running app -- the
    # simplest way to force a real query failure without mocking anything,
    # so this proves the actual round-trip, not a stubbed-out check.
    await database.close()
    response = await client.get("/health")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"] == "unreachable"
