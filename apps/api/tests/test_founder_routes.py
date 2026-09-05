"""Founder gate + dashboard, end-to-end against a real PostgreSQL instance.

Skipped unless TEST_DATABASE_URL is set, matching the rest of this suite.
"""

import os
import time

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
    # free_incident_id's FK is ON DELETE SET NULL, not CASCADE -- deleting
    # the user row above wouldn't clean up the incidents row the
    # conversion-funnel test inserts directly, and a fixed incident id
    # would collide with itself on the next run.
    await database.execute("DELETE FROM incidents WHERE client_email LIKE %s", ("founder-test-%",))
    await database.execute("DELETE FROM users WHERE email LIKE %s", ("founder-test-%",))
    await database.execute("DELETE FROM users WHERE email=%s", (FOUNDER_EMAIL,))
    # account_activity_log.client_email is a plain column, not a foreign
    # key (deliberately -- see migration 0024's own comment: history must
    # survive even an account being deleted) -- so the DELETEs above don't
    # cascade-clean it. Needed for the activity-log tests' exact-count
    # assertions below to stay reliable across repeated runs.
    await database.execute("DELETE FROM account_activity_log WHERE client_email LIKE %s", ("founder-test-%",))
    await database.execute("DELETE FROM account_activity_log WHERE client_email=%s", (FOUNDER_EMAIL,))

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

    # Resolving it makes it count toward the real, computed platform-wide
    # mean-time-to-resolve -- never a hardcoded number.
    resolve = await client.patch(f"/v1/postmortems/incidents/{incident.json()['id']}/status", json={"status": "resolved"})
    assert resolve.status_code == 200

    summary_after = await client.get("/v1/founder/summary")
    body_after = summary_after.json()
    assert body_after["avg_resolution_ms"] is not None
    assert body_after["avg_resolution_ms"] >= 0


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


@pytest.mark.asyncio
async def test_conversion_funnel_excludes_the_founder_and_tracks_real_signups(context) -> None:
    """The funnel exists to answer "where do accounts actually drop off,"
    which the founder's own account (always is_founder, never a real paying
    customer) would only distort if counted."""
    client, database = context
    await client.post("/v1/auth/register", json={"email": FOUNDER_EMAIL, "password": "correct-horse-battery"})

    baseline = (await client.get("/v1/founder/summary")).json()["conversion_funnel"]

    # A regular signup that never touches an incident -- counts as a signup,
    # nothing else.
    await client.post(
        "/v1/auth/register", json={"email": "founder-test-cold@example.com", "password": "correct-horse-battery"}
    )
    # A signup with a free incident on record but never paid -- the trial
    # is retired for new grants (see test_free_incident.py), so this can no
    # longer be produced by actually calling POST /incidents; insert the
    # incident and set the column directly, the same way the legacy-account
    # fixture there does (free_incident_id has a real FK into incidents).
    warm_client_cookies = await client.post(
        "/v1/auth/register", json={"email": "founder-test-warm@example.com", "password": "correct-horse-battery"}
    )
    assert warm_client_cookies.status_code == 201
    now = int(time.time() * 1000)
    await database.execute(
        """INSERT INTO incidents (id, client_email, title, severity, status, impact, created_at, updated_at)
           VALUES ('inc-funnel-test-warm', %s, 'Legacy free incident', 'sev3', 'open', NULL, %s, %s)""",
        ("founder-test-warm@example.com", now, now),
    )
    await database.execute(
        "UPDATE users SET free_incident_id='inc-funnel-test-warm' WHERE email=%s", ("founder-test-warm@example.com",)
    )
    await client.post("/v1/auth/logout")

    # A signup with a real, currently-active manual (UPI/wire) subscription --
    # directly via the database rather than the real payment-claim approval
    # flow, since only the exact resulting user row state matters here, not
    # re-testing that flow (already covered by its own tests).
    await client.post(
        "/v1/auth/register", json={"email": "founder-test-paying@example.com", "password": "correct-horse-battery"}
    )
    await database.execute(
        "UPDATE users SET subscription_status='active', current_period_end=%s WHERE email=%s",
        (9999999999, "founder-test-paying@example.com"),
    )
    await client.post("/v1/auth/logout")

    # A signup whose manual subscription lapsed -- still 'ever_paid' (their
    # stored status never flips back to 'none' on its own, per
    # auth.py's has_free_incident_available reasoning) but not
    # 'currently_paying'.
    await client.post(
        "/v1/auth/register", json={"email": "founder-test-lapsed@example.com", "password": "correct-horse-battery"}
    )
    await database.execute(
        "UPDATE users SET subscription_status='active', current_period_end=%s WHERE email=%s",
        (1, "founder-test-lapsed@example.com"),
    )
    await client.post("/v1/auth/logout")

    await client.post("/v1/auth/login", json={"email": FOUNDER_EMAIL, "password": "correct-horse-battery"})
    funnel = (await client.get("/v1/founder/summary")).json()["conversion_funnel"]

    assert funnel["signups"] - baseline["signups"] == 4
    assert funnel["tried_free_incident"] - baseline["tried_free_incident"] == 1
    assert funnel["ever_paid"] - baseline["ever_paid"] == 2
    assert funnel["currently_paying"] - baseline["currently_paying"] == 1


# ---------------------------------------------------------------------------
# GET /v1/founder/activity-log: the cross-account counterpart to
# GET /v1/postmortems/activity-log (see cqrs/activity.py) -- same query
# handler, called with client_email left unset instead of scoped to one
# caller.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_non_founder_cannot_reach_the_platform_wide_activity_log(context) -> None:
    client, _ = context
    await client.post(
        "/v1/auth/register", json={"email": "founder-test-regular@example.com", "password": "correct-horse-battery"}
    )
    response = await client.get("/v1/founder/activity-log")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_the_platform_wide_activity_log_sees_another_accounts_own_history(context) -> None:
    """The whole point of this endpoint: unlike GET
    /v1/postmortems/activity-log (scoped to the caller's own client_email),
    the founder can see an action a *different* account took."""
    client, database = context
    await client.post(
        "/v1/auth/register", json={"email": "founder-test-other@example.com", "password": "correct-horse-battery"}
    )
    # The free-incident trial is retired for new signups (see
    # test_free_incident.py) -- grant a real active subscription directly,
    # same pattern as the conversion-funnel test above, so creating an
    # incident below isn't blocked by the paywall this test isn't about.
    await database.execute(
        "UPDATE users SET subscription_status='active', current_period_end=%s WHERE email=%s",
        (9999999999, "founder-test-other@example.com"),
    )
    created = await client.post(
        "/v1/postmortems/incidents", json={"title": "Someone else's incident", "severity": "sev2"}
    )
    assert created.status_code == 201
    await client.post("/v1/auth/logout")

    await client.post("/v1/auth/register", json={"email": FOUNDER_EMAIL, "password": "correct-horse-battery"})
    # A founder account with no incidents of its own would see this in
    # their own GET /v1/postmortems/activity-log only if it were their own
    # action -- it isn't, so that endpoint would show nothing for it.
    own_scope = await client.get("/v1/postmortems/activity-log")
    assert not any(e["action"] == "incident_created" for e in own_scope.json())

    response = await client.get("/v1/founder/activity-log")
    assert response.status_code == 200, response.text
    body = response.json()
    assert any(
        e["client_email"] == "founder-test-other@example.com" and e["action"] == "incident_created"
        for e in body["entries"]
    ), body


@pytest.mark.asyncio
async def test_the_platform_wide_activity_log_filters_by_client_email_and_source(context) -> None:
    client, database = context
    await client.post(
        "/v1/auth/register", json={"email": "founder-test-filterme@example.com", "password": "correct-horse-battery"}
    )
    await database.execute(
        "UPDATE users SET subscription_status='active', current_period_end=%s WHERE email=%s",
        (9999999999, "founder-test-filterme@example.com"),
    )
    created = await client.post("/v1/postmortems/incidents", json={"title": "Filter target", "severity": "sev3"})
    assert created.status_code == 201, created.text
    await client.post("/v1/auth/logout")

    await client.post("/v1/auth/register", json={"email": FOUNDER_EMAIL, "password": "correct-horse-battery"})

    scoped = await client.get(
        "/v1/founder/activity-log", params={"client_email": "founder-test-filterme@example.com"}
    )
    assert scoped.status_code == 200
    scoped_entries = scoped.json()["entries"]
    assert len(scoped_entries) > 0
    assert all(e["client_email"] == "founder-test-filterme@example.com" for e in scoped_entries)

    # source="web" -- this row really was created over REST, not MCP -- so
    # the filter should still include it; a bogus source should exclude it.
    web_only = await client.get(
        "/v1/founder/activity-log",
        params={"client_email": "founder-test-filterme@example.com", "source": "web"},
    )
    assert any(e["action"] == "incident_created" for e in web_only.json()["entries"])

    agent_only = await client.get(
        "/v1/founder/activity-log",
        params={"client_email": "founder-test-filterme@example.com", "source": "mcp_agent"},
    )
    assert agent_only.json()["entries"] == []


@pytest.mark.asyncio
async def test_the_platform_wide_activity_log_paginates_with_a_real_cursor(context) -> None:
    """Real keyset pagination (cqrs/activity.py), not OFFSET: fetching two
    pages of 1 with the second page's cursor from the first must not
    repeat a row, and must stay consistent even though other tests in this
    file/run are writing to the same shared table concurrently."""
    client, database = context
    await client.post(
        "/v1/auth/register", json={"email": "founder-test-paginate@example.com", "password": "correct-horse-battery"}
    )
    await database.execute(
        "UPDATE users SET subscription_status='active', current_period_end=%s WHERE email=%s",
        (9999999999, "founder-test-paginate@example.com"),
    )
    first_created = await client.post("/v1/postmortems/incidents", json={"title": "Page one", "severity": "sev4"})
    assert first_created.status_code == 201, first_created.text
    second_created = await client.post("/v1/postmortems/incidents", json={"title": "Page two", "severity": "sev4"})
    assert second_created.status_code == 201, second_created.text
    await client.post("/v1/auth/logout")

    await client.post("/v1/auth/register", json={"email": FOUNDER_EMAIL, "password": "correct-horse-battery"})

    first_page = await client.get(
        "/v1/founder/activity-log",
        params={"client_email": "founder-test-paginate@example.com", "limit": 1},
    )
    assert first_page.status_code == 200
    first_body = first_page.json()
    assert len(first_body["entries"]) == 1
    assert first_body["next_cursor"] is not None

    second_page = await client.get(
        "/v1/founder/activity-log",
        params={
            "client_email": "founder-test-paginate@example.com",
            "limit": 1,
            "cursor": first_body["next_cursor"],
        },
    )
    assert second_page.status_code == 200
    second_body = second_page.json()
    assert len(second_body["entries"]) == 1
    assert second_body["entries"][0]["created_at"] != first_body["entries"][0]["created_at"] or (
        second_body["entries"][0]["action"] != first_body["entries"][0]["action"]
    )
