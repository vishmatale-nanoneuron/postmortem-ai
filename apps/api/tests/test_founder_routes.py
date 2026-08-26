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
async def test_ai_run_health_is_broken_out_by_24h_window_and_feature(context) -> None:
    import time

    client, database = context
    await client.post("/v1/auth/register", json={"email": FOUNDER_EMAIL, "password": "correct-horse-battery"})

    incident = await client.post(
        "/v1/postmortems/incidents", json={"title": "AI health test incident", "severity": "sev2"}
    )
    incident_id = incident.json()["id"]

    # ai_runs is a global, unscoped table -- other test files' drafting/
    # extraction tests (real prompt_version values "v2"/"extract-v1") also
    # write rows to it in this same shared database. Baseline before
    # inserting, then assert deltas -- not absolute counts, which would be
    # flaky depending on test run order/parallelism.
    baseline = await client.get("/v1/founder/summary")
    baseline_body = baseline.json()
    baseline_24h_total = baseline_body["ai_runs_24h_total"]
    baseline_24h_succeeded = baseline_body["ai_runs_24h_succeeded"]
    baseline_24h_failed = baseline_body["ai_runs_24h_failed"]
    baseline_by_feature = {row["prompt_version"]: row for row in baseline_body["ai_runs_by_feature"]}

    now = int(time.time() * 1000)
    two_days_ago = now - 2 * 24 * 60 * 60 * 1000

    async def insert_run(prompt_version: str, status_value: str, latency_ms: int, created_at: int) -> None:
        await database.execute(
            """INSERT INTO ai_runs
                 (id,incident_id,provider,model,prompt_version,input_chars,
                  output_tokens,latency_ms,status,error_type,created_at)
               VALUES (gen_random_uuid(),%s,'fake','fake-model',%s,10,5,%s,%s,%s,%s)""",
            (incident_id, prompt_version, latency_ms, status_value, None if status_value == "succeeded" else "test_error", created_at),
        )

    # Recent: one succeeded draft, one failed extraction.
    await insert_run("v2", "succeeded", 100, now)
    await insert_run("extract-v1", "failed", 50, now)
    # Old (outside the 24h window): must not count toward the 24h figures,
    # but must still count toward all-time and the per-feature totals.
    await insert_run("v2", "succeeded", 200, two_days_ago)

    summary = await client.get("/v1/founder/summary")
    assert summary.status_code == 200
    body = summary.json()

    assert body["ai_runs_24h_total"] - baseline_24h_total == 2
    assert body["ai_runs_24h_succeeded"] - baseline_24h_succeeded == 1
    assert body["ai_runs_24h_failed"] - baseline_24h_failed == 1

    by_feature = {row["prompt_version"]: row for row in body["ai_runs_by_feature"]}
    v2_baseline_total = baseline_by_feature.get("v2", {}).get("total", 0)
    v2_baseline_succeeded = baseline_by_feature.get("v2", {}).get("succeeded", 0)
    extract_baseline_total = baseline_by_feature.get("extract-v1", {}).get("total", 0)
    extract_baseline_failed = baseline_by_feature.get("extract-v1", {}).get("failed", 0)

    assert by_feature["v2"]["total"] - v2_baseline_total == 2  # both v2 runs, including the 2-day-old one
    assert by_feature["v2"]["succeeded"] - v2_baseline_succeeded == 2
    assert by_feature["extract-v1"]["total"] - extract_baseline_total == 1
    assert by_feature["extract-v1"]["failed"] - extract_baseline_failed == 1


@pytest.mark.asyncio
async def test_a_founder_summary_call_without_a_session_is_unauthorized(context) -> None:
    client, _ = context
    response = await client.get("/v1/founder/summary")
    assert response.status_code == 401
