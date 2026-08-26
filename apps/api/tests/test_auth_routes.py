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
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-used")
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
async def test_email_case_is_normalized_so_a_case_variant_cannot_double_register(context) -> None:
    # Real bug this guards against: "User@Example.com" and
    # "user@example.com" previously registered as two separate accounts
    # sharing the same real inbox.
    client, database = context
    await database.execute("DELETE FROM users WHERE email=%s", ("auth-test-case@example.com",))

    first = await client.post(
        "/v1/auth/register", json={"email": "Auth-Test-Case@Example.com", "password": "correct-horse-battery"}
    )
    assert first.status_code == 201, first.text
    assert first.json()["email"] == "auth-test-case@example.com"

    conflict = await client.post(
        "/v1/auth/register", json={"email": "AUTH-TEST-CASE@EXAMPLE.COM", "password": "a-different-password"}
    )
    assert conflict.status_code == 409


@pytest.mark.asyncio
async def test_login_email_case_is_normalized_too(context) -> None:
    client, database = context
    await database.execute("DELETE FROM users WHERE email=%s", ("auth-test-login-case@example.com",))
    await client.post(
        "/v1/auth/register", json={"email": "auth-test-login-case@example.com", "password": "correct-horse-battery"}
    )
    client.cookies.clear()

    response = await client.post(
        "/v1/auth/login", json={"email": "Auth-Test-Login-Case@Example.com", "password": "correct-horse-battery"}
    )
    assert response.status_code == 200, response.text


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
async def test_login_is_rate_limited_after_repeated_failures(context) -> None:
    from app.security.rate_limit import MAX_FAILED_ATTEMPTS_PER_EMAIL

    client, database = context
    email = "auth-test-ratelimit@example.com"
    await client.post("/v1/auth/register", json={"email": email, "password": "correct-horse-battery"})
    client.cookies.clear()
    await database.execute("DELETE FROM login_attempts WHERE email=%s", (email,))

    for _ in range(MAX_FAILED_ATTEMPTS_PER_EMAIL):
        response = await client.post("/v1/auth/login", json={"email": email, "password": "wrong-password"})
        assert response.status_code == 401

    # One more attempt -- even with the CORRECT password -- must now be
    # rejected as rate limited, not allowed through.
    locked_out = await client.post("/v1/auth/login", json={"email": email, "password": "correct-horse-battery"})
    assert locked_out.status_code == 429


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


@pytest.mark.asyncio
async def test_patch_me_updates_only_the_supplied_field(context) -> None:
    client, _ = context
    await client.post(
        "/v1/auth/register", json={"email": "auth-test-patch-1@example.com", "password": "correct-horse-battery"}
    )
    response = await client.patch("/v1/auth/me", json={"email": "auth-test-patch-1-renamed@example.com"})
    assert response.status_code == 200, response.text
    assert response.json()["email"] == "auth-test-patch-1-renamed@example.com"

    # Old password still works against the renamed account -- PATCH with
    # only email must not have touched the password.
    client.cookies.clear()
    login = await client.post(
        "/v1/auth/login",
        json={"email": "auth-test-patch-1-renamed@example.com", "password": "correct-horse-battery"},
    )
    assert login.status_code == 200, login.text


@pytest.mark.asyncio
async def test_patch_me_with_no_fields_is_rejected(context) -> None:
    client, _ = context
    await client.post(
        "/v1/auth/register", json={"email": "auth-test-patch-2@example.com", "password": "correct-horse-battery"}
    )
    response = await client.patch("/v1/auth/me", json={})
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_put_me_requires_both_fields_and_replaces_password(context) -> None:
    client, _ = context
    await client.post(
        "/v1/auth/register", json={"email": "auth-test-put-1@example.com", "password": "correct-horse-battery"}
    )
    response = await client.put(
        "/v1/auth/me", json={"email": "auth-test-put-1@example.com", "password": "a-brand-new-password"}
    )
    assert response.status_code == 200, response.text

    client.cookies.clear()
    old_login = await client.post(
        "/v1/auth/login", json={"email": "auth-test-put-1@example.com", "password": "correct-horse-battery"}
    )
    assert old_login.status_code == 401

    new_login = await client.post(
        "/v1/auth/login", json={"email": "auth-test-put-1@example.com", "password": "a-brand-new-password"}
    )
    assert new_login.status_code == 200


@pytest.mark.asyncio
async def test_updating_to_an_email_already_taken_is_a_conflict(context) -> None:
    client, _ = context
    await client.post(
        "/v1/auth/register", json={"email": "auth-test-conflict-a@example.com", "password": "correct-horse-battery"}
    )
    client.cookies.clear()
    await client.post(
        "/v1/auth/register", json={"email": "auth-test-conflict-b@example.com", "password": "correct-horse-battery"}
    )
    response = await client.patch("/v1/auth/me", json={"email": "auth-test-conflict-a@example.com"})
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_the_founder_account_cannot_reassign_its_own_email(context, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FOUNDER_EMAIL", "auth-test-founder@example.com")
    from app.settings import get_settings

    get_settings.cache_clear()
    client, _ = context
    register = await client.post(
        "/v1/auth/register", json={"email": "auth-test-founder@example.com", "password": "correct-horse-battery"}
    )
    assert register.json()["is_founder"] is True

    response = await client.patch("/v1/auth/me", json={"email": "auth-test-founder-new@example.com"})
    assert response.status_code == 403
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_a_non_founder_account_cannot_rename_itself_into_the_founder_email(
    context, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FOUNDER_EMAIL", "auth-test-founder-2@example.com")
    from app.settings import get_settings

    get_settings.cache_clear()
    client, _ = context
    await client.post(
        "/v1/auth/register", json={"email": "auth-test-not-founder@example.com", "password": "correct-horse-battery"}
    )
    response = await client.patch("/v1/auth/me", json={"email": "auth-test-founder-2@example.com"})
    assert response.status_code == 403
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_delete_me_removes_the_account_and_clears_the_session(context) -> None:
    client, database = context
    await client.post(
        "/v1/auth/register", json={"email": "auth-test-delete-1@example.com", "password": "correct-horse-battery"}
    )
    response = await client.delete("/v1/auth/me")
    assert response.status_code == 204

    me = await client.get("/v1/auth/me")
    assert me.status_code == 401

    row = await database.fetch_one("SELECT id FROM users WHERE email=%s", ("auth-test-delete-1@example.com",))
    assert row is None


@pytest.mark.asyncio
async def test_the_founder_account_cannot_delete_itself(context, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FOUNDER_EMAIL", "auth-test-founder-3@example.com")
    from app.settings import get_settings

    get_settings.cache_clear()
    client, database = context
    await client.post(
        "/v1/auth/register", json={"email": "auth-test-founder-3@example.com", "password": "correct-horse-battery"}
    )
    response = await client.delete("/v1/auth/me")
    assert response.status_code == 403

    row = await database.fetch_one("SELECT id FROM users WHERE email=%s", ("auth-test-founder-3@example.com",))
    assert row is not None
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_registration_is_rate_limited_per_ip(context) -> None:
    # Regression for a real gap: registration is free and instant (no
    # email verification, no KYC) -- it was the only thing standing between
    # "anyone on the internet" and billing/upi/info + billing/wire/info
    # (which require a signed-in caller, but any account qualifies). This
    # is the deployed-by-default defense against mass throwaway-account
    # creation; CAPTCHA (security/captcha.py) is the stronger one but is
    # optional/unconfigured until a real Cloudflare key is set.
    client, _ = context
    for i in range(5):
        response = await client.post(
            "/v1/auth/register",
            json={"email": f"auth-test-rate-limit-{i}@example.com", "password": "correct-horse-battery"},
        )
        assert response.status_code == 201, response.text
        client.cookies.clear()

    blocked = await client.post(
        "/v1/auth/register",
        json={"email": "auth-test-rate-limit-6th@example.com", "password": "correct-horse-battery"},
    )
    assert blocked.status_code == 429
