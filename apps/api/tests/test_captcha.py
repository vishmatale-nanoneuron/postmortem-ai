"""Cloudflare Turnstile verification -- pure unit tests (no real network
call, no database) plus a route-level check that register/login actually
enforce it once configured.
"""

import os

import httpx
import pytest
import pytest_asyncio
from app.security.captcha import verify_turnstile
from httpx import ASGITransport, AsyncClient

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.mark.asyncio
async def test_unconfigured_captcha_always_passes() -> None:
    assert await verify_turnstile(None, None) is True
    assert await verify_turnstile(None, "any-token-or-none") is True


@pytest.mark.asyncio
async def test_configured_captcha_rejects_a_missing_token() -> None:
    assert await verify_turnstile("real-secret", None) is False


@pytest.mark.asyncio
async def test_configured_captcha_accepts_a_successful_verification(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_post(self, url, data=None, **kwargs):
        assert data["secret"] == "real-secret"
        assert data["response"] == "a-real-token"
        return httpx.Response(200, json={"success": True}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    assert await verify_turnstile("real-secret", "a-real-token") is True


@pytest.mark.asyncio
async def test_configured_captcha_rejects_a_failed_verification(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_post(self, url, data=None, **kwargs):
        return httpx.Response(200, json={"success": False, "error-codes": ["invalid-input-response"]}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    assert await verify_turnstile("real-secret", "a-bad-token") is False


@pytest.mark.asyncio
async def test_configured_captcha_fails_closed_when_cloudflare_is_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_post(self, url, data=None, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    # Fails CLOSED (returns False), not open -- an unreachable Cloudflare
    # must never be indistinguishable from "verification passed."
    assert await verify_turnstile("real-secret", "a-real-token") is False


@pytest_asyncio.fixture
async def captcha_context(monkeypatch: pytest.MonkeyPatch):
    if not DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is not configured")
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-used")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("TURNSTILE_SITE_KEY", "test-site-key")
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "test-secret-key")

    # Patching httpx.AsyncClient.post globally would also intercept the
    # test's OWN outer client (which routes to the app via ASGITransport,
    # not a real socket) -- only fake the Turnstile verify call
    # specifically, and delegate everything else to the real method.
    real_post = httpx.AsyncClient.post

    async def fake_post(self, url, data=None, **kwargs):
        if str(url) == "https://challenges.cloudflare.com/turnstile/v0/siteverify":
            success = (data or {}).get("response") == "valid-token"
            return httpx.Response(200, json={"success": success}, request=httpx.Request("POST", url))
        return await real_post(self, url, data=data, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    from app.database import Database
    from app.main import create_app
    from app.settings import get_settings

    get_settings.cache_clear()
    database = Database(get_settings())
    await database.open()
    await database.execute("DELETE FROM users WHERE email LIKE %s", ("captcha-test-%",))

    application = create_app()
    application.state.database = database

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        yield client

    await database.close()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_captcha_config_reflects_settings(captcha_context) -> None:
    response = await captcha_context.get("/v1/auth/captcha-config")
    assert response.status_code == 200
    assert response.json() == {"enabled": True, "site_key": "test-site-key"}


@pytest.mark.asyncio
async def test_registration_is_blocked_without_a_valid_captcha_token(captcha_context) -> None:
    response = await captcha_context.post(
        "/v1/auth/register", json={"email": "captcha-test-1@example.com", "password": "correct-horse-battery"}
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_registration_succeeds_with_a_valid_captcha_token(captcha_context) -> None:
    response = await captcha_context.post(
        "/v1/auth/register",
        json={
            "email": "captcha-test-2@example.com",
            "password": "correct-horse-battery",
            "captcha_token": "valid-token",
        },
    )
    assert response.status_code == 201, response.text
