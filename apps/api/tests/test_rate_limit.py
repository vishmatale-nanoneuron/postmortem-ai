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


async def _record_failed_attempt(database, email: str, ip: str) -> None:
    """Sets up a precondition row directly -- same INSERT login_attempt_slot's
    own record() callback runs, but without going through the guard, so
    tests can arrange "N prior failures" without needing N successful,
    unlocked calls first."""
    import time

    await database.execute(
        "INSERT INTO login_attempts (email, ip, succeeded, created_at) VALUES (%s, %s, false, %s)",
        (email, ip, int(time.time() * 1000)),
    )


@pytest.mark.asyncio
async def test_not_rate_limited_with_no_prior_attempts(database) -> None:
    from app.security.rate_limit import login_attempt_slot

    async with login_attempt_slot(database, EMAIL, IP) as record:
        await record(False)


@pytest.mark.asyncio
async def test_locked_out_after_max_failed_attempts_for_one_email(database) -> None:
    from app.security.rate_limit import MAX_FAILED_ATTEMPTS_PER_EMAIL, LoginRateLimited, login_attempt_slot

    for i in range(MAX_FAILED_ATTEMPTS_PER_EMAIL):
        # Different IPs each time -- this must still lock out, because the
        # email-based limit is independent of source IP.
        await _record_failed_attempt(database, EMAIL, f"198.51.100.{i}")

    with pytest.raises(LoginRateLimited):
        async with login_attempt_slot(database, EMAIL, "198.51.100.99"):
            pass


@pytest.mark.asyncio
async def test_successful_attempts_never_count_toward_lockout(database) -> None:
    from app.security.rate_limit import MAX_FAILED_ATTEMPTS_PER_EMAIL, login_attempt_slot

    for _ in range(MAX_FAILED_ATTEMPTS_PER_EMAIL + 5):
        async with login_attempt_slot(database, EMAIL, IP) as record:
            await record(True)

    async with login_attempt_slot(database, EMAIL, IP) as record:
        await record(False)


@pytest.mark.asyncio
async def test_a_different_email_is_not_affected_by_another_emails_lockout(database) -> None:
    from app.security.rate_limit import MAX_FAILED_ATTEMPTS_PER_EMAIL, LoginRateLimited, login_attempt_slot

    for _ in range(MAX_FAILED_ATTEMPTS_PER_EMAIL):
        await _record_failed_attempt(database, EMAIL, IP)

    with pytest.raises(LoginRateLimited):
        async with login_attempt_slot(database, EMAIL, IP):
            pass

    async with login_attempt_slot(database, "someone-else@example.com", IP) as record:
        await record(False)


@pytest.mark.asyncio
async def test_locked_out_after_max_failed_attempts_from_one_ip_across_different_emails(database) -> None:
    from app.security.rate_limit import MAX_FAILED_ATTEMPTS_PER_IP, LoginRateLimited, login_attempt_slot

    for i in range(MAX_FAILED_ATTEMPTS_PER_IP):
        await _record_failed_attempt(database, f"target-{i}@example.com", IP)

    # A brand new email from the same IP should still be blocked -- this is
    # exactly the credential-stuffing pattern the per-IP bound exists for.
    with pytest.raises(LoginRateLimited):
        async with login_attempt_slot(database, "yet-another-new-email@example.com", IP):
            pass


@pytest.mark.asyncio
async def test_a_concurrent_login_burst_for_the_same_email_cannot_exceed_the_limit(database) -> None:
    # Regression for the exact race this module's own docstring describes:
    # is_login_rate_limited() (a SELECT) and record_login_attempt() (a
    # separate INSERT, after a real password check in between) used to be
    # two non-atomic operations -- a burst of concurrent login attempts for
    # the same email could all pass the check before any of their inserts
    # committed. Firing genuinely concurrent attempts (asyncio.gather)
    # against MAX_FAILED_ATTEMPTS_PER_EMAIL proves at most that many are
    # ever let through the guard, mirroring
    # test_a_concurrent_burst_cannot_exceed_the_limit below for the
    # generic action limiter.
    import asyncio

    from app.security.rate_limit import MAX_FAILED_ATTEMPTS_PER_EMAIL, LoginRateLimited, login_attempt_slot

    async def one_attempt() -> bool:
        try:
            async with login_attempt_slot(database, EMAIL, IP) as record:
                await record(False)
                return True
        except LoginRateLimited:
            return False

    results = await asyncio.gather(*[one_attempt() for _ in range(MAX_FAILED_ATTEMPTS_PER_EMAIL + 15)])
    assert sum(1 for allowed in results if allowed) == MAX_FAILED_ATTEMPTS_PER_EMAIL


@pytest_asyncio.fixture
async def action_user(database):
    # api_action_events.user_id has a real FK into users -- needs an
    # actual row, not just an arbitrary UUID.
    from app.security.passwords import hash_password

    row = await database.fetch_one(
        """INSERT INTO users (email, password_hash, created_at)
           VALUES (%s, %s, 0) ON CONFLICT (email) DO UPDATE SET email=excluded.email
           RETURNING id::text""",
        ("rate-limit-action-test@example.com", hash_password("unused-password-123")),
    )
    user_id = row["id"]
    await database.execute("DELETE FROM api_action_events WHERE user_id=%s", (user_id,))
    yield user_id
    await database.execute("DELETE FROM api_action_events WHERE user_id=%s", (user_id,))
    await database.execute("DELETE FROM users WHERE id=%s", (user_id,))


@pytest.mark.asyncio
async def test_action_rate_limiting_is_not_limited_below_the_threshold(database, action_user) -> None:
    from app.security.rate_limit import try_record_action

    for _ in range(3):
        assert await try_record_action(database, action_user, "draft_postmortem", max_per_window=5, window_ms=60_000)


@pytest.mark.asyncio
async def test_action_rate_limiting_trips_at_the_threshold(database, action_user) -> None:
    from app.security.rate_limit import try_record_action

    for _ in range(5):
        assert await try_record_action(database, action_user, "draft_postmortem", max_per_window=5, window_ms=60_000)
    assert not await try_record_action(database, action_user, "draft_postmortem", max_per_window=5, window_ms=60_000)


@pytest.mark.asyncio
async def test_action_rate_limiting_is_scoped_per_action(database, action_user) -> None:
    # Hitting the limit on one action must not block a different action
    # for the same account.
    from app.security.rate_limit import try_record_action

    for _ in range(5):
        assert await try_record_action(database, action_user, "draft_postmortem", max_per_window=5, window_ms=60_000)
    assert not await try_record_action(database, action_user, "draft_postmortem", max_per_window=5, window_ms=60_000)
    assert await try_record_action(database, action_user, "create_incident", max_per_window=5, window_ms=60_000)


@pytest.mark.asyncio
async def test_a_concurrent_burst_cannot_exceed_the_limit(database, action_user) -> None:
    # Regression for a real TOCTOU race: the old is_action_rate_limited() +
    # record_action() pair were two separate queries, so a burst of
    # concurrent callers could all pass the check before any of their
    # inserts committed, letting the burst blow past max_per_window. Firing
    # genuinely concurrent calls (asyncio.gather) against a limit of 5
    # proves at most 5 of 20 concurrent attempts are ever allowed through.
    import asyncio

    from app.security.rate_limit import try_record_action

    results = await asyncio.gather(
        *[
            try_record_action(database, action_user, "draft_postmortem", max_per_window=5, window_ms=60_000)
            for _ in range(20)
        ]
    )
    assert sum(1 for allowed in results if allowed) == 5
