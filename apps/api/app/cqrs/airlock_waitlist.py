"""Command/query split for airlock_waitlist (migration 0030).

Same seam, and the same reason, as cqrs/activity.py: one write path, more
than one genuinely different read shape. A waitlist row is written by one
public endpoint and never updated; it is read two ways that share nothing
but the table -- the founder's list of who signed up (addresses, companies,
what they said they'd point it at) and a pair of counts on the founder
summary (total, last 7 days) that must never carry an address into a
platform-wide dashboard payload.

Keeping those two reads in one module rather than as SQL inlined in two
routers is what stops them drifting: the counting query and the listing
query are about the same rows, and a later change to what "on the list"
means (soft-deletion, say, or an unsubscribe flag) has exactly one place to
land. At this app's scale -- one Postgres instance, one writer -- that is
what CQRS buys; not a message bus or a separate read model, which nothing
here has a use for.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from ..database import Database

logger = logging.getLogger("postmortem_ai")

# ---------------------------------------------------------------------------
# Command side -- the one way any code path adds someone to the list.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JoinWaitlistCommand:
    email: str
    company: str | None = None
    use_case: str | None = None


async def handle_join_waitlist(database: Database, command: JoinWaitlistCommand) -> None:
    """Idempotent by construction. The unique index is on lower(email), so
    the address is lowercased here -- the one place it is written -- rather
    than trusting each caller to do it and the stored value to agree with
    the index.

    Unlike handle_record_activity, this is NOT best-effort: a failure here
    must reach the caller as a 500 rather than a cheerful 202, because the
    whole point of the endpoint is that the row exists afterwards.
    """
    email = command.email.strip().lower()
    company = (command.company or "").strip() or None
    use_case = (command.use_case or "").strip() or None
    await database.execute(
        """INSERT INTO airlock_waitlist (email, company, use_case, created_at)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (lower(email)) DO NOTHING""",
        (email, company, use_case, int(time.time() * 1000)),
    )
    # No address in the log line -- the table is the only place it lives.
    logger.info("airlock_waitlist_signup recorded")


# ---------------------------------------------------------------------------
# Query side -- the two reads, both founder-only at their call sites.
# ---------------------------------------------------------------------------

MAX_WAITLIST_PAGE_SIZE = 500

SEVEN_DAYS_MS = 7 * 24 * 60 * 60 * 1000


@dataclass(frozen=True)
class WaitlistEntry:
    id: str
    email: str
    company: str | None
    use_case: str | None
    created_at: int


@dataclass(frozen=True)
class WaitlistCounts:
    total: int
    last_7d: int


@dataclass(frozen=True)
class WaitlistQuery:
    limit: int = MAX_WAITLIST_PAGE_SIZE


async def handle_waitlist_query(database: Database, query: WaitlistQuery) -> list[WaitlistEntry]:
    limit = max(1, min(query.limit, MAX_WAITLIST_PAGE_SIZE))
    rows = await database.fetch_all(
        """SELECT id::text, email, company, use_case, created_at
           FROM airlock_waitlist ORDER BY created_at DESC LIMIT %s""",
        (limit,),
    )
    return [WaitlistEntry(**row) for row in rows]


async def handle_waitlist_counts_query(database: Database, *, now_ms: int | None = None) -> WaitlistCounts:
    """The founder-summary read. Returns counts only -- no addresses, by
    construction rather than by each caller remembering to strip them."""
    cutoff = (int(time.time() * 1000) if now_ms is None else now_ms) - SEVEN_DAYS_MS
    row = await database.fetch_one(
        """SELECT count(*) AS total,
                  count(*) FILTER (WHERE created_at >= %s) AS last_7d
           FROM airlock_waitlist""",
        (cutoff,),
    )
    return WaitlistCounts(total=int((row or {}).get("total", 0)), last_7d=int((row or {}).get("last_7d", 0)))
