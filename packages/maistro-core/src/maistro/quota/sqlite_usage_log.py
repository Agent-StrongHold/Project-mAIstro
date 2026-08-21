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
scope (a timestamp watermark, not an event count -- `InMemoryUsageLog` prunes
its own deque as it goes, which would silently invalidate a count-based
watermark the moment old events fall off the front). `restore` rehydrates by
calling `InMemoryUsageLog.record` for each row in timestamp order, which
reproduces `sum_between`'s (start, end] boundary semantics exactly rather than
re-deriving them: that logic lives entirely in `sum_between` itself, so
replaying the same events with the same timestamps into a fresh log gives
identical query results.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from maistro.quota.usage_log import InMemoryUsageLog

if TYPE_CHECKING:
    import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_events (
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
        # Per-scope high-water mark: the timestamp of the last event this
        # instance has already written. A VALUE watermark, not an index/count
        # one, because InMemoryUsageLog prunes its own deque over time --
        # a count-based watermark would silently point at the wrong element
        # (or re-persist already-written events) the moment pruning shifts
        # what's at any given index.
        self._last_persisted_ts: dict[str, float] = {}

    async def ensure_schema(self) -> None:
        """Create the usage_events table + its (scope_key, timestamp) index."""
        await self._conn.execute(_SCHEMA)
        await self._conn.execute(_INDEX)
        await self._conn.commit()

    async def snapshot(self, log: InMemoryUsageLog) -> None:
        """Persist events recorded since the last `snapshot` call.

        Best-effort and additive: call this periodically (every N recorded
        events, or every T seconds) rather than synchronously on every
        `record()` -- the in-memory log stays the sole source of truth for
        live reads; this only makes it survive a restart.

        Note: two events for the same scope sharing the exact same
        `timestamp` value can't both be distinguished by a value watermark --
        the second would be skipped as "already persisted." Real timestamps
        (`time.time()`) make this practically negligible; it only matters for
        tests that pass an explicit, repeated `now=`.
        """
        rows: list[tuple[str, float, int, int, int, float]] = []
        new_watermarks: dict[str, float] = {}
        for scope_key in log.scope_keys():
            watermark = self._last_persisted_ts.get(scope_key, float("-inf"))
            new_events = [e for e in log.events_for(scope_key) if e.timestamp > watermark]
            if not new_events:
                continue
            rows.extend(
                (scope_key, e.timestamp, e.input_tokens, e.output_tokens, e.images, e.cost_usd)
                for e in new_events
            )
            new_watermarks[scope_key] = new_events[-1].timestamp

        if not rows:
            return
        await self._conn.executemany(
            "INSERT INTO usage_events "
            "(scope_key, timestamp, input_tokens, output_tokens, images, cost_usd) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        await self._conn.commit()
        self._last_persisted_ts.update(new_watermarks)

    async def restore(self, *, max_retention_s: float = 86_400.0) -> InMemoryUsageLog:
        """Rehydrate a fresh `InMemoryUsageLog` from persisted events.

        Replays rows through `InMemoryUsageLog.record` in timestamp order --
        the same code path live recording uses -- so `max_retention_s`
        pruning applies identically to a restored log as it would have to a
        continuously-running one, and `sum_between`'s boundary semantics are
        reproduced exactly rather than re-derived.

        Also seeds `self._last_persisted_ts` from the rows just read: without
        this, this same instance's next `snapshot()` call would treat every
        restored event as unpersisted (its watermark starts at `-inf`) and
        re-insert all of it -- duplicate rows, inflated usage, understated
        quota headroom after every restart.
        """
        log = InMemoryUsageLog(max_retention_s=max_retention_s)
        cursor = await self._conn.execute(
            "SELECT scope_key, timestamp, input_tokens, output_tokens, images, cost_usd "
            "FROM usage_events ORDER BY timestamp ASC"
        )
        rows = await cursor.fetchall()
        seeded_watermarks: dict[str, float] = {}
        for scope_key, timestamp, input_tokens, output_tokens, images, cost_usd in rows:
            log.record(
                scope_key,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                images=images,
                cost_usd=cost_usd,
                now=timestamp,
            )
            # Rows are timestamp-ascending, so the last write per scope_key
            # naturally ends up holding the max timestamp for that scope.
            seeded_watermarks[scope_key] = timestamp
        self._last_persisted_ts.update(seeded_watermarks)
        return log


__all__ = ["SqliteUsageLog"]
