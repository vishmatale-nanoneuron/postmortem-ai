"""Password reset: request always 202s (never reveals whether the email
belongs to a real account), the token is single-use (fingerprinted against
the CURRENT password_hash, not a separately tracked "used" flag), and a
tampered/expired/reused token is rejected. Real end-to-end against
Postgres; the actual Resend API call is replaced with a fake that records
what it would have sent, so these tests need no real RESEND_API_KEY and
send no real email.
"""

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not configured")

CLIENT_EMAIL = "password-reset-test@example.com"


@pytest_asyncio.fixture
async def context(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL or "")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-used")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("RESEND_API_KEY", "test-key-not-used")
    monkeypatch.setenv("RESEND_EMAIL_DOMAIN", "test.example.com")

    from app.database import Database
    from app.main import create_app
    from app.settings import get_settings

    sent: list[dict] = []

    def fake_send(settings, to_email, reset_url):
        sent.append({"to": to_email, "reset_url": reset_url})

    monkeypatch.setattr("app.api.v1.auth.send_password_reset_email", fake_send)

    get_settings.cache_clear()
    database = Database(get_settings())
    await database.open()
    await database.execute("DELETE FROM users WHERE email=%s", (CLIENT_EMAIL,))
    await database.execute("DELETE FROM password_reset_attempts")

    application = create_app()
    application.state.database = database

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        register = await client.post("/v1/auth/register", json={"email": CLIENT_EMAIL, "password": "original-password"})
        assert register.status_code == 201, register.text
        yield client, database, sent

    await database.close()
    get_settings.cache_clear()


def _extract_token(reset_url: str) -> str:
    return reset_url.split("token=", 1)[1]


@pytest.mark.asyncio
async def test_requesting_a_reset_for_a_real_account_sends_an_email(context) -> None:
    client, _, sent = context
    response = await client.post("/v1/auth/password-reset/request", json={"email": CLIENT_EMAIL})
    assert response.status_code == 202, response.text
    assert len(sent) == 1
    assert sent[0]["to"] == CLIENT_EMAIL
    assert "token=" in sent[0]["reset_url"]


@pytest.mark.asyncio
async def test_requesting_a_reset_for_an_unknown_email_still_returns_202(context) -> None:
    # Never reveal whether an email is registered -- same reasoning as
    # login's identical failure message for wrong-password vs. unknown-email.
    client, _, sent = context
    response = await client.post("/v1/auth/password-reset/request", json={"email": "no-such-account@example.com"})
    assert response.status_code == 202, response.text
    assert len(sent) == 0


@pytest.mark.asyncio
async def test_a_valid_token_actually_changes_the_password(context) -> None:
    client, _, sent = context
    await client.post("/v1/auth/password-reset/request", json={"email": CLIENT_EMAIL})
    token = _extract_token(sent[0]["reset_url"])

    confirm = await client.post("/v1/auth/password-reset/confirm", json={"token": token, "new_password": "brand-new-password"})
    assert confirm.status_code == 200, confirm.text

    # Old password no longer works; new one does.
    old_login = await client.post("/v1/auth/login", json={"email": CLIENT_EMAIL, "password": "original-password"})
    assert old_login.status_code == 401
    new_login = await client.post("/v1/auth/login", json={"email": CLIENT_EMAIL, "password": "brand-new-password"})
    assert new_login.status_code == 200, new_login.text


@pytest.mark.asyncio
async def test_a_token_cannot_be_used_twice(context) -> None:
    client, _, sent = context
    await client.post("/v1/auth/password-reset/request", json={"email": CLIENT_EMAIL})
    token = _extract_token(sent[0]["reset_url"])

    first = await client.post("/v1/auth/password-reset/confirm", json={"token": token, "new_password": "first-new-password"})
    assert first.status_code == 200, first.text

    second = await client.post("/v1/auth/password-reset/confirm", json={"token": token, "new_password": "second-new-password"})
    assert second.status_code == 400


@pytest.mark.asyncio
async def test_a_garbage_token_is_rejected(context) -> None:
    client, _, _ = context
    response = await client.post(
        "/v1/auth/password-reset/confirm", json={"token": "not-a-real-token", "new_password": "whatever-password"}
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_a_session_token_cannot_be_used_as_a_password_reset_token(context) -> None:
    # The purpose claim must be checked -- a leaked/logged session cookie
    # (a real JWT, correctly signed) must never double as a password-reset
    # grant just because it's a valid token for the same secret.
    client, _, _ = context
    login = await client.post("/v1/auth/login", json={"email": CLIENT_EMAIL, "password": "original-password"})
    session_cookie = login.cookies.get("session_token")
    assert session_cookie is not None

    response = await client.post(
        "/v1/auth/password-reset/confirm", json={"token": session_cookie, "new_password": "should-not-work"}
    )
    assert response.status_code == 400
