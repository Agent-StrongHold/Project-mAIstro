"""PostgreSQL-backed durable event stores (#135).

ADR-086's durable-event stores existed in two flavours, in-memory and SQLite.
The container selects on `db_pool is not None`, and `db_pool` is a *SQLite*
connection — so a deployment on PostgreSQL, the durable system of record per
ADR-082226-5104, got **in-memory** durable events. The event log, the trigger
registry and the invocation history were all lost on restart. "Durable events
that are not durable" is #122's shape, one layer up.

The consequence that outlives a restart is idempotency. `InvocationStore` is
what makes a redelivered event recognisable as already handled; in-memory that
guarantee holds within one process, for one process. Any deployment with more
than one worker did not have it at all — and multi-worker is the only reason to
reach for PostgreSQL here in the first place.

So the interesting store is `PgInvocationStore`, and the interesting property is
the one SQLite never had to answer: two workers racing on the same
`(trigger_id, event_id)` must produce **one** invocation. That is a database
guarantee, not application logic — `ON CONFLICT DO NOTHING` against a composite
primary key — and `tests/events/test_durable_store_conformance.py` runs
concurrent writers against a real server rather than asserting it in a comment.

All three take an `asyncpg.Pool` rather than opening their own, matching
`persistence/pg_*` and letting the container own connection lifetime.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from maistro.events.durable_log import LoggedEvent
from maistro.events.invocations import (
    DEFAULT_LEASE_SECONDS,
    HandlerInvocation,
    InvocationStatus,
)
from maistro.events.trigger_store import TriggerDefinition

if TYPE_CHECKING:
    import asyncpg

#: `BIGSERIAL` rather than SQLite's implicit rowid, and `DOUBLE PRECISION` for
#: `created_at` so the float epoch the dataclasses carry survives the round trip
#: unchanged. A `TIMESTAMPTZ` column would be the better schema and a worse
#: match: it would make the PostgreSQL store return values the other two cannot,
#: which is exactly the divergence one conformance suite exists to prevent.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS event_log (
    id BIGSERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT '',
    entity_id TEXT NOT NULL DEFAULT '',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    source TEXT NOT NULL DEFAULT '',
    created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_event_log_type_id ON event_log(event_type, id);
CREATE INDEX IF NOT EXISTS idx_event_log_created_at ON event_log(created_at);

CREATE TABLE IF NOT EXISTS trigger_definitions (
    trigger_id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    event_pattern TEXT NOT NULL DEFAULT '',
    handler_url TEXT NOT NULL DEFAULT '',
    enabled BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS idx_trigger_enabled ON trigger_definitions(enabled);

CREATE TABLE IF NOT EXISTS handler_invocations (
    trigger_id TEXT NOT NULL,
    event_id BIGINT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    created_at DOUBLE PRECISION NOT NULL,
    -- The dispatch lease. The primary key below makes racing workers converge
    -- on one *row*; it does not stop both of them calling the handler, because
    -- both read that row back in a non-terminal status. `claim` is what settles
    -- ownership, and this column is where it is recorded.
    lease_expires_at DOUBLE PRECISION NOT NULL DEFAULT 0,
    -- The idempotency key, enforced by the database rather than by the caller.
    -- This is what `ON CONFLICT` in `get_or_create` and `claim` relies on, and
    -- what makes two racing workers converge on one row.
    PRIMARY KEY (trigger_id, event_id)
);
CREATE INDEX IF NOT EXISTS idx_invocations_event ON handler_invocations(event_id);
"""


#: Namespace for the bootstrap advisory lock. Arbitrary but fixed: any two
#: processes running `ensure_event_schema` must pick the same number, and no
#: unrelated advisory lock in this database should pick it too.
_SCHEMA_LOCK_KEY = 0x6D61_6973  # "mais"


async def ensure_event_schema(pool: asyncpg.Pool) -> None:
    """Create all three tables. Idempotent, and safe to call concurrently.

    `CREATE TABLE IF NOT EXISTS` is idempotent but **not** serialised: two
    workers that both observe the table as absent can both run the DDL, and one
    loses with `duplicate key value violates unique constraint
    "pg_type_typname_nsp_index"` rather than a clean no-op. That is the failure
    of a bootstrap path in the deployment shape it exists for — several workers
    starting at once is the reason to be on PostgreSQL at all.

    A transaction-scoped advisory lock serialises them. It is released when the
    transaction ends, including by crash, so a worker killed mid-bootstrap does
    not lock the rest out.

    Migration 004 remains the real path for a managed deployment; this is what
    lets tests and single-command dev runs work without one.
    """
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock($1)", _SCHEMA_LOCK_KEY)
        await conn.execute(_SCHEMA)


class PgEventLog:
    """PostgreSQL-backed `EventLogStore`."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def ensure_schema(self) -> None:
        await ensure_event_schema(self._pool)

    async def append(
        self,
        event_type: str,
        *,
        entity_type: str = "",
        entity_id: str = "",
        payload: dict[str, Any] | None = None,
        source: str = "",
    ) -> LoggedEvent:
        created_at = time.time()
        row = await self._pool.fetchrow(
            """INSERT INTO event_log
               (event_type, entity_type, entity_id, payload, source, created_at)
               VALUES ($1,$2,$3,$4::jsonb,$5,$6) RETURNING id""",
            event_type,
            entity_type,
            entity_id,
            json.dumps(payload or {}),
            source,
            created_at,
        )
        return LoggedEvent(
            id=row["id"],
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=dict(payload or {}),
            source=source,
            created_at=created_at,
        )

    async def get(self, event_id: int) -> LoggedEvent | None:
        row = await self._pool.fetchrow(
            "SELECT id, event_type, entity_type, entity_id, payload, source, created_at "
            "FROM event_log WHERE id = $1",
            event_id,
        )
        return _row_to_event(row) if row is not None else None

    async def query(
        self,
        *,
        event_type: str | None = None,
        since: float | None = None,
        until: float | None = None,
        after_id: int = 0,
        limit: int = 100,
    ) -> list[LoggedEvent]:
        # Numbered placeholders built alongside the params, so the two cannot
        # drift out of step the way a hand-maintained `$3` would.
        # (column, operator, value) spelled out. An earlier version derived the
        # operator with `value is since`, which is wrong the moment `since` and
        # `until` hold equal floats — CPython interns them, so `until` would be
        # emitted as `>=` and the upper bound would silently become a second
        # lower bound. Placeholders are numbered from `len(params)` so the SQL
        # and the arguments cannot drift apart.
        conditions = ["id > $1"]
        params: list[Any] = [after_id]
        for column, operator, value in (
            ("event_type", "=", event_type),
            ("created_at", ">=", since),
            ("created_at", "<=", until),
        ):
            if value is None:
                continue
            params.append(value)
            conditions.append(f"{column} {operator} ${len(params)}")
        params.append(limit)
        query = (
            "SELECT id, event_type, entity_type, entity_id, payload, source, created_at "
            "FROM event_log WHERE "
            + " AND ".join(conditions)
            + f" ORDER BY id ASC LIMIT ${len(params)}"
        )
        rows = await self._pool.fetch(query, *params)
        return [_row_to_event(r) for r in rows]


class PgTriggerStore:
    """PostgreSQL-backed `TriggerStore`."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def ensure_schema(self) -> None:
        await ensure_event_schema(self._pool)

    async def add(self, trigger: TriggerDefinition) -> None:
        await self._pool.execute(
            """INSERT INTO trigger_definitions
               (trigger_id, name, event_pattern, handler_url, enabled)
               VALUES ($1,$2,$3,$4,$5)
               ON CONFLICT (trigger_id) DO UPDATE SET
                 name=EXCLUDED.name, event_pattern=EXCLUDED.event_pattern,
                 handler_url=EXCLUDED.handler_url, enabled=EXCLUDED.enabled""",
            trigger.trigger_id,
            trigger.name,
            trigger.event_pattern,
            trigger.handler_url,
            trigger.enabled,
        )

    async def get(self, trigger_id: str) -> TriggerDefinition | None:
        row = await self._pool.fetchrow(
            "SELECT trigger_id, name, event_pattern, handler_url, enabled "
            "FROM trigger_definitions WHERE trigger_id = $1",
            trigger_id,
        )
        return _row_to_trigger(row) if row is not None else None

    async def remove(self, trigger_id: str) -> None:
        await self._pool.execute(
            "DELETE FROM trigger_definitions WHERE trigger_id = $1", trigger_id
        )

    async def list_triggers(self) -> list[TriggerDefinition]:
        rows = await self._pool.fetch(
            "SELECT trigger_id, name, event_pattern, handler_url, enabled FROM trigger_definitions"
        )
        return [_row_to_trigger(r) for r in rows]

    async def get_matching(self, event_type: str) -> list[TriggerDefinition]:
        # Filtered in Python, as the SQLite store does: the glob semantics in
        # `pattern_matches` are per-segment and not expressible in portable SQL.
        # Doing it differently here would make "the same trigger matches" a
        # per-backend question.
        rows = await self._pool.fetch(
            "SELECT trigger_id, name, event_pattern, handler_url, enabled "
            "FROM trigger_definitions WHERE enabled = TRUE"
        )
        return [t for t in (_row_to_trigger(r) for r in rows) if t.matches(event_type)]

    async def set_enabled(self, trigger_id: str, enabled: bool) -> None:
        await self._pool.execute(
            "UPDATE trigger_definitions SET enabled = $1 WHERE trigger_id = $2",
            enabled,
            trigger_id,
        )


class PgInvocationStore:
    """PostgreSQL-backed `InvocationStore` — the idempotency guarantee.

    The composite primary key `(trigger_id, event_id)` is the idempotency key,
    and `ON CONFLICT DO NOTHING` is what makes two workers racing on the same
    redelivered event converge on one row. Not a lock, not a read-then-write:
    both of those have a window, and the window is the bug.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def ensure_schema(self) -> None:
        await ensure_event_schema(self._pool)

    async def get(self, trigger_id: str, event_id: int) -> HandlerInvocation | None:
        row = await self._pool.fetchrow(
            "SELECT trigger_id, event_id, status, attempts, last_error, created_at, "
            "lease_expires_at FROM handler_invocations WHERE trigger_id = $1 AND event_id = $2",
            trigger_id,
            event_id,
        )
        return _row_to_invocation(row) if row is not None else None

    async def get_or_create(self, trigger_id: str, event_id: int) -> HandlerInvocation:
        # One statement. `RETURNING` fires only for the inserting caller, so a
        # NULL row means somebody else won the race — and the follow-up SELECT
        # returns *their* row, which is the whole point: both callers see one
        # invocation with one `created_at`.
        row = await self._pool.fetchrow(
            """INSERT INTO handler_invocations
               (trigger_id, event_id, status, attempts, last_error, created_at, lease_expires_at)
               VALUES ($1,$2,$3,0,'',$4,0)
               ON CONFLICT (trigger_id, event_id) DO NOTHING
               RETURNING trigger_id, event_id, status, attempts, last_error, created_at,
                         lease_expires_at""",
            trigger_id,
            event_id,
            InvocationStatus.PENDING.value,
            time.time(),
        )
        if row is not None:
            return _row_to_invocation(row)
        existing = await self.get(trigger_id, event_id)
        if existing is None:  # pragma: no cover - the conflict proves a row exists
            msg = f"handler_invocations row for ({trigger_id!r}, {event_id}) vanished"
            raise RuntimeError(msg)
        return existing

    async def claim(
        self, trigger_id: str, event_id: int, *, lease_seconds: float = DEFAULT_LEASE_SECONDS
    ) -> HandlerInvocation | None:
        """Hand this (trigger, event) to exactly one worker.

        One statement, so there is no window: the `WHERE` on the `DO UPDATE`
        means a row that is terminal or still leased matches nothing, updates
        nothing, and returns nothing — and the loser gets `None` rather than a
        non-terminal row it would read as permission to dispatch. That
        distinction is the difference between deduplicating bookkeeping and
        deduplicating side effects.
        """
        now = time.time()
        row = await self._pool.fetchrow(
            """INSERT INTO handler_invocations
               (trigger_id, event_id, status, attempts, last_error, created_at, lease_expires_at)
               VALUES ($1,$2,$3,1,'',$4,$5)
               ON CONFLICT (trigger_id, event_id) DO UPDATE SET
                 attempts = handler_invocations.attempts + 1,
                 lease_expires_at = EXCLUDED.lease_expires_at
               WHERE handler_invocations.status <> ALL($6::text[])
                 AND handler_invocations.lease_expires_at <= $4
               RETURNING trigger_id, event_id, status, attempts, last_error, created_at,
                         lease_expires_at""",
            trigger_id,
            event_id,
            InvocationStatus.PENDING.value,
            now,
            now + lease_seconds,
            [InvocationStatus.SUCCESS.value, InvocationStatus.FAILED.value],
        )
        return _row_to_invocation(row) if row is not None else None

    async def save(self, invocation: HandlerInvocation) -> None:
        await self._pool.execute(
            """INSERT INTO handler_invocations
               (trigger_id, event_id, status, attempts, last_error, created_at, lease_expires_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7)
               ON CONFLICT (trigger_id, event_id) DO UPDATE SET
                 status=EXCLUDED.status, attempts=EXCLUDED.attempts,
                 last_error=EXCLUDED.last_error,
                 lease_expires_at=EXCLUDED.lease_expires_at""",
            invocation.trigger_id,
            invocation.event_id,
            invocation.status.value,
            invocation.attempts,
            invocation.last_error,
            invocation.created_at,
            invocation.lease_expires_at,
        )

    async def list_for_event(self, event_id: int) -> list[HandlerInvocation]:
        rows = await self._pool.fetch(
            "SELECT trigger_id, event_id, status, attempts, last_error, created_at, "
            "lease_expires_at FROM handler_invocations WHERE event_id = $1",
            event_id,
        )
        return [_row_to_invocation(r) for r in rows]


def _row_to_event(row: Any) -> LoggedEvent:
    payload = row["payload"]
    return LoggedEvent(
        id=row["id"],
        event_type=row["event_type"],
        entity_type=row["entity_type"] or "",
        entity_id=row["entity_id"] or "",
        # asyncpg returns JSONB as a string unless a codec is registered, so
        # both shapes are accepted rather than depending on pool configuration
        # the store does not own.
        payload=json.loads(payload) if isinstance(payload, str) else dict(payload or {}),
        source=row["source"] or "",
        created_at=row["created_at"],
    )


def _row_to_trigger(row: Any) -> TriggerDefinition:
    return TriggerDefinition(
        trigger_id=row["trigger_id"],
        name=row["name"] or "",
        event_pattern=row["event_pattern"] or "",
        handler_url=row["handler_url"] or "",
        enabled=bool(row["enabled"]),
    )


def _row_to_invocation(row: Any) -> HandlerInvocation:
    return HandlerInvocation(
        trigger_id=row["trigger_id"],
        event_id=int(row["event_id"]),
        status=InvocationStatus(row["status"]),
        attempts=int(row["attempts"]),
        last_error=row["last_error"] or "",
        created_at=float(row["created_at"]),
        lease_expires_at=float(row["lease_expires_at"] or 0),
    )
