"""End-to-end rate-limit tests against a real PostgreSQL instance.

Skipped unless TEST_DATABASE_URL is set, matching the rest of this suite.
"""

import os

import pytest
import pytest_asyncio

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not configured")

EMAIL = "rate-limit-test@example.com"
IP = "203.0.113.5"


@pytest_asyncio.fixture
async def database(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL or "")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-used")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("COOKIE_SECURE", "false")

    from app.database import Database
    from app.settings import get_settings

    get_settings.cache_clear()
    db = Database(get_settings())
    await db.open()
    await db.execute("DELETE FROM login_attempts WHERE email=%s OR ip=%s", (EMAIL, IP))
    yield db
    await db.close()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_not_rate_limited_with_no_prior_attempts(database) -> None:
    from app.security.rate_limit import is_login_rate_limited

    assert not await is_login_rate_limited(database, EMAIL, IP)


@pytest.mark.asyncio
async def test_locked_out_after_max_failed_attempts_for_one_email(database) -> None:
    from app.security.rate_limit import (
        MAX_FAILED_ATTEMPTS_PER_EMAIL,
        is_login_rate_limited,
        record_login_attempt,
    )

    for i in range(MAX_FAILED_ATTEMPTS_PER_EMAIL):
        # Different IPs each time -- this must still lock out, because the
        # email-based limit is independent of source IP.
        await record_login_attempt(database, EMAIL, f"198.51.100.{i}", succeeded=False)

    assert await is_login_rate_limited(database, EMAIL, "198.51.100.99")


@pytest.mark.asyncio
async def test_successful_attempts_never_count_toward_lockout(database) -> None:
    from app.security.rate_limit import MAX_FAILED_ATTEMPTS_PER_EMAIL, is_login_rate_limited, record_login_attempt

    for _ in range(MAX_FAILED_ATTEMPTS_PER_EMAIL + 5):
        await record_login_attempt(database, EMAIL, IP, succeeded=True)

    assert not await is_login_rate_limited(database, EMAIL, IP)


@pytest.mark.asyncio
async def test_a_different_email_is_not_affected_by_another_emails_lockout(database) -> None:
    from app.security.rate_limit import MAX_FAILED_ATTEMPTS_PER_EMAIL, is_login_rate_limited, record_login_attempt

    for _ in range(MAX_FAILED_ATTEMPTS_PER_EMAIL):
        await record_login_attempt(database, EMAIL, IP, succeeded=False)

    assert await is_login_rate_limited(database, EMAIL, IP)
    assert not await is_login_rate_limited(database, "someone-else@example.com", IP)


@pytest.mark.asyncio
async def test_locked_out_after_max_failed_attempts_from_one_ip_across_different_emails(database) -> None:
    from app.security.rate_limit import MAX_FAILED_ATTEMPTS_PER_IP, is_login_rate_limited, record_login_attempt

    for i in range(MAX_FAILED_ATTEMPTS_PER_IP):
        await record_login_attempt(database, f"target-{i}@example.com", IP, succeeded=False)

    # A brand new email from the same IP should still be blocked -- this is
    # exactly the credential-stuffing pattern the per-IP bound exists for.
    assert await is_login_rate_limited(database, "yet-another-new-email@example.com", IP)
