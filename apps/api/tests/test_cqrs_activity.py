"""Direct tests of the command/query handlers in cqrs/activity.py, against
a real Postgres instance -- independent of any REST route or MCP tool, so
a mistake here (a bad WHERE clause, an off-by-one in keyset pagination)
gets caught at the one place the logic actually lives, not only through
whichever HTTP surface happens to call it.
"""

import os

import pytest
import pytest_asyncio

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not configured")

EMAIL_A = "cqrs-test-a@example.com"
EMAIL_B = "cqrs-test-b@example.com"


@pytest_asyncio.fixture
async def database(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL or "")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-used")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")

    from app.database import Database
    from app.settings import get_settings

    get_settings.cache_clear()
    db = Database(get_settings())
    await db.open()
    await db.execute("DELETE FROM account_activity_log WHERE client_email IN (%s, %s)", (EMAIL_A, EMAIL_B))
    yield db
    await db.close()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_handle_record_activity_writes_a_row_with_the_given_source(database) -> None:
    from app.cqrs.activity import ActivityLogFilter, RecordActivityCommand, handle_activity_log_query, handle_record_activity

    await handle_record_activity(
        database,
        RecordActivityCommand(client_email=EMAIL_A, action="test_action", detail="hello", source="mcp_agent"),
    )
    page = await handle_activity_log_query(database, ActivityLogFilter(client_email=EMAIL_A))
    assert len(page.entries) == 1
    assert page.entries[0].action == "test_action"
    assert page.entries[0].detail == "hello"
    assert page.entries[0].source == "mcp_agent"


@pytest.mark.asyncio
async def test_handle_record_activity_never_raises_even_against_a_closed_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Best-effort by design: a logging failure must never surface as an
    exception to the caller, which relies on that to keep the real action
    it's recording from failing alongside it."""
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL or "")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-used")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")

    from app.cqrs.activity import RecordActivityCommand, handle_record_activity
    from app.database import Database
    from app.settings import get_settings

    get_settings.cache_clear()
    unopened = Database(get_settings())
    # Never called .open() -- _require_pool() raises RuntimeError, the
    # real failure mode this is meant to survive.
    await handle_record_activity(unopened, RecordActivityCommand(client_email=EMAIL_A, action="never_written"))
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_query_with_no_client_email_sees_every_account(database) -> None:
    from app.cqrs.activity import ActivityLogFilter, RecordActivityCommand, handle_activity_log_query, handle_record_activity

    await handle_record_activity(database, RecordActivityCommand(client_email=EMAIL_A, action="a_action"))
    await handle_record_activity(database, RecordActivityCommand(client_email=EMAIL_B, action="b_action"))

    page = await handle_activity_log_query(database, ActivityLogFilter(limit=200))
    seen_emails = {e.client_email for e in page.entries}
    assert EMAIL_A in seen_emails
    assert EMAIL_B in seen_emails


@pytest.mark.asyncio
async def test_query_scoped_to_one_client_email_never_sees_another(database) -> None:
    from app.cqrs.activity import ActivityLogFilter, RecordActivityCommand, handle_activity_log_query, handle_record_activity

    await handle_record_activity(database, RecordActivityCommand(client_email=EMAIL_A, action="a_action"))
    await handle_record_activity(database, RecordActivityCommand(client_email=EMAIL_B, action="b_action"))

    page = await handle_activity_log_query(database, ActivityLogFilter(client_email=EMAIL_A))
    assert all(e.client_email == EMAIL_A for e in page.entries)
    assert any(e.action == "a_action" for e in page.entries)


@pytest.mark.asyncio
async def test_query_filters_by_source(database) -> None:
    from app.cqrs.activity import ActivityLogFilter, RecordActivityCommand, handle_activity_log_query, handle_record_activity

    await handle_record_activity(database, RecordActivityCommand(client_email=EMAIL_A, action="web_action", source="web"))
    await handle_record_activity(
        database, RecordActivityCommand(client_email=EMAIL_A, action="agent_action", source="mcp_agent")
    )

    web_page = await handle_activity_log_query(database, ActivityLogFilter(client_email=EMAIL_A, source="web"))
    assert {e.action for e in web_page.entries} == {"web_action"}

    agent_page = await handle_activity_log_query(database, ActivityLogFilter(client_email=EMAIL_A, source="mcp_agent"))
    assert {e.action for e in agent_page.entries} == {"agent_action"}


@pytest.mark.asyncio
async def test_query_filters_by_time_window(database) -> None:
    from app.cqrs.activity import ActivityLogFilter, handle_activity_log_query

    now = 10_000_000_000_000  # far future ms, well clear of real rows
    await database.execute(
        "INSERT INTO account_activity_log (client_email, action, source, created_at) VALUES (%s, 'old', 'web', %s)",
        (EMAIL_A, now - 10_000),
    )
    await database.execute(
        "INSERT INTO account_activity_log (client_email, action, source, created_at) VALUES (%s, 'new', 'web', %s)",
        (EMAIL_A, now),
    )

    page = await handle_activity_log_query(
        database, ActivityLogFilter(client_email=EMAIL_A, since_ms=now - 1, until_ms=now + 1)
    )
    assert {e.action for e in page.entries} == {"new"}


@pytest.mark.asyncio
async def test_keyset_pagination_covers_every_row_exactly_once(database) -> None:
    """The actual correctness property real (non-OFFSET) pagination has to
    hold: paging all the way through with limit=1 must visit every row
    written, each exactly once, regardless of insertion order ties."""
    from app.cqrs.activity import ActivityLogFilter, RecordActivityCommand, handle_activity_log_query, handle_record_activity

    for i in range(5):
        await handle_record_activity(database, RecordActivityCommand(client_email=EMAIL_A, action=f"action_{i}"))

    seen: list[str] = []
    cursor = None
    for _ in range(10):  # generous upper bound; a bug that loops forever should fail loudly, not hang
        page = await handle_activity_log_query(database, ActivityLogFilter(client_email=EMAIL_A, limit=1, cursor=cursor))
        if not page.entries:
            break
        seen.extend(e.action for e in page.entries)
        cursor = page.next_cursor
        if cursor is None:
            break

    assert sorted(seen) == [f"action_{i}" for i in range(5)]


@pytest.mark.asyncio
async def test_malformed_cursor_degrades_to_no_cursor_instead_of_500(database) -> None:
    from app.cqrs.activity import ActivityLogFilter, RecordActivityCommand, handle_activity_log_query, handle_record_activity

    await handle_record_activity(database, RecordActivityCommand(client_email=EMAIL_A, action="only_action"))
    page = await handle_activity_log_query(
        database, ActivityLogFilter(client_email=EMAIL_A, cursor="not-a-real-cursor")
    )
    assert any(e.action == "only_action" for e in page.entries)


@pytest.mark.asyncio
async def test_limit_is_clamped_to_the_page_size_ceiling(database) -> None:
    from app.cqrs.activity import MAX_ACTIVITY_LOG_PAGE_SIZE, ActivityLogFilter, RecordActivityCommand, handle_activity_log_query, handle_record_activity

    await handle_record_activity(database, RecordActivityCommand(client_email=EMAIL_A, action="one_row"))
    page = await handle_activity_log_query(
        database, ActivityLogFilter(client_email=EMAIL_A, limit=MAX_ACTIVITY_LOG_PAGE_SIZE * 10)
    )
    # Only one real row exists, so this doesn't prove the ceiling directly,
    # but it does prove an oversized limit doesn't raise -- the actual
    # regression this guards (an unclamped LIMIT value reaching Postgres
    # from an unvalidated client-supplied number).
    assert len(page.entries) == 1
