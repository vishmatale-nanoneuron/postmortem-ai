"""The error ledger: a 500 in production is a row the founder can read and
one email per new fault per day, not a log line nobody sees.

Pinned: the row matches the request id the customer was shown; the same
fault again is counted, not re-emailed; a different fault is; the hourly
email cap holds; a founder can list, a client cannot; the ledger write
failing does not change the 500 the customer gets; and the fail-closed
body on the Airlock paths is untouched by all of this.
"""

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not configured")

FOUNDER_EMAIL = "errors-founder@example.com"
CLIENT_EMAIL = "errors-client@example.com"
PASSWORD = "test-password-123"


@pytest_asyncio.fixture
async def context(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL or "")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-used")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-0123456789abcdef0123")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("FOUNDER_EMAIL", FOUNDER_EMAIL)
    monkeypatch.setenv("RESEND_API_KEY", "test-key-not-used")
    monkeypatch.setenv("RESEND_EMAIL_DOMAIN", "test.example.com")

    from app.database import Database
    from app.main import create_app
    from app.settings import get_settings

    sent: list[dict] = []

    def fake_notify(settings, **kwargs):
        sent.append(kwargs)

    monkeypatch.setattr("app.main.send_founder_error_notification", fake_notify)

    get_settings.cache_clear()
    database = Database(get_settings())
    await database.open()
    await database.execute("DELETE FROM request_errors")
    await database.execute("DELETE FROM registration_attempts")
    await database.execute("DELETE FROM users WHERE email = ANY(%s)", ([FOUNDER_EMAIL, CLIENT_EMAIL],))

    application = create_app()
    application.state.database = database
    async with AsyncClient(
        transport=ASGITransport(app=application, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        yield client, database, sent

    await database.close()
    get_settings.cache_clear()


async def _sign_in_as(client: AsyncClient, email: str) -> None:
    client.cookies.clear()
    credentials = {"email": email, "password": PASSWORD}
    response = await client.post("/v1/auth/register", json=credentials)
    if response.status_code == 409:
        response = await client.post("/v1/auth/login", json=credentials)
    assert response.status_code in (200, 201), response.text


def _break(monkeypatch: pytest.MonkeyPatch, target: str, error: Exception) -> None:
    def broken(*args, **kwargs):
        raise error

    monkeypatch.setattr(target, broken)


@pytest.mark.asyncio
async def test_a_500_becomes_a_row_and_one_email_per_fault_per_day(context, monkeypatch: pytest.MonkeyPatch):
    client, database, sent = context
    _break(monkeypatch, "app.api.v1.airlock.handle_scan_stats_query", RuntimeError("stats query exploded"))

    first = await client.get("/v1/airlock/stats", headers={"X-Request-ID": "req-errors-0001"})
    assert first.status_code == 500
    assert first.json() == {"detail": "Internal server error", "request_id": "req-errors-0001"}

    rows = await database.fetch_all("SELECT * FROM request_errors ORDER BY created_at")
    assert len(rows) == 1
    row = rows[0]
    assert (row["method"], row["path"], row["status"]) == ("GET", "/v1/airlock/stats", 500)
    assert row["request_id"] == "req-errors-0001"
    assert row["error_type"] == "RuntimeError" and row["message"] == "stats query exploded"
    assert row["notified"] is True
    assert len(sent) == 1
    assert sent[0]["request_id"] == "req-errors-0001" and sent[0]["fingerprint"] == row["fingerprint"]
    assert "exploded" in sent[0]["message"]

    # The same fault again: counted, not re-emailed.
    again = await client.get("/v1/airlock/stats", headers={"X-Request-ID": "req-errors-0002"})
    assert again.status_code == 500
    rows = await database.fetch_all("SELECT notified FROM request_errors ORDER BY created_at")
    assert [r["notified"] for r in rows] == [True, False]
    assert len(sent) == 1

    # A different fault on the same route is news.
    _break(monkeypatch, "app.api.v1.airlock.handle_scan_stats_query", KeyError("total"))
    assert (await client.get("/v1/airlock/stats")).status_code == 500
    assert len(sent) == 2 and sent[1]["error_type"] == "KeyError"


@pytest.mark.asyncio
async def test_the_founder_sees_grouped_errors_and_a_client_does_not(context, monkeypatch: pytest.MonkeyPatch):
    client, database, sent = context
    _break(monkeypatch, "app.api.v1.airlock.handle_scan_stats_query", RuntimeError("boom"))
    for _ in range(3):
        await client.get("/v1/airlock/stats")

    await _sign_in_as(client, CLIENT_EMAIL)
    assert (await client.get("/v1/founder/errors")).status_code in (403, 404)
    summary_as_client = await client.get("/v1/founder/summary")
    assert summary_as_client.status_code in (403, 404)

    await _sign_in_as(client, FOUNDER_EMAIL)
    listed = await client.get("/v1/founder/errors?days=7")
    assert listed.status_code == 200, listed.text
    groups = listed.json()
    assert len(groups) == 1
    group = groups[0]
    assert group["count"] == 3 and group["error_type"] == "RuntimeError" and group["path"] == "/v1/airlock/stats"
    assert group["sample_message"] == "boom" and group["notified"] is True
    assert group["last_seen"] >= group["first_seen"]
    assert group["last_request_id"]

    summary = await client.get("/v1/founder/summary")
    assert summary.status_code == 200, summary.text
    assert summary.json()["errors"] == {"last_24h": 3, "last_7d": 3}
    assert (await client.get("/v1/founder/errors?days=0")).status_code == 422


@pytest.mark.asyncio
async def test_the_email_cap_holds_and_a_broken_ledger_does_not_change_the_500(context, monkeypatch: pytest.MonkeyPatch):
    from app.cqrs import request_errors as ledger

    client, database, sent = context
    # Ten distinct faults email; the eleventh in the same hour does not.
    for n in range(11):
        _break(monkeypatch, "app.api.v1.airlock.handle_scan_stats_query", RuntimeError(f"fault {n}"))
        monkeypatch.setattr(ledger, "fingerprint", lambda t, m, p, n=n: f"fp-{n:02d}")
        assert (await client.get("/v1/airlock/stats")).status_code == 500
    assert len(sent) == ledger.MAX_NOTIFICATIONS_PER_HOUR
    assert (await database.fetch_one("SELECT count(*) AS n FROM request_errors"))["n"] == 11

    # The ledger itself failing: the customer still gets the same 500 with
    # their request id and, on a decision path, the fail-closed verdict.
    async def cannot_write(*args, **kwargs):
        raise RuntimeError("ledger down")

    monkeypatch.setattr("app.main.handle_record_error", cannot_write)
    _break(monkeypatch, "app.api.v1.airlock._DETECTOR.scan", RuntimeError("engine fault"))
    await _sign_in_as(client, FOUNDER_EMAIL)
    response = await client.post("/v1/airlock/scan", json={"content": "x"}, headers={"X-Request-ID": "req-ledger-down"})
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error", "request_id": "req-ledger-down", "verdict": "block"}
