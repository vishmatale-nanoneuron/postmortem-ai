"""The purchase-reminder cron: the one automated purchase nudge in the app.

An account that signed up at least a day ago and has never paid for
anything gets exactly one email, ever. Pinned here: the secret gate, the
one-send-ever guarantee across runs, the age floor, and every exclusion
(a payment claim in any state, Airlock credits ever bought or granted, an
active subscription, the founder's own account).
"""

import os
import time

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not configured")

CRON_SECRET = "test-cron-secret"
FOUNDER_EMAIL = "cron-test-founder@example.com"
DAY_MS = 24 * 60 * 60 * 1000
CRON_PATH = "/v1/internal/cron/purchase-reminder"


@pytest_asyncio.fixture
async def context(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL or "")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-used")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-0123456789abcdef0123")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("RESEND_API_KEY", "test-key-not-used")
    monkeypatch.setenv("RESEND_EMAIL_DOMAIN", "test.example.com")
    monkeypatch.setenv("CRON_SECRET", CRON_SECRET)
    monkeypatch.setenv("FOUNDER_EMAIL", FOUNDER_EMAIL)

    from app.database import Database
    from app.main import create_app
    from app.settings import get_settings

    sent: list[dict] = []

    def fake_send(settings, to_email, user_id, *, days_since_signup):
        sent.append({"to": to_email, "user_id": user_id, "days": days_since_signup})

    monkeypatch.setattr("app.api.v1.internal.send_purchase_reminder_email", fake_send)

    get_settings.cache_clear()
    database = Database(get_settings())
    await database.open()
    await database.execute("DELETE FROM users WHERE email LIKE %s", ("cron-test-%",))

    application = create_app()
    application.state.database = database

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        yield client, database, sent

    await database.close()
    get_settings.cache_clear()


async def _register(client: AsyncClient, database, email: str, *, age_ms: int) -> str:
    """Registers and backdates the account so it looks `age_ms` old."""
    register = await client.post("/v1/auth/register", json={"email": email, "password": "correct-horse-battery"})
    assert register.status_code == 201, register.text
    user_id = register.json()["id"]
    # One test registers six accounts from one address; the per-IP
    # registration limiter (5/hour) is a real guard, not the thing under
    # test here.
    await database.execute("DELETE FROM registration_attempts")
    await database.execute(
        "UPDATE users SET created_at=%s WHERE id=%s", (int(time.time() * 1000) - age_ms, user_id)
    )
    await client.post("/v1/auth/logout")
    client.cookies.clear()
    return user_id


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {CRON_SECRET}"}


@pytest.mark.asyncio
async def test_the_cron_endpoint_requires_the_real_secret(context) -> None:
    client, _, sent = context
    assert (await client.post(CRON_PATH)).status_code == 401
    assert (await client.post(CRON_PATH, headers={"Authorization": "Bearer wrong-secret"})).status_code == 401
    assert sent == []


@pytest.mark.asyncio
async def test_reminds_an_eligible_account_exactly_once_ever(context) -> None:
    client, database, sent = context
    user_id = await _register(client, database, "cron-test-eligible@example.com", age_ms=3 * DAY_MS + 1000)

    first = await client.post(CRON_PATH, headers=_headers())
    assert first.status_code == 200, first.text
    assert first.json() == {"candidates_found": 1, "emails_sent": 1, "emails_failed": 0}
    assert sent == [{"to": "cron-test-eligible@example.com", "user_id": user_id, "days": 3}]

    # A second run must not re-send: the sent mark is set on success and
    # checked in the candidate query, so a retry of the same run, or the
    # next day's run, finds nobody.
    second = await client.post(CRON_PATH, headers=_headers())
    assert second.json() == {"candidates_found": 0, "emails_sent": 0, "emails_failed": 0}
    assert len(sent) == 1
    row = await database.fetch_one("SELECT free_incident_reminder_sent_at FROM users WHERE id=%s", (user_id,))
    assert row["free_incident_reminder_sent_at"] is not None


@pytest.mark.asyncio
async def test_does_not_remind_an_account_younger_than_a_day(context) -> None:
    client, database, sent = context
    await _register(client, database, "cron-test-too-recent@example.com", age_ms=60 * 60 * 1000)
    run = await client.post(CRON_PATH, headers=_headers())
    assert run.json()["candidates_found"] == 0
    assert sent == []


@pytest.mark.asyncio
async def test_does_not_remind_anyone_who_has_paid_or_is_paying_or_owns_the_place(context) -> None:
    """Every exclusion in one place. Each of these accounts is old enough
    and unsubscribed; each has a reason the email would be wrong."""
    from app.cqrs.airlock_billing import GrantCreditsCommand, handle_grant_credits

    client, database, sent = context
    old = 2 * DAY_MS

    # 1. Subscribed (manually approved UPI/wire subscription).
    subscribed = await _register(client, database, "cron-test-subscribed@example.com", age_ms=old)
    await database.execute(
        "UPDATE users SET subscription_status='active', current_period_end=%s WHERE id=%s",
        (int(time.time() / 1000) + 30 * 24 * 3600, subscribed),
    )

    # 2. A payment claim in flight (pending) -- they have paid and are
    #    waiting on the founder; nudging them now would be insulting.
    claimant = await _register(client, database, "cron-test-claimant@example.com", age_ms=old)
    await database.execute(
        """INSERT INTO payment_claims (user_id, method, currency, amount_inr, reference, status, created_at, billing_period, product)
           VALUES (%s, 'upi', 'INR', 999, 'UPI-REF-123456', 'pending', %s, 'monthly', 'postmortem')""",
        (claimant, int(time.time() * 1000)),
    )

    # 3. A rejected claim still counts as "has tried to pay": a human is
    #    already in the loop with them.
    rejected = await _register(client, database, "cron-test-rejected@example.com", age_ms=old)
    await database.execute(
        """INSERT INTO payment_claims (user_id, method, currency, amount_inr, reference, status, created_at, billing_period, product)
           VALUES (%s, 'wire', 'USD', 12, 'WIRE-REF-123456', 'rejected', %s, 'monthly', 'postmortem')""",
        (rejected, int(time.time() * 1000)),
    )

    # 4. Airlock credits granted by the founder (or bought) -- a customer.
    airlock = await _register(client, database, "cron-test-airlock@example.com", age_ms=old)
    await handle_grant_credits(database, GrantCreditsCommand(user_id=airlock, credits=100, reason="grant", reference="t"))

    # 5. The founder's own account.
    await _register(client, database, FOUNDER_EMAIL, age_ms=old)

    # 6. And one genuinely eligible account, to prove the run itself works.
    eligible = await _register(client, database, "cron-test-only-me@example.com", age_ms=old)

    run = await client.post(CRON_PATH, headers=_headers())
    assert run.status_code == 200, run.text
    assert run.json() == {"candidates_found": 1, "emails_sent": 1, "emails_failed": 0}
    assert [s["user_id"] for s in sent] == [eligible]


@pytest.mark.asyncio
async def test_a_failed_send_is_counted_and_retried_next_run(context, monkeypatch: pytest.MonkeyPatch) -> None:
    client, database, sent = context
    user_id = await _register(client, database, "cron-test-flaky@example.com", age_ms=2 * DAY_MS)

    calls = {"n": 0}

    def flaky(settings, to_email, user_id, *, days_since_signup):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("provider hiccup")
        sent.append({"to": to_email, "user_id": user_id, "days": days_since_signup})

    monkeypatch.setattr("app.api.v1.internal.send_purchase_reminder_email", flaky)
    first = await client.post(CRON_PATH, headers=_headers())
    assert first.json() == {"candidates_found": 1, "emails_sent": 0, "emails_failed": 1}
    row = await database.fetch_one("SELECT free_incident_reminder_sent_at FROM users WHERE id=%s", (user_id,))
    assert row["free_incident_reminder_sent_at"] is None, "not marked sent: it was not"

    second = await client.post(CRON_PATH, headers=_headers())
    assert second.json() == {"candidates_found": 1, "emails_sent": 1, "emails_failed": 0}
    assert [s["user_id"] for s in sent] == [user_id]
