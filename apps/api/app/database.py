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


class Database:
    """Thin async wrapper over a psycopg3 connection pool.

    Deliberately minimal for this MVP: no pooler-mode detection (Supabase
    transaction-pooler prepared-statement/pool-size quirks) since this runs
    against a single dev Postgres for now. Add that back if this is ever
    deployed behind a transaction pooler -- see the reference project's
    apps/api/app/database.py for the pattern to reuse at that point.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pool: AsyncConnectionPool | None = None

    async def open(self) -> None:
        self._pool = AsyncConnectionPool(
            self._settings.database_url,
            min_size=1,
            max_size=5,
            kwargs={"autocommit": True, "row_factory": dict_row},
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
                    yield Transaction(connection)
            finally:
                await connection.set_read_only(False)
