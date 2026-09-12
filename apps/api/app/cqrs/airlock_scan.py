"""Command/query split for airlock_scan_events (migration 0031).

The third module to use this seam, and the one where it earns the most:
writing a scan decision and reading the aggregate are not just different
queries, they have different *rules*. Every write is append-only and
carries no personal data by construction; every read is an aggregate that
must never be able to reconstruct a scanned document. Keeping both behind
handlers means those rules live in one file rather than being re-decided by
each route that touches the table.

Note what handle_record_scan does NOT accept: the scanned text. A caller
cannot store content through this interface even by mistake, because the
interface has nowhere to put it -- the command takes a Detection's derived
fields (hash, byte count, verdict, score, rule ids), not the document.
That is a stronger guarantee than a code review promising nobody will pass
the wrong argument.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

from ..database import Database

logger = logging.getLogger("postmortem_ai")

# ---------------------------------------------------------------------------
# Command side -- the one way a scan decision is recorded.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RecordScanCommand:
    kind: str  # "ingress" | "egress"
    verdict: str  # "allow" | "flag" | "block"
    score: float
    content_sha256: str
    content_bytes: int
    matched_rules: list[str]
    source: str | None = None
    latency_ms: int = 0
    # Redacted excerpt. Left None by the public playground: a free
    # unauthenticated scanner storing fragments of whatever strangers paste
    # is a liability with no matching benefit, and the page promises the
    # content is not kept.
    excerpt: str | None = None


async def handle_record_scan(database: Database, command: RecordScanCommand) -> None:
    """Best-effort, like handle_record_activity and unlike
    handle_join_waitlist: the verdict is the product, and a caller must
    still get its answer if the audit write fails. A failure here is loud in
    the logs rather than fatal to the request that produced it.

    The row cannot be corrected afterwards -- the table refuses UPDATE,
    DELETE and TRUNCATE at the database level -- so anything wrong here is
    wrong forever. Hence writing only derived values, never the content.
    """
    try:
        await database.execute(
            """INSERT INTO airlock_scan_events
                   (kind, source, verdict, score, matched_rules, content_sha256,
                    content_bytes, excerpt, latency_ms, created_at)
               VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s)""",
            (
                command.kind,
                command.source,
                command.verdict,
                command.score,
                json.dumps(list(command.matched_rules)),
                command.content_sha256,
                command.content_bytes,
                command.excerpt,
                command.latency_ms,
                int(time.time() * 1000),
            ),
        )
    except Exception:
        logger.warning(
            "airlock_scan_event_write_failed",
            extra={"kind": command.kind, "verdict": command.verdict},
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# Query side -- aggregates only. Nothing here returns a row's excerpt or
# anything that could reassemble a scanned document.
# ---------------------------------------------------------------------------

SEVEN_DAYS_MS = 7 * 24 * 60 * 60 * 1000


@dataclass(frozen=True)
class ScanStats:
    total: int
    blocked: int
    flagged: int
    allowed: int
    last_7d: int
    top_rules: list[dict]


async def handle_scan_stats_query(database: Database, *, now_ms: int | None = None) -> ScanStats:
    cutoff = (int(time.time() * 1000) if now_ms is None else now_ms) - SEVEN_DAYS_MS
    row = await database.fetch_one(
        """SELECT count(*) AS total,
                  count(*) FILTER (WHERE verdict = 'block') AS blocked,
                  count(*) FILTER (WHERE verdict = 'flag') AS flagged,
                  count(*) FILTER (WHERE verdict = 'allow') AS allowed,
                  count(*) FILTER (WHERE created_at >= %s) AS last_7d
           FROM airlock_scan_events""",
        (cutoff,),
    )
    # Which rules actually fire, ranked. The corpus is the product's
    # compounding asset, and this is the only feedback loop that says which
    # of the 30 hand-written rules are doing real work.
    rules = await database.fetch_all(
        """SELECT rule, count(*) AS n
           FROM airlock_scan_events, jsonb_array_elements_text(matched_rules) AS rule
           GROUP BY rule ORDER BY count(*) DESC, rule LIMIT 10"""
    )
    data = row or {}
    return ScanStats(
        total=int(data.get("total", 0)),
        blocked=int(data.get("blocked", 0)),
        flagged=int(data.get("flagged", 0)),
        allowed=int(data.get("allowed", 0)),
        last_7d=int(data.get("last_7d", 0)),
        top_rules=[{"rule": entry["rule"], "count": int(entry["n"])} for entry in rules],
    )
