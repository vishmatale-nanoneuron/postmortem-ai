"""Command/query split for account_activity_log (migration 0024, extended
by 0027 with `source`).

Before this module, "log an activity" and "read the activity log" were two
unrelated functions living in api/v1/postmortems.py, and only one read
shape existed (a caller's own history). Adding a second, genuinely
different read shape -- a founder-only view across every account, for the
new agent-accountability feature -- is exactly the moment a single
`log_activity` helper stops being enough: the caller-scoped and
platform-wide reads share nothing but the table, while every write (from
REST routes and from MCP's _audited() wrapper) shares everything. Splitting
along that seam is what CQRS means at this app's actual scale -- one
Postgres instance, one writer -- not a message bus or a separate read
model, which nothing here has a real use for.

RecordActivityCommand/handle_record_activity is the one way any code path
writes a row. ActivityLogFilter/handle_activity_log_query is the one way
any code path reads them, whether scoped to one account
(api/v1/postmortems.py's GET /activity-log) or across all of them
(api/v1/founder.py's GET /activity-log, mcp_server.py's
list_agent_activity tool) -- both pass through the same handler with a
different filter, rather than two separately-written SQL queries that
could drift apart.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from ..database import Database

logger = logging.getLogger("postmortem_ai")

# ---------------------------------------------------------------------------
# Command side -- the one way any code path records an activity-log row.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RecordActivityCommand:
    client_email: str
    action: str
    incident_id: str | None = None
    detail: str | None = None
    # "web" (a browser session or a webhook acting as one) or "mcp_agent"
    # (an AI agent via this account's own MCP tools) -- see
    # mcp_server.py's _audited().
    source: str = "web"


async def handle_record_activity(database: Database, command: RecordActivityCommand) -> None:
    """Best-effort by design: a logging failure must never block the real
    action it's recording -- every call site relies on this degrading to a
    log line, not a broken request, exactly as it did when this was
    api/v1/postmortems.py's log_activity."""
    try:
        await database.execute(
            "INSERT INTO account_activity_log (client_email, action, incident_id, detail, source, created_at)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (
                command.client_email,
                command.action,
                command.incident_id,
                command.detail,
                command.source,
                int(time.time() * 1000),
            ),
        )
    except Exception:
        logger.warning(
            "activity_log_write_failed",
            extra={"action": command.action, "incident_id": command.incident_id},
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# Query side -- every read of the activity log, caller-scoped or
# platform-wide, paged the same way.
# ---------------------------------------------------------------------------

MAX_ACTIVITY_LOG_PAGE_SIZE = 200


@dataclass(frozen=True)
class ActivityLogEntry:
    client_email: str
    action: str
    incident_id: str | None
    detail: str | None
    source: str
    created_at: int


@dataclass(frozen=True)
class ActivityLogPage:
    entries: list[ActivityLogEntry]
    # Opaque -- pass back as ActivityLogFilter.cursor to fetch the next
    # page. None means this page was the last one.
    next_cursor: str | None


@dataclass(frozen=True)
class ActivityLogFilter:
    """client_email=None is what makes a query platform-wide rather than
    one account's own history -- only the founder-only REST route and MCP
    tool ever construct a filter that way; api/v1/postmortems.py's own
    GET /activity-log always passes the caller's own email."""

    client_email: str | None = None
    source: str | None = None
    since_ms: int | None = None
    until_ms: int | None = None
    limit: int = 50
    cursor: str | None = None


def _parse_cursor(cursor: str) -> tuple[int, str] | None:
    # "<created_at>:<id>" -- see _encode_cursor below. Malformed input (a
    # hand-edited query string) degrades to "no cursor" rather than a 500.
    try:
        created_at_part, id_part = cursor.split(":", 1)
        return int(created_at_part), id_part
    except (ValueError, AttributeError):
        return None


def _encode_cursor(created_at: int, row_id: str) -> str:
    return f"{created_at}:{row_id}"


async def handle_activity_log_query(database: Database, query: ActivityLogFilter) -> ActivityLogPage:
    """Real keyset pagination -- WHERE (created_at, id) < (%s, %s) ORDER BY
    created_at DESC, id DESC -- rather than OFFSET, which drifts under
    concurrent inserts (a row written between two page fetches shifts
    every later page by one, silently duplicating or skipping rows).
    created_at alone isn't unique enough to key on (two rows can share a
    millisecond); pairing it with the uuid primary key makes every cursor
    position unambiguous."""
    limit = max(1, min(query.limit, MAX_ACTIVITY_LOG_PAGE_SIZE))
    conditions: list[str] = []
    values: list[object] = []

    if query.client_email is not None:
        conditions.append("client_email = %s")
        values.append(query.client_email)
    if query.source is not None:
        conditions.append("source = %s")
        values.append(query.source)
    if query.since_ms is not None:
        conditions.append("created_at >= %s")
        values.append(query.since_ms)
    if query.until_ms is not None:
        conditions.append("created_at <= %s")
        values.append(query.until_ms)
    if query.cursor is not None:
        parsed = _parse_cursor(query.cursor)
        if parsed is not None:
            conditions.append("(created_at, id) < (%s, %s)")
            values.extend(parsed)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = await database.fetch_all(
        f"""SELECT id::text, client_email, action, incident_id, detail, source, created_at
            FROM account_activity_log
            {where_clause}
            ORDER BY created_at DESC, id DESC
            LIMIT %s""",
        (*values, limit),
    )
    entries = [
        ActivityLogEntry(
            client_email=row["client_email"],
            action=row["action"],
            incident_id=row["incident_id"],
            detail=row["detail"],
            source=row["source"],
            created_at=row["created_at"],
        )
        for row in rows
    ]
    # A full page might still be the last one (exactly `limit` rows left) --
    # harmless, it just costs one extra empty-page fetch to find out, the
    # same tradeoff every keyset-paginated API without a COUNT(*) makes.
    next_cursor = _encode_cursor(rows[-1]["created_at"], rows[-1]["id"]) if len(rows) == limit else None
    return ActivityLogPage(entries=entries, next_cursor=next_cursor)
