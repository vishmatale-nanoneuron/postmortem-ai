"""End-to-end auth tests against a real PostgreSQL instance.

Skipped unless TEST_DATABASE_URL is set, matching the rest of this suite.
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
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("COOKIE_SECURE", "false")

    from app.database import Database
    from app.main import create_app
    from app.settings import get_settings

    get_settings.cache_clear()
    database = Database(get_settings())
    await database.open()
    await database.execute("DELETE FROM users WHERE email LIKE %s", ("auth-test-%",))

    application = create_app()
    application.state.database = database

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        yield client, database

    await database.close()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_register_then_me_reflects_the_new_user(context) -> None:
    client, _ = context
    response = await client.post(
        "/v1/auth/register", json={"email": "auth-test-1@example.com", "password": "correct-horse-battery"}
    )
    assert response.status_code == 201, response.text
    assert response.json()["email"] == "auth-test-1@example.com"
    assert "session_token" in response.cookies

    me = await client.get("/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "auth-test-1@example.com"


@pytest.mark.asyncio
async def test_registering_the_same_email_twice_is_a_conflict(context) -> None:
    client, _ = context
    await client.post(
        "/v1/auth/register", json={"email": "auth-test-2@example.com", "password": "correct-horse-battery"}
    )
    response = await client.post(
        "/v1/auth/register", json={"email": "auth-test-2@example.com", "password": "a-different-password"}
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_login_with_correct_password_succeeds(context) -> None:
    client, _ = context
    await client.post(
        "/v1/auth/register", json={"email": "auth-test-3@example.com", "password": "correct-horse-battery"}
    )
    client.cookies.clear()
    response = await client.post(
        "/v1/auth/login", json={"email": "auth-test-3@example.com", "password": "correct-horse-battery"}
    )
    assert response.status_code == 200
    assert "session_token" in response.cookies


@pytest.mark.asyncio
async def test_login_with_wrong_password_is_rejected_with_a_generic_message(context) -> None:
    client, _ = context
    await client.post(
        "/v1/auth/register", json={"email": "auth-test-4@example.com", "password": "correct-horse-battery"}
    )
    client.cookies.clear()
    response = await client.post(
        "/v1/auth/login", json={"email": "auth-test-4@example.com", "password": "wrong-password"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect email or password"


@pytest.mark.asyncio
async def test_login_with_an_unregistered_email_gets_the_same_generic_message(context) -> None:
    # Wrong email and wrong password must be indistinguishable to the
    # caller -- otherwise a failed login attempt could be used to enumerate
    # which emails are registered.
    client, _ = context
    response = await client.post(
        "/v1/auth/login", json={"email": "auth-test-never-registered@example.com", "password": "anything"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect email or password"


@pytest.mark.asyncio
async def test_me_without_a_session_cookie_is_unauthorized(context) -> None:
    client, _ = context
    response = await client.get("/v1/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_logout_clears_the_session(context) -> None:
    client, _ = context
    await client.post(
        "/v1/auth/register", json={"email": "auth-test-5@example.com", "password": "correct-horse-battery"}
    )
    logout_response = await client.post("/v1/auth/logout")
    assert logout_response.status_code == 200
    client.cookies.clear()
    me = await client.get("/v1/auth/me")
    assert me.status_code == 401
