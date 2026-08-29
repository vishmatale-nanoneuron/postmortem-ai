from collections.abc import Sequence
from contextlib import asynccontextmanager
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .settings import Settings


class Transaction:
    def __init__(self, connection: Any) -> None:
        self._connection = connection

    async def fetch_one(self, query: str, values: Sequence[Any] = ()) -> dict | None:
        async with self._connection.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(query, values)
            return await cursor.fetchone()

    async def fetch_all(self, query: str, values: Sequence[Any] = ()) -> list[dict]:
        async with self._connection.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(query, values)
            return list(await cursor.fetchall())

    async def execute(self, query: str, values: Sequence[Any] = ()) -> int:
        async with self._connection.cursor() as cursor:
            await cursor.execute(query, values)
            return cursor.rowcount


def _uses_transaction_pooler(database_url: str) -> bool:
    """True when the connection targets a connection pooler in transaction
    mode. Supabase serves that mode on port 6543 -- which is exactly what
    production uses here. Server-side prepared statements are unsafe there:
    a later query can land on a different backend, and psycopg's cached
    statement names then collide with "prepared statement already exists" /
    "prepared statement does not exist" -- intermittent, not reproducible
    per-request, and not tied to any one user, because which backend a
    query lands on is effectively random. Reproduced this exact failure
    signature live against production before finding the missing fix (this
    file's own prior comment named the gap but nothing had closed it yet);
    the mirrored pattern below matches the reference project's
    apps/api/app/database.py, referenced by that comment.
    """
    return ":6543" in database_url


class Database:
    """Thin async wrapper over a psycopg3 connection pool."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pool: AsyncConnectionPool | None = None

    async def open(self) -> None:
        pooled = _uses_transaction_pooler(self._settings.database_url)
        connection_kwargs: dict[str, Any] = {"autocommit": True, "row_factory": dict_row}
        if pooled:
            connection_kwargs["prepare_threshold"] = None
        # A transaction-mode pooler can also route two connections from the
        # same pool to different backends mid-session in ways a larger pool
        # makes more likely to surface -- kept small when pooled, same
        # reasoning the reference project's own pool-size clamp documents.
        max_size = 3 if pooled else 5
        self._pool = AsyncConnectionPool(
            self._settings.database_url,
            min_size=1,
            max_size=max_size,
            kwargs=connection_kwargs,
            open=False,
        )
        await self._pool.open()

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()

    def _require_pool(self) -> AsyncConnectionPool:
        if self._pool is None:
            raise RuntimeError("Database pool is not open -- call open() first")
        return self._pool

    async def fetch_one(self, query: str, values: Sequence[Any] = ()) -> dict | None:
        async with self._require_pool().connection() as connection, connection.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(query, values)
            return await cursor.fetchone()

    async def fetch_all(self, query: str, values: Sequence[Any] = ()) -> list[dict]:
        async with self._require_pool().connection() as connection, connection.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(query, values)
            return list(await cursor.fetchall())

    async def execute(self, query: str, values: Sequence[Any] = ()) -> int:
        async with self._require_pool().connection() as connection, connection.cursor() as cursor:
            await cursor.execute(query, values)
            return cursor.rowcount

    @asynccontextmanager
    async def transaction(self):
        async with self._require_pool().connection() as connection:
            async with connection.transaction():
                yield Transaction(connection)

    @asynccontextmanager
    async def read_only_transaction(self):
        """A real Postgres read-only transaction (not just app-level
        discipline) -- used by the MCP run_read_only_sql tool so a bug in
        the query-validation layer can't turn into a write, even in
        principle, because the database itself refuses one."""
        async with self._require_pool().connection() as connection:
            # psycopg3 async connections require the async setter, not
            # direct attribute assignment -- found via a real failing
            # test, not by inspection ("'read_only' property is
            # read-only on async connections").
            await connection.set_read_only(True)
            try:
                async with connection.transaction():
                    # read-only blocks a write, but not an expensive-to-
                    # compute SELECT (pg_sleep, a runaway join, ...) -- and
                    # the pool is max_size=3 when pooled (production's real
                    # case, per _uses_transaction_pooler above -- this
                    # comment previously said 5, the non-pooled value, which
                    # overstated real production headroom), so one or two
                    # such queries would starve every other request, not
                    # just this tool's caller. SET LOCAL scopes the timeout to
                    # this transaction only; it reverts automatically at
                    # commit/rollback, no manual reset needed.
                    await connection.execute("SET LOCAL statement_timeout = '5s'")
                    yield Transaction(connection)
            finally:
                await connection.set_read_only(False)
