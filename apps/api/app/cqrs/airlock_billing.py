"""Command/query split for Airlock's keys and credits (migration 0032).

Three things live here and nowhere else:

- How a key is minted, stored and resolved. The secret is generated once,
  returned once, and only its SHA-256 is kept; there is no handler that can
  read a key back, because the table has nothing to read.
- How a credit is spent. `handle_debit_credit` is the one place a balance
  goes down, and it is atomic by construction (a conditional UPDATE on the
  balance row, not a read-then-write) so two scans racing for the last
  credit cannot both win. Exactly the double-spend that a "check balance,
  then scan, then decrement" sequence would allow.
- How credits are granted. `handle_grant_credits` is called from the
  founder's approve flow and the founder's manual grant, and from nothing a
  client can reach.

The scanner routes (api/v1/airlock.py) use these and add nothing of their
own to the money path -- which is the point of the split: a route can
compute a verdict, but it cannot invent a credit or forget to charge one.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass

from ..database import Database, Transaction
from .airlock_policy import DEFAULT_POLICY, POLICY_COLUMNS, Policy, policy_from_row

KEY_PREFIX = "alk_"
# 32 random bytes -> 43 url-safe characters. Far beyond brute force, and
# the reason a fast hash is safe: SHA-256 of a 256-bit secret has no
# dictionary to be attacked with, unlike a password.
KEY_SECRET_BYTES = 32
# Enough to tell keys apart in a list; not enough to guess the rest.
DISPLAY_PREFIX_CHARS = 12

MAX_ACTIVE_KEYS_PER_USER = 10

# last_used_at is a courtesy ("is this key still in use?"), not an audit
# field, so it is written at most once a minute per key rather than on every
# scan -- one fewer write on the hot path.
LAST_USED_WRITE_INTERVAL_MS = 60 * 1000


class InsufficientCredits(Exception):
    """Raised by handle_debit_credit when the balance is already zero. The
    route turns it into a 402; nothing else should catch it."""


class TooManyKeys(Exception):
    pass


def hash_key(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _now_ms() -> int:
    return int(time.time() * 1000)


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IssueApiKeyCommand:
    user_id: str
    label: str


@dataclass(frozen=True)
class IssuedApiKey:
    id: str
    label: str
    prefix: str
    created_at: int
    # The full key. Present on this dataclass only, returned from
    # handle_issue_api_key only, and shown to the customer once.
    secret: str


async def handle_issue_api_key(database: Database, command: IssueApiKeyCommand) -> IssuedApiKey:
    secret = KEY_PREFIX + secrets.token_urlsafe(KEY_SECRET_BYTES)
    prefix = secret[:DISPLAY_PREFIX_CHARS]
    now = _now_ms()
    async with database.transaction() as tx:
        # The cap is checked under the same per-user advisory lock the
        # rate limiters use, so a burst of concurrent "create key" requests
        # cannot each see nine keys and each mint a tenth.
        await tx.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{command.user_id}:airlock_keys",))
        row = await tx.fetch_one(
            "SELECT count(*) AS n FROM airlock_api_keys WHERE user_id=%s AND revoked_at IS NULL",
            (command.user_id,),
        )
        if row and int(row["n"]) >= MAX_ACTIVE_KEYS_PER_USER:
            raise TooManyKeys()
        inserted = await tx.fetch_one(
            """INSERT INTO airlock_api_keys (user_id, label, prefix, key_hash, created_at)
               VALUES (%s, %s, %s, %s, %s)
               RETURNING id::text""",
            (command.user_id, command.label.strip()[:80], prefix, hash_key(secret), now),
        )
    assert inserted is not None
    return IssuedApiKey(
        id=inserted["id"], label=command.label.strip()[:80], prefix=prefix, created_at=now, secret=secret
    )


@dataclass(frozen=True)
class RevokeApiKeyCommand:
    user_id: str
    key_id: str


async def handle_revoke_api_key(database: Database, command: RevokeApiKeyCommand) -> bool:
    """True if a key was revoked; False if there was no active key with that
    id for this user. The user_id in the WHERE is the ownership check --
    another account's key id is simply "not found", never "forbidden"."""
    updated = await database.execute(
        "UPDATE airlock_api_keys SET revoked_at=%s WHERE id=%s AND user_id=%s AND revoked_at IS NULL",
        (_now_ms(), command.key_id, command.user_id),
    )
    return bool(updated)


@dataclass(frozen=True)
class ApiKeySummary:
    id: str
    label: str
    prefix: str
    created_at: int
    last_used_at: int | None
    revoked_at: int | None


async def handle_api_keys_query(database: Database, user_id: str) -> list[ApiKeySummary]:
    rows = await database.fetch_all(
        """SELECT id::text, label, prefix, created_at, last_used_at, revoked_at
           FROM airlock_api_keys WHERE user_id=%s ORDER BY created_at DESC LIMIT 50""",
        (user_id,),
    )
    return [ApiKeySummary(**row) for row in rows]


@dataclass(frozen=True)
class ResolvedKey:
    id: str
    user_id: str
    # The account's policy, fetched in the same query as the key so a scan
    # does not pay a round trip for it. Defaults when the account never
    # set one.
    policy: Policy = DEFAULT_POLICY


async def resolve_api_key(database: Database, secret: str) -> ResolvedKey | None:
    """The secret to (key, account, policy) lookup the scanner authenticates
    with. A revoked key resolves to None exactly like a wrong one; the
    caller cannot tell which, and should not be able to."""
    if not secret.startswith(KEY_PREFIX) or len(secret) > 128:
        return None
    row = await database.fetch_one(
        f"""SELECT k.id::text, k.user_id::text, k.last_used_at, {POLICY_COLUMNS}
            FROM airlock_api_keys k
            LEFT JOIN airlock_policies p ON p.user_id = k.user_id
            WHERE k.key_hash=%s AND k.revoked_at IS NULL""",
        (hash_key(secret),),
    )
    if not row:
        return None
    now = _now_ms()
    last = row["last_used_at"]
    if last is None or now - int(last) > LAST_USED_WRITE_INTERVAL_MS:
        await database.execute("UPDATE airlock_api_keys SET last_used_at=%s WHERE id=%s", (now, row["id"]))
    return ResolvedKey(id=row["id"], user_id=row["user_id"], policy=policy_from_row(row))


# ---------------------------------------------------------------------------
# Credits
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GrantCreditsCommand:
    user_id: str
    credits: int
    reason: str  # 'purchase' | 'grant' | 'refund' | 'adjustment'
    reference: str | None = None


async def handle_grant_credits(database: Database | Transaction, command: GrantCreditsCommand) -> int:
    """Adds credits and returns the new balance. Accepts a Transaction so the
    founder's approve flow can grant in the same transaction that marks the
    claim approved -- a grant with no approved claim, or an approved claim
    with no grant, are both states this product must never be in."""
    if command.credits <= 0:
        raise ValueError("credits must be positive")
    now = _now_ms()
    row = await database.fetch_one(
        """INSERT INTO airlock_credit_balances (user_id, balance, updated_at)
           VALUES (%s, %s, %s)
           ON CONFLICT (user_id) DO UPDATE
             SET balance = airlock_credit_balances.balance + EXCLUDED.balance, updated_at = EXCLUDED.updated_at
           RETURNING balance""",
        (command.user_id, command.credits, now),
    )
    await database.execute(
        """INSERT INTO airlock_credit_ledger (user_id, api_key_id, delta, reason, reference, created_at)
           VALUES (%s, NULL, %s, %s, %s, %s)""",
        (command.user_id, command.credits, command.reason, command.reference, now),
    )
    assert row is not None
    return int(row["balance"])


@dataclass(frozen=True)
class DebitCreditCommand:
    user_id: str
    reason: str  # 'scan' | 'deep_scan' | 'egress'
    api_key_id: str | None = None
    # A plain scan is 1; a deep scan is 1 + DEEP_SCAN_EXTRA_CREDITS. Always
    # taken in one debit so a caller either affords the whole call or none
    # of it.
    credits: int = 1


async def handle_debit_credit(database: Database, command: DebitCreditCommand) -> int:
    """Spends `credits` and returns the balance after. Raises
    InsufficientCredits -- and writes nothing -- when the balance is short.

    The conditional UPDATE is the whole concurrency story: Postgres takes a
    row lock on the balance row, so concurrent debits for one account
    serialise, and each one re-evaluates `balance >= 1` against the value
    the previous one left. There is no window in which two callers both
    observe 1 and both decrement. The ledger row is written in the same
    transaction, so a balance can never move without a line explaining it.
    """
    if command.credits <= 0:
        raise ValueError("credits must be positive")
    now = _now_ms()
    # One statement, one round trip. The debit and its ledger line are a
    # data-modifying CTE: the INSERT only happens when the UPDATE matched
    # (balance was sufficient), and both are atomic as a single statement
    # under autocommit -- no BEGIN/COMMIT round trips. This was four round
    # trips as an explicit transaction; with the database on another
    # continent from the function (Mumbai vs US East, ~200 ms each) that
    # was most of a scan's latency.
    row = await database.fetch_one(
        """WITH debited AS (
               UPDATE airlock_credit_balances SET balance = balance - %s, updated_at = %s
               WHERE user_id = %s AND balance >= %s
               RETURNING user_id, balance
           ),
           logged AS (
               INSERT INTO airlock_credit_ledger (user_id, api_key_id, delta, reason, reference, created_at)
               SELECT user_id, %s, %s, %s, NULL, %s FROM debited
           )
           SELECT balance FROM debited""",
        (
            command.credits,
            now,
            command.user_id,
            command.credits,
            command.api_key_id,
            -command.credits,
            command.reason,
            now,
        ),
    )
    if row is None:
        raise InsufficientCredits()
    return int(row["balance"])


@dataclass(frozen=True)
class CreditBalance:
    balance: int
    purchased_total: int
    used_total: int
    used_last_30d: int


THIRTY_DAYS_MS = 30 * 24 * 60 * 60 * 1000


async def handle_credit_balance_query(database: Database, user_id: str, *, now_ms: int | None = None) -> CreditBalance:
    cutoff = (now_ms if now_ms is not None else _now_ms()) - THIRTY_DAYS_MS
    balance_row = await database.fetch_one(
        "SELECT balance FROM airlock_credit_balances WHERE user_id=%s", (user_id,)
    )
    # A refund is not a purchase and a refunded charge was not a use: the
    # deep-scan refund (+4 after a -5 when Gemini was unavailable) nets
    # against usage, so "used" is what the customer actually consumed and
    # "purchased" is what they actually bought or were granted. Seen in the
    # first end-to-end run as "bought 10,004, used 6" for one refunded call.
    totals = await database.fetch_one(
        """SELECT coalesce(sum(delta) FILTER (WHERE delta > 0 AND reason <> 'refund'), 0) AS purchased,
                  coalesce(-sum(delta) FILTER (WHERE delta < 0 OR reason = 'refund'), 0) AS used,
                  coalesce(-sum(delta) FILTER (WHERE (delta < 0 OR reason = 'refund') AND created_at >= %s), 0)
                    AS used_30d
           FROM airlock_credit_ledger WHERE user_id=%s""",
        (cutoff, user_id),
    )
    data = totals or {}
    return CreditBalance(
        balance=int(balance_row["balance"]) if balance_row else 0,
        purchased_total=int(data.get("purchased", 0)),
        used_total=int(data.get("used", 0)),
        used_last_30d=int(data.get("used_30d", 0)),
    )


@dataclass(frozen=True)
class LedgerEntry:
    delta: int
    reason: str
    reference: str | None
    key_prefix: str | None
    created_at: int


async def handle_ledger_query(database: Database, user_id: str, *, limit: int = 50) -> list[LedgerEntry]:
    """The statement: purchases, grants and (collapsed per day, per key) the
    scans that spent them. Individual -1 rows would drown the purchases
    they sit between, so debits are rolled up into one line per key per
    day with the day's total in `delta`."""
    rows = await database.fetch_all(
        """SELECT * FROM (
             SELECT l.delta, l.reason, l.reference, k.prefix AS key_prefix, l.created_at
             FROM airlock_credit_ledger l
             LEFT JOIN airlock_api_keys k ON k.id = l.api_key_id
             WHERE l.user_id=%s AND l.delta > 0
             UNION ALL
             SELECT sum(l.delta)::int AS delta,
                    'usage' AS reason,
                    NULL AS reference,
                    k.prefix AS key_prefix,
                    max(l.created_at) AS created_at
             FROM airlock_credit_ledger l
             LEFT JOIN airlock_api_keys k ON k.id = l.api_key_id
             WHERE l.user_id=%s AND l.delta < 0
             GROUP BY (l.created_at / 86400000), k.prefix
           ) AS statement
           ORDER BY created_at DESC LIMIT %s""",
        (user_id, user_id, limit),
    )
    return [LedgerEntry(**row) for row in rows]


@dataclass(frozen=True)
class UsageDay:
    day: str
    key_prefix: str | None
    scans: int
    deep_scans: int
    egress: int
    refunds: int
    credits: int


DAY_MS = 24 * 60 * 60 * 1000


async def handle_usage_query(database: Database, user_id: str, *, days: int = 30, now_ms: int | None = None) -> list[UsageDay]:
    """Calls per UTC day per key. Only the metered lines (debits and their
    refunds) -- a purchase is not usage. `credits` is what the day netted
    out to, so a deep scan whose second opinion was refunded counts as 1."""
    now = now_ms if now_ms is not None else _now_ms()
    since = now - days * DAY_MS
    rows = await database.fetch_all(
        """SELECT to_char(to_timestamp(l.created_at / 1000.0) AT TIME ZONE 'UTC', 'YYYY-MM-DD') AS day,
                  k.prefix AS key_prefix,
                  count(*) FILTER (WHERE l.reason = 'scan')::int AS scans,
                  count(*) FILTER (WHERE l.reason = 'deep_scan')::int AS deep_scans,
                  count(*) FILTER (WHERE l.reason = 'egress')::int AS egress,
                  count(*) FILTER (WHERE l.reason = 'refund')::int AS refunds,
                  -sum(l.delta)::int AS credits
           FROM airlock_credit_ledger l
           LEFT JOIN airlock_api_keys k ON k.id = l.api_key_id
           WHERE l.user_id=%s AND l.created_at >= %s
             AND l.reason IN ('scan', 'deep_scan', 'egress', 'refund')
           GROUP BY 1, 2
           ORDER BY 1 DESC, 2 NULLS LAST""",
        (user_id, since),
    )
    return [UsageDay(**row) for row in rows]


@dataclass(frozen=True)
class LedgerLine:
    delta: int
    reason: str
    reference: str | None
    key_prefix: str | None
    created_at: int


async def handle_ledger_lines_query(
    database: Database, user_id: str, *, days: int = 90, limit: int = 50_000, now_ms: int | None = None
) -> list[LedgerLine]:
    """Every line, unrolled, newest first -- the export. The statement
    (handle_ledger_query) rolls debits up per day; an export must not."""
    now = now_ms if now_ms is not None else _now_ms()
    since = now - days * DAY_MS
    rows = await database.fetch_all(
        """SELECT l.delta, l.reason, l.reference, k.prefix AS key_prefix, l.created_at
           FROM airlock_credit_ledger l
           LEFT JOIN airlock_api_keys k ON k.id = l.api_key_id
           WHERE l.user_id=%s AND l.created_at >= %s
           ORDER BY l.created_at DESC
           LIMIT %s""",
        (user_id, since, limit),
    )
    return [LedgerLine(**row) for row in rows]


# ---------------------------------------------------------------------------
# The owner's view. Whether Airlock is earning is a question the founder
# answers from the dashboard, so the numbers live here next to the ledger
# they come from rather than being re-derived in founder.py.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AirlockBusinessStats:
    credits_sold_total: int  # reason='purchase' -- paid packs, approved
    credits_granted_total: int  # grant/refund/adjustment -- not revenue
    credits_used_total: int
    credits_used_last_7d: int
    credits_outstanding: int  # sum of balances: prepaid but not yet spent
    active_keys: int
    accounts_with_balance: int
    revenue_by_currency: list[dict]  # approved Airlock claims: {"currency", "amount", "claims"}


SEVEN_DAYS_MS = 7 * 24 * 60 * 60 * 1000


async def handle_airlock_business_stats_query(database: Database, *, now_ms: int | None = None) -> AirlockBusinessStats:
    cutoff = (now_ms if now_ms is not None else _now_ms()) - SEVEN_DAYS_MS
    ledger = await database.fetch_one(
        """SELECT coalesce(sum(delta) FILTER (WHERE reason = 'purchase'), 0) AS sold,
                  coalesce(sum(delta) FILTER (WHERE reason IN ('grant', 'refund', 'adjustment') AND delta > 0), 0)
                    AS granted,
                  coalesce(-sum(delta) FILTER (WHERE delta < 0), 0) AS used,
                  coalesce(-sum(delta) FILTER (WHERE delta < 0 AND created_at >= %s), 0) AS used_7d
           FROM airlock_credit_ledger""",
        (cutoff,),
    )
    balances = await database.fetch_one(
        "SELECT coalesce(sum(balance), 0) AS outstanding, count(*) FILTER (WHERE balance > 0) AS funded"
        " FROM airlock_credit_balances"
    )
    keys = await database.fetch_one("SELECT count(*) AS n FROM airlock_api_keys WHERE revoked_at IS NULL")
    revenue = await database.fetch_all(
        """SELECT currency, sum(amount_inr) AS amount, count(*) AS claims
           FROM payment_claims WHERE product = 'airlock' AND status = 'approved'
           GROUP BY currency ORDER BY currency"""
    )
    data = ledger or {}
    return AirlockBusinessStats(
        credits_sold_total=int(data.get("sold", 0)),
        credits_granted_total=int(data.get("granted", 0)),
        credits_used_total=int(data.get("used", 0)),
        credits_used_last_7d=int(data.get("used_7d", 0)),
        credits_outstanding=int((balances or {}).get("outstanding", 0)),
        active_keys=int((keys or {}).get("n", 0)),
        accounts_with_balance=int((balances or {}).get("funded", 0)),
        revenue_by_currency=[
            {"currency": r["currency"], "amount": int(r["amount"]), "claims": int(r["claims"])} for r in revenue
        ],
    )
