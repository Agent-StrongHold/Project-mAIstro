"""Write-behind SQLite persistence for `InMemoryUsageLog`.

`InMemoryUsageLog` is deliberately synchronous (`usage_log.py`'s own docstring:
"the only thing ever read on the hot path") -- every real quota decision
(`cycles_remaining`, a dispatch gate) reads it directly, with no `await` in the
path. Forcing that hot path async to match either existing SQLite convention in
this codebase (`durable_runs/stores.py`'s raw-sqlite3-plus-JSON-blob style, or
`persistence/sqlite_quota.py`'s injected-aiosqlite-plus-typed-columns style)
would violate that design principle for the sake of persistence.

So `SqliteUsageLog` is not a drop-in replacement implementing the same
protocol -- it's a periodic snapshot layer that sits *beside* the live
`InMemoryUsageLog`, following `sqlite_quota.py`'s convention (injected
`aiosqlite.Connection`, plain typed columns, explicit `ensure_schema()`):

    log = InMemoryUsageLog()
    persist = SqliteUsageLog(conn)
    await persist.ensure_schema()
    ...
    await persist.snapshot(log)   # call periodically (every N records / T seconds)
    ...
    # on restart:
    log = await persist.restore()

Each `UsageEvent` carries a generated identity. SQLite enforces that identity
with a unique index, and `snapshot` uses conflict-ignore inserts. This makes a
retry after an ambiguous commit safe even when the in-memory process has not
recorded that the commit completed. A per-instance lock also keeps selection,
insert, commit, and any local bookkeeping one operation for ordinary concurrent
callers; the database identity remains the authority when multiple persistence
instances share a database.

`restore` rehydrates by calling `InMemoryUsageLog.record` for each row in
(timestamp, event-id) order, which reproduces `sum_between`'s (start, end]
boundary semantics exactly rather than re-deriving them.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from maistro.quota.usage_log import InMemoryUsageLog
from maistro.sqlite_schema import serialized_schema_upgrade

if TYPE_CHECKING:
    import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_events (
    event_id TEXT NOT NULL UNIQUE,
    scope_key TEXT NOT NULL,
    timestamp REAL NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    images INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0.0
)
"""

_INDEX = """
CREATE INDEX IF NOT EXISTS idx_usage_events_scope_ts
    ON usage_events (scope_key, timestamp)
"""


class SqliteUsageLog:
    """Periodic write-behind persistence for an `InMemoryUsageLog`.

    Not itself a `UsageSource` / hot-path implementation -- see module
    docstring for why the two stay separate.
    """

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
        self._operation_lock = asyncio.Lock()

    async def ensure_schema(self) -> None:
        """Create the usage_events table and its indexes.

        The event-id column is added and backfilled for databases created by
        the timestamp-only schema. Existing rows receive identities derived
        from their stable SQLite rowids; new rows always come from
        `UsageEvent.event_id`. The upgrade runs through the shared
        `serialized_schema_upgrade` discipline (per-connection asyncio lock +
        ``BEGIN IMMEDIATE``) so concurrent store initializations sharing one
        database cannot interleave; this instance's operation lock keeps the
        migration exclusive of `snapshot`/`restore` on the same connection.
        """
        async with self._operation_lock, serialized_schema_upgrade(self._conn):
            await self._conn.execute(_SCHEMA)
            cursor = await self._conn.execute("PRAGMA table_info(usage_events)")
            columns = await cursor.fetchall()
            if not any(row[1] == "event_id" for row in columns):
                await self._conn.execute("ALTER TABLE usage_events ADD COLUMN event_id TEXT")
            await self._conn.execute(
                "UPDATE usage_events SET event_id = 'legacy:' || rowid WHERE event_id IS NULL"
            )
            await self._conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_usage_events_event_id "
                "ON usage_events (event_id)"
            )
            await self._conn.execute(_INDEX)

    async def snapshot(self, log: InMemoryUsageLog) -> None:
        """Persist the currently retained events, idempotently.

        The live log remains the source of truth for reads. Replaying retained
        events on each flush is intentional: the unique event identity makes
        this safe and avoids a process-local watermark whose update could be
        lost after a successful commit.
        """
        async with self._operation_lock:
            rows = [
                (
                    event.event_id,
                    scope_key,
                    event.timestamp,
                    event.input_tokens,
                    event.output_tokens,
                    event.images,
                    event.cost_usd,
                )
                for scope_key in log.scope_keys()
                for event in log.events_for(scope_key)
            ]
            if not rows:
                return
            await self._conn.executemany(
                "INSERT INTO usage_events "
                "(event_id, scope_key, timestamp, input_tokens, output_tokens, images, cost_usd) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (event_id) DO NOTHING",
                rows,
            )
            await self._conn.commit()

    async def restore(self, *, max_retention_s: float = 86_400.0) -> InMemoryUsageLog:
        """Rehydrate a fresh `InMemoryUsageLog` from persisted events.

        Replays rows through `InMemoryUsageLog.record` in timestamp order --
        the same code path live recording uses -- so `max_retention_s`
        pruning applies identically to a restored log as it would have to a
        continuously-running one, and `sum_between`'s boundary semantics are
        reproduced exactly rather than re-derived.

        Event identities are restored along with their usage values, so a
        later snapshot of the restored log remains idempotent as well.
        """
        log = InMemoryUsageLog(max_retention_s=max_retention_s)
        async with self._operation_lock:
            cursor = await self._conn.execute(
                "SELECT event_id, scope_key, timestamp, input_tokens, output_tokens, images, cost_usd "
                "FROM usage_events ORDER BY timestamp ASC, event_id ASC"
            )
            rows = await cursor.fetchall()
        for event_id, scope_key, timestamp, input_tokens, output_tokens, images, cost_usd in rows:
            log.record(
                scope_key,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                images=images,
                cost_usd=cost_usd,
                now=timestamp,
                event_id=event_id,
            )
        return log


__all__ = ["SqliteUsageLog"]
