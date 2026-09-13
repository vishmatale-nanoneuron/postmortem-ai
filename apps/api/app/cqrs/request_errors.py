"""The error ledger: every unhandled 500 the API answers, as a row the
founder can read, plus one email per new fault per day.

Why a table and not a vendor: the product's whole posture is "no third
party sees more than it must", and an error tracker sees request paths,
exception messages and timing for every failure. Postgres already holds
all of that in the only place it needs to be. What is deliberately NOT
recorded: request bodies, headers, stack traces, the user. The exception
class, the route and the request id are enough to find the log line and
reproduce; the message is truncated in case a library put something it
should not have in it.

`record_error` is called from the exception handler and must never raise:
a failure to write the ledger is logged and swallowed, because the one
thing worse than an unrecorded 500 is a 500 handler that 500s.
"""

import hashlib
import logging
import time
from dataclasses import dataclass

from ..database import Database

logger = logging.getLogger("postmortem_ai")

MAX_MESSAGE_CHARS = 300
MAX_PATH_CHARS = 200
DAY_MS = 24 * 60 * 60 * 1000
RETENTION_DAYS = 90
# At most this many founder emails an hour, whatever is failing: a storm
# of distinct faults must not become a storm of email.
MAX_NOTIFICATIONS_PER_HOUR = 10


def fingerprint(error_type: str, method: str, path: str) -> str:
    return hashlib.sha256(f"{error_type}|{method}|{path}".encode()).hexdigest()[:16]


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(frozen=True)
class RecordErrorCommand:
    method: str
    path: str
    request_id: str
    error_type: str
    message: str
    status: int = 500


@dataclass(frozen=True)
class RecordedError:
    id: str
    fingerprint: str
    # True when this is the first sighting of the fingerprint in a day,
    # i.e. the caller should tell the founder.
    first_today: bool


async def handle_record_error(database: Database, command: RecordErrorCommand) -> RecordedError | None:
    """Writes the row and says whether it is news. Returns None (and logs)
    if the write itself fails -- never raises."""
    now = _now_ms()
    print_ = fingerprint(command.error_type, command.method, command.path)
    try:
        seen = await database.fetch_one(
            "SELECT 1 AS seen FROM request_errors WHERE fingerprint=%s AND created_at > %s LIMIT 1",
            (print_, now - DAY_MS),
        )
        row = await database.fetch_one(
            """INSERT INTO request_errors (created_at, method, path, status, request_id, error_type, message, fingerprint)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id::text""",
            (
                now,
                command.method[:16],
                command.path[:MAX_PATH_CHARS],
                command.status,
                command.request_id[:128],
                command.error_type[:120],
                command.message[:MAX_MESSAGE_CHARS],
                print_,
            ),
        )
        return RecordedError(id=row["id"], fingerprint=print_, first_today=seen is None)
    except Exception:
        logger.warning("request_error_ledger_write_failed", exc_info=True)
        return None


async def mark_notified(database: Database, error_id: str) -> None:
    try:
        await database.execute("UPDATE request_errors SET notified=true WHERE id=%s", (error_id,))
    except Exception:
        logger.warning("request_error_mark_notified_failed", exc_info=True)


async def notifications_in_last_hour(database: Database) -> int:
    try:
        row = await database.fetch_one(
            "SELECT count(*) AS n FROM request_errors WHERE notified AND created_at > %s",
            (_now_ms() - 60 * 60 * 1000,),
        )
        return int(row["n"]) if row else 0
    except Exception:
        return MAX_NOTIFICATIONS_PER_HOUR  # when in doubt, do not email


@dataclass(frozen=True)
class ErrorGroup:
    fingerprint: str
    error_type: str
    method: str
    path: str
    count: int
    first_seen: int
    last_seen: int
    last_request_id: str
    sample_message: str
    notified: bool


async def handle_error_groups_query(database: Database, *, days: int = 7) -> list[ErrorGroup]:
    """One line per fault, most recent first. Also the moment old rows go:
    anything past RETENTION_DAYS is deleted here rather than by a cron,
    because this is the only reader and it runs whenever the founder looks."""
    now = _now_ms()
    try:
        await database.execute("DELETE FROM request_errors WHERE created_at < %s", (now - RETENTION_DAYS * DAY_MS,))
    except Exception:
        logger.warning("request_error_prune_failed", exc_info=True)
    rows = await database.fetch_all(
        """SELECT fingerprint,
                  max(error_type) AS error_type,
                  max(method) AS method,
                  max(path) AS path,
                  count(*)::int AS count,
                  min(created_at) AS first_seen,
                  max(created_at) AS last_seen,
                  (array_agg(request_id ORDER BY created_at DESC))[1] AS last_request_id,
                  (array_agg(message ORDER BY created_at DESC))[1] AS sample_message,
                  bool_or(notified) AS notified
           FROM request_errors
           WHERE created_at > %s
           GROUP BY fingerprint
           ORDER BY last_seen DESC
           LIMIT 200""",
        (now - days * DAY_MS,),
    )
    return [ErrorGroup(**row) for row in rows]


async def handle_error_count_query(database: Database, *, days: int = 1) -> int:
    row = await database.fetch_one(
        "SELECT count(*) AS n FROM request_errors WHERE created_at > %s", (_now_ms() - days * DAY_MS,)
    )
    return int(row["n"]) if row else 0
