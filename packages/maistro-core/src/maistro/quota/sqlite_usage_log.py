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

`snapshot` only ever appends events newer than the last one it persisted per
scope. Stable event identities preserve events sharing a timestamp and make
overlapping flushes and crash/retry idempotent. `restore` rehydrates by calling
`InMemoryUsageLog.record` for each row in timestamp order, which reproduces
`sum_between`'s (start, end] boundary semantics exactly rather than re-deriving
them.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from maistro.persistence.sqlite_schema import begin_schema_upgrade
from maistro.quota.usage_log import InMemoryUsageLog

if TYPE_CHECKING:
    import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_events (
    event_id TEXT,
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
        self._persisted_event_ids: set[str] = set()
        # A connection is shared by several quota users in one process. The
        # lock prevents overlapping snapshots from racing before SQLite gets
        # to the unique event identity; the unique index covers other
        # processes and crash/retry after commit.
        self._snapshot_lock = asyncio.Lock()

    async def ensure_schema(self) -> None:
        """Create or upgrade usage_events without losing existing events."""
        await begin_schema_upgrade(self._conn)
        await self._conn.execute(_SCHEMA)
        cursor = await self._conn.execute("PRAGMA table_info(usage_events)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "event_id" not in columns:
            await self._conn.execute("ALTER TABLE usage_events ADD COLUMN event_id TEXT")
            await self._conn.execute(
                "UPDATE usage_events SET event_id = 'legacy:' || rowid WHERE event_id IS NULL"
            )
        await self._conn.execute(_INDEX)
        await self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_usage_events_event_id ON usage_events (event_id)"
        )
        await self._conn.execute("PRAGMA busy_timeout = 5000")
        await self._conn.commit()

    async def snapshot(self, log: InMemoryUsageLog) -> None:
        """Persist events recorded since the last `snapshot` call.

        Best-effort and additive: call this periodically (every N recorded
        events, or every T seconds) rather than synchronously on every
        `record()` -- the in-memory log stays the sole source of truth for
        live reads; this only makes it survive a restart.
        """
        async with self._snapshot_lock:
            rows: list[tuple[str, str, float, int, int, int, float]] = []
            for scope_key in log.scope_keys():
                for event in log.events_for(scope_key):
                    if event.event_id in self._persisted_event_ids:
                        continue
                    rows.append(
                        (
                            event.event_id,
                            scope_key,
                            event.timestamp,
                            event.input_tokens,
                            event.output_tokens,
                            event.images,
                            event.cost_usd,
                        )
                    )

            if not rows:
                return
            await self._conn.executemany(
                "INSERT OR IGNORE INTO usage_events "
                "(event_id, scope_key, timestamp, input_tokens, output_tokens, images, cost_usd) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            await self._conn.commit()
            self._persisted_event_ids.update(row[0] for row in rows)

    async def restore(self, *, max_retention_s: float = 86_400.0) -> InMemoryUsageLog:
        """Rehydrate a fresh `InMemoryUsageLog` from persisted events.

        Replays rows through `InMemoryUsageLog.record` in timestamp order --
        the same code path live recording uses -- so `max_retention_s`
        pruning applies identically to a restored log as it would have to a
        continuously-running one, and `sum_between`'s boundary semantics are
        reproduced exactly rather than re-derived.

        It also seeds the event-id set from the rows just read, so this same
        instance's next `snapshot()` call is a no-op rather than a duplicate
        insert after a restart.
        """
        log = InMemoryUsageLog(max_retention_s=max_retention_s)
        cursor = await self._conn.execute(
            "SELECT event_id, rowid, scope_key, timestamp, input_tokens, output_tokens, images, cost_usd "
            "FROM usage_events ORDER BY timestamp ASC, rowid ASC"
        )
        rows = await cursor.fetchall()
        for (
            event_id,
            rowid,
            scope_key,
            timestamp,
            input_tokens,
            output_tokens,
            images,
            cost_usd,
        ) in rows:
            # A legacy row receives a stable identity during restore; current
            # schemas populate it at insert time.
            stable_id = str(event_id or f"legacy:{rowid}")
            log.record(
                scope_key,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                images=images,
                cost_usd=cost_usd,
                now=timestamp,
                event_id=stable_id,
            )
            self._persisted_event_ids.add(stable_id)
        return log


__all__ = ["SqliteUsageLog"]
