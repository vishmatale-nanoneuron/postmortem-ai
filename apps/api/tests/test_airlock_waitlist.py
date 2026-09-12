"""Airlock's early-access list.

Three properties, all of which are the reason the endpoint is shaped the
way it is rather than as a plain INSERT:

- A duplicate address answers exactly like a new one (202, one row), so the
  response cannot be used to test who is on the list -- the same
  enumeration reasoning as password reset.
- Reading the list is founder-only. It is a list of prospects' email
  addresses; a client session must not reach it.
- The per-IP limit holds, so one source cannot fill the list.

Real end-to-end against Postgres, no mocks -- the ON CONFLICT and the
unique index on lower(email) are the actual mechanism and only a real
database proves them.
"""

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not configured")

FOUNDER_EMAIL = "airlock-founder@example.com"
CLIENT_EMAIL = "airlock-client@example.com"
WAITLIST_EMAIL = "airlock-prospect@example.com"


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
    await database.execute(
        "DELETE FROM airlock_waitlist WHERE lower(email) LIKE %s", ("%@example.com",)
    )
    await database.execute("DELETE FROM airlock_waitlist_attempts")
    for email in (FOUNDER_EMAIL, CLIENT_EMAIL):
        await database.execute("DELETE FROM users WHERE email=%s", (email,))

    application = create_app()
    application.state.database = database
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        yield client, database

    await database.close()
    get_settings.cache_clear()


async def _sign_in_as(client: AsyncClient, email: str) -> None:
    """Auth here is a session cookie, not a bearer token (see auth.py's
    _resolve_user_from_cookie) -- httpx's client stores it, so registering
    IS signing in. Cleared first so a previous identity can't leak into the
    next assertion.

    Registers on first use and logs in afterwards: a test that signs in as
    the same address twice (to read a value before and after an
    unauthenticated action) would otherwise hit register's deliberate 409.
    """
    client.cookies.clear()
    credentials = {"email": email, "password": "test-password-123"}
    response = await client.post("/v1/auth/register", json=credentials)
    if response.status_code == 409:
        response = await client.post("/v1/auth/login", json=credentials)
        assert response.status_code == 200, response.text
        return
    assert response.status_code == 201, response.text


@pytest.mark.asyncio
async def test_a_signup_is_recorded_once_however_many_times_it_is_sent(context):
    client, database = context
    first = await client.post(
        "/v1/airlock/waitlist",
        json={"email": WAITLIST_EMAIL, "company": "Example Ltd", "use_case": "A support agent that reads tickets."},
    )
    assert first.status_code == 202, first.text

    # Different case, no company: still the same address, still one row,
    # and the response is indistinguishable from the first.
    second = await client.post("/v1/airlock/waitlist", json={"email": WAITLIST_EMAIL.upper()})
    assert second.status_code == 202
    assert second.json() == first.json()

    rows = await database.fetch_all(
        "SELECT email, company, use_case FROM airlock_waitlist WHERE lower(email)=%s", (WAITLIST_EMAIL,)
    )
    assert len(rows) == 1
    # The first submission wins; the duplicate does not blank the details.
    assert rows[0]["company"] == "Example Ltd"
    assert rows[0]["email"] == WAITLIST_EMAIL


@pytest.mark.asyncio
async def test_a_malformed_address_is_rejected_before_it_reaches_the_table(context):
    client, database = context
    response = await client.post("/v1/airlock/waitlist", json={"email": "not-an-address"})
    assert response.status_code == 422
    count = await database.fetch_one("SELECT count(*) AS n FROM airlock_waitlist")
    assert count["n"] == 0


@pytest.mark.asyncio
async def test_the_list_is_founder_only(context):
    client, _database = context
    await client.post("/v1/airlock/waitlist", json={"email": WAITLIST_EMAIL})

    anonymous = await client.get("/v1/airlock/waitlist")
    assert anonymous.status_code == 401

    await _sign_in_as(client, CLIENT_EMAIL)
    as_client = await client.get("/v1/airlock/waitlist")
    assert as_client.status_code == 403

    await _sign_in_as(client, FOUNDER_EMAIL)
    as_founder = await client.get("/v1/airlock/waitlist")
    assert as_founder.status_code == 200
    assert [entry["email"] for entry in as_founder.json()] == [WAITLIST_EMAIL]


@pytest.mark.asyncio
async def test_one_source_cannot_fill_the_list(context):
    client, database = context
    from app.security.rate_limit import MAX_AIRLOCK_WAITLIST_PER_IP

    for index in range(MAX_AIRLOCK_WAITLIST_PER_IP):
        response = await client.post("/v1/airlock/waitlist", json={"email": f"airlock-flood-{index}@example.com"})
        assert response.status_code == 202, response.text

    blocked = await client.post("/v1/airlock/waitlist", json={"email": "airlock-flood-last@example.com"})
    assert blocked.status_code == 429
    count = await database.fetch_one(
        "SELECT count(*) AS n FROM airlock_waitlist WHERE email LIKE %s", ("airlock-flood-%",)
    )
    assert count["n"] == MAX_AIRLOCK_WAITLIST_PER_IP


@pytest.mark.asyncio
async def test_the_founder_summary_counts_the_waitlist(context):
    client, _database = context
    # A delta, not an absolute count. Nothing prunes airlock_waitlist, and
    # the fixture only clears @example.com rows -- a row from any other
    # source (a real signup, on a database shared with anything else) would
    # make an "== 1" assertion fail for a reason that has nothing to do with
    # what this test is about. Same fix as the activity-log count test.
    await _sign_in_as(client, FOUNDER_EMAIL)
    before = (await client.get("/v1/founder/summary")).json()["airlock_waitlist"]

    client.cookies.clear()
    joined = await client.post("/v1/airlock/waitlist", json={"email": WAITLIST_EMAIL})
    assert joined.status_code == 202

    await _sign_in_as(client, FOUNDER_EMAIL)
    summary = await client.get("/v1/founder/summary")
    assert summary.status_code == 200, summary.text
    after = summary.json()["airlock_waitlist"]
    assert after["total"] - before["total"] == 1
    assert after["last_7d"] - before["last_7d"] == 1
