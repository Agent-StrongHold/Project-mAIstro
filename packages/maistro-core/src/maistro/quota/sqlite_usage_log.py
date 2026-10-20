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

#: Added after the original schema shipped; each is nullable so an upgrade
#: needs no backfill and a legacy row stays honestly empty.
_PROVENANCE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("invocation_id", "TEXT"),
    ("provider", "TEXT"),
    ("billing_cycle", "TEXT"),
    ("usage_reported", "INTEGER"),
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_events (
    event_id TEXT NOT NULL UNIQUE,
    scope_key TEXT NOT NULL,
    timestamp REAL NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    images INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0.0,
    -- Provenance from the canonical Invocation recorder. Nullable on purpose:
    -- legacy callback recording has no identity to record and must not invent
    -- one, which is exactly what `UsageEvent` says about these fields.
    invocation_id TEXT,
    provider TEXT,
    billing_cycle TEXT,
    usage_reported INTEGER
)
"""

_AGGREGATES_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_event_aggregates (
    scope_key TEXT NOT NULL,
    bucket_start REAL NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    images INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0.0,
    PRIMARY KEY (scope_key, bucket_start)
)
"""

_INDEX = """
CREATE INDEX IF NOT EXISTS idx_usage_events_scope_ts
    ON usage_events (scope_key, timestamp)
"""

#: Most raw rows one `purge_expired` call may aggregate and delete.
DEFAULT_PURGE_BATCH = 1_000


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
            await self._conn.execute(_AGGREGATES_SCHEMA)
            cursor = await self._conn.execute("PRAGMA table_info(usage_events)")
            columns = await cursor.fetchall()
            if not any(row[1] == "event_id" for row in columns):
                await self._conn.execute("ALTER TABLE usage_events ADD COLUMN event_id TEXT")
            # Additive, nullable, no backfill: rows written before these
            # columns existed genuinely have no provenance, and a default
            # would be an invented one.
            present = {row[1] for row in columns}
            for column, sql_type in _PROVENANCE_COLUMNS:
                if column not in present:
                    await self._conn.execute(
                        f"ALTER TABLE usage_events ADD COLUMN {column} {sql_type}"
                    )
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
                    event.invocation_id,
                    event.provider,
                    event.billing_cycle,
                    None if event.usage_reported is None else int(event.usage_reported),
                )
                for scope_key in log.scope_keys()
                for event in log.events_for(scope_key)
            ]
            if not rows:
                return
            await self._conn.executemany(
                "INSERT INTO usage_events "
                "(event_id, scope_key, timestamp, input_tokens, output_tokens, images, cost_usd, "
                " invocation_id, provider, billing_cycle, usage_reported) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (event_id) DO NOTHING",
                rows,
            )
            await self._conn.commit()

    async def purge_expired(
        self,
        *,
        before: float,
        limit: int = DEFAULT_PURGE_BATCH,
        legal_hold_scopes: tuple[str, ...] = (),
    ) -> int:
        """Aggregate and delete an idempotent bounded batch of raw events.

        Raw `usage_events` rows are reconciliation evidence with a bounded
        lifetime; the aggregates are the long-lived accounting totals (#325).
        Deleting raw rows therefore must not lose the spend they recorded:
        aggregates are upserted in the same transaction as the deletion, so a
        crash before commit removes neither and a retry adds the same bucket
        exactly once. The horizon is the caller's policy — the in-memory
        enforcement window is shorter than any horizon a retention driver
        should pass, so a cutoff cannot change a current quota decision —
        and ``legal_hold_scopes`` is deliberately an explicit input rather
        than a hidden process-local flag, so every replica applies the same
        hold decision.
        """
        if limit <= 0:
            raise ValueError("limit must be positive")
        if not legal_hold_scopes:
            hold_sql = ""
            hold_params: tuple[object, ...] = ()
        else:
            marks = ",".join("?" for _ in legal_hold_scopes)
            hold_sql = f" AND scope_key NOT IN ({marks})"  # nosec B608 - values bound, identifiers are literal ?
            hold_params = tuple(legal_hold_scopes)
        # The aggregate must cover exactly the batch being deleted -- not
        # every expired row.  Otherwise the rows that survive a bounded
        # delete are aggregated again by the next sweep and the aggregates
        # double-count them.  ``ORDER BY timestamp, rowid`` makes the batch
        # deterministic, so the two statements below select the same rows.
        batch_sql = (
            "SELECT rowid FROM usage_events WHERE timestamp < ?"
            + hold_sql
            + " ORDER BY timestamp, rowid LIMIT ?"
        )
        async with self._operation_lock:
            await self._conn.execute("BEGIN IMMEDIATE")
            try:
                aggregate_sql = (
                    """INSERT INTO usage_event_aggregates
                       (scope_key, bucket_start, input_tokens, output_tokens, images, cost_usd)
                       SELECT scope_key, CAST(timestamp / 86400 AS INTEGER) * 86400 AS bucket_start,
                              SUM(input_tokens), SUM(output_tokens), SUM(images), SUM(cost_usd)
                       FROM usage_events
                       WHERE rowid IN ("""
                    + batch_sql
                    + ")"
                    + """ GROUP BY scope_key, bucket_start
                       ON CONFLICT(scope_key, bucket_start) DO UPDATE SET
                         input_tokens = usage_event_aggregates.input_tokens + excluded.input_tokens,
                         output_tokens = usage_event_aggregates.output_tokens + excluded.output_tokens,
                         images = usage_event_aggregates.images + excluded.images,
                         cost_usd = usage_event_aggregates.cost_usd + excluded.cost_usd"""
                )
                await self._conn.execute(aggregate_sql, (before, *hold_params, limit))
                delete_sql = "DELETE FROM usage_events WHERE rowid IN (" + batch_sql + ")"
                cursor = await self._conn.execute(
                    delete_sql,
                    (before, *hold_params, limit),
                )
                await self._conn.commit()
                return max(cursor.rowcount, 0)
            except BaseException:
                await self._conn.rollback()
                raise

    async def restore(self, *, max_retention_s: float = 86_400.0) -> InMemoryUsageLog:
        """Rehydrate a fresh `InMemoryUsageLog` from persisted events.

        Replays rows through `InMemoryUsageLog.record` in timestamp order --
        the same code path live recording uses -- so `max_retention_s`
        pruning applies identically to a restored log as it would have to a
        continuously-running one, and `sum_between`'s boundary semantics are
        reproduced exactly rather than re-derived.

        Event identities are restored along with their usage values, so a
        later snapshot of the restored log remains idempotent as well -- and
        so is the canonical Invocation provenance the recorder attaches. It
        was being dropped: `snapshot` wrote seven columns and `restore` read
        the same seven, so every SQLite restart silently discarded the
        invocation identity, the provider, the billing cycle and the
        reported/unreported distinction, defeating the durable audit value
        those fields exist for (Codex, #1362).
        """
        log = InMemoryUsageLog(max_retention_s=max_retention_s)
        async with self._operation_lock:
            cursor = await self._conn.execute(
                "SELECT event_id, scope_key, timestamp, input_tokens, output_tokens, images, "
                "cost_usd, invocation_id, provider, billing_cycle, usage_reported "
                "FROM usage_events ORDER BY timestamp ASC, event_id ASC"
            )
            rows = await cursor.fetchall()
        for row in rows:
            (
                event_id,
                scope_key,
                timestamp,
                input_tokens,
                output_tokens,
                images,
                cost_usd,
                invocation_id,
                provider,
                billing_cycle,
                usage_reported,
            ) = row
            log.record(
                scope_key,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                images=images,
                cost_usd=cost_usd,
                now=timestamp,
                event_id=event_id,
                invocation_id=invocation_id,
                provider=provider,
                billing_cycle=billing_cycle,
                usage_reported=None if usage_reported is None else bool(usage_reported),
            )
        return log


__all__ = ["SqliteUsageLog"]
