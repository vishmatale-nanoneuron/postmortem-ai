"""Founder gate + dashboard, end-to-end against a real PostgreSQL instance.

Skipped unless TEST_DATABASE_URL is set, matching the rest of this suite.
"""

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not configured")

FOUNDER_EMAIL = "founder-test@example.com"


@pytest_asyncio.fixture
async def context(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL or "")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-used")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("FOUNDER_EMAIL", FOUNDER_EMAIL)

    from app.database import Database
    from app.main import create_app
    from app.settings import get_settings

    get_settings.cache_clear()
    database = Database(get_settings())
    await database.open()
    await database.execute("DELETE FROM users WHERE email LIKE %s", ("founder-test-%",))
    await database.execute("DELETE FROM users WHERE email=%s", (FOUNDER_EMAIL,))

    application = create_app()
    application.state.database = database

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        yield client, database

    await database.close()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_registering_with_the_founder_email_is_flagged_founder(context) -> None:
    client, _ = context
    response = await client.post(
        "/v1/auth/register", json={"email": FOUNDER_EMAIL, "password": "correct-horse-battery"}
    )
    assert response.status_code == 201, response.text
    assert response.json()["is_founder"] is True

    me = await client.get("/v1/auth/me")
    assert me.json()["is_founder"] is True


@pytest.mark.asyncio
async def test_a_non_founder_account_is_not_flagged_and_cannot_reach_the_founder_summary(context) -> None:
    client, _ = context
    await client.post(
        "/v1/auth/register", json={"email": "founder-test-regular@example.com", "password": "correct-horse-battery"}
    )
    me = await client.get("/v1/auth/me")
    assert me.json()["is_founder"] is False

    summary = await client.get("/v1/founder/summary")
    assert summary.status_code == 403


@pytest.mark.asyncio
async def test_the_founder_summary_reports_real_platform_aggregates(context) -> None:
    client, _ = context
    await client.post("/v1/auth/register", json={"email": FOUNDER_EMAIL, "password": "correct-horse-battery"})

    incident = await client.post(
        "/v1/postmortems/incidents", json={"title": "Founder-visible incident", "severity": "sev2"}
    )
    assert incident.status_code == 201

    summary = await client.get("/v1/founder/summary")
    assert summary.status_code == 200
    body = summary.json()
    assert body["total_users"] >= 1
    assert body["total_incidents"] >= 1
    assert body["open_incidents"] >= 1
    assert any(u["email"] == FOUNDER_EMAIL for u in body["recent_users"])


@pytest.mark.asyncio
async def test_a_founder_summary_call_without_a_session_is_unauthorized(context) -> None:
    client, _ = context
    response = await client.get("/v1/founder/summary")
    assert response.status_code == 401
