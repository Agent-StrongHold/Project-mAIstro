"""PostgreSQL persistence for ADR-086's durable events (#135).

The durable twins of `SqliteEventLog`, `SqliteTriggerStore` and
`SqliteInvocationStore`, against the system of record ADR-082226-5104 names.
Before this the container selected between in-memory and SQLite on "is a SQLite
connection open", so a PostgreSQL deployment got in-memory durable events — the
event log, the trigger registry and the invocation history all lost on restart.

`PgInvocationStore` is the one that carries weight. `InvocationStore` is what
makes event handling idempotent: it is how a redelivered event is recognised as
already handled. In-memory that held only within one process lifetime and only
for one process, so any deployment with more than one worker did not have it at
all. Here the composite primary key enforces it across every worker sharing the
database, which is the point of moving it.

Payloads are JSONB and come back as dicts, because the pool registers a JSON
codec (`maistro.persistence._register_json_codecs`) — so unlike the SQLite
stores these do not `json.dumps`/`loads` by hand.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from maistro.events.durable_log import LoggedEvent
from maistro.events.invocations import HandlerInvocation, InvocationStatus
from maistro.events.trigger_store import TriggerDefinition

if TYPE_CHECKING:  # pragma: no cover - typing only
    import asyncpg

_EVENT_COLUMNS = "id, event_type, entity_type, entity_id, payload, source, created_at"
_TRIGGER_COLUMNS = "trigger_id, name, event_pattern, handler_url, enabled"
_INVOCATION_COLUMNS = "trigger_id, event_id, status, attempts, last_error, created_at"


def _to_event(row: Any) -> LoggedEvent:
    return LoggedEvent(
        id=int(row["id"]),
        event_type=str(row["event_type"]),
        entity_type=str(row["entity_type"] or ""),
        entity_id=str(row["entity_id"] or ""),
        payload=dict(row["payload"] or {}),
        source=str(row["source"] or ""),
        created_at=float(row["created_at"]),
    )


def _to_trigger(row: Any) -> TriggerDefinition:
    return TriggerDefinition(
        trigger_id=str(row["trigger_id"]),
        name=str(row["name"] or ""),
        event_pattern=str(row["event_pattern"] or ""),
        handler_url=str(row["handler_url"] or ""),
        enabled=bool(row["enabled"]),
    )


def _to_invocation(row: Any) -> HandlerInvocation:
    return HandlerInvocation(
        trigger_id=str(row["trigger_id"]),
        event_id=int(row["event_id"]),
        status=InvocationStatus(str(row["status"])),
        attempts=int(row["attempts"]),
        last_error=str(row["last_error"] or ""),
        created_at=float(row["created_at"]),
    )


class PgEventLog:
    """PostgreSQL-backed append-only event log."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def append(
        self,
        event_type: str,
        *,
        entity_type: str = "",
        entity_id: str = "",
        payload: dict[str, Any] | None = None,
        source: str = "",
    ) -> LoggedEvent:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""INSERT INTO event_log
                    (event_type, entity_type, entity_id, payload, source, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    RETURNING {_EVENT_COLUMNS}""",  # nosec B608 - fixed column list
                event_type,
                entity_type,
                entity_id,
                dict(payload or {}),
                source,
                time.time(),
            )
        return _to_event(row)

    async def get(self, event_id: int) -> LoggedEvent | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_EVENT_COLUMNS} FROM event_log WHERE id = $1",  # nosec B608
                event_id,
            )
        return _to_event(row) if row is not None else None

    async def query(
        self,
        *,
        event_type: str | None = None,
        since: float | None = None,
        until: float | None = None,
        after_id: int = 0,
        limit: int = 100,
    ) -> list[LoggedEvent]:
        # Placeholders are built positionally rather than interpolated, so the
        # filter values never reach the SQL string.
        conditions = ["id > $1"]
        params: list[Any] = [after_id]
        for value, clause in (
            (event_type, "event_type = "),
            (since, "created_at >= "),
            (until, "created_at <= "),
        ):
            if value is not None:
                params.append(value)
                conditions.append(f"{clause}${len(params)}")
        params.append(limit)
        sql = (
            f"SELECT {_EVENT_COLUMNS} FROM event_log WHERE "  # nosec B608
            + " AND ".join(conditions)
            + f" ORDER BY id ASC LIMIT ${len(params)}"
        )
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [_to_event(row) for row in rows]


class PgTriggerStore:
    """PostgreSQL-backed store of durable trigger definitions."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def add(self, trigger: TriggerDefinition) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO trigger_definitions
                   (trigger_id, name, event_pattern, handler_url, enabled)
                   VALUES ($1, $2, $3, $4, $5)
                   ON CONFLICT (trigger_id) DO UPDATE SET
                     name = EXCLUDED.name,
                     event_pattern = EXCLUDED.event_pattern,
                     handler_url = EXCLUDED.handler_url,
                     enabled = EXCLUDED.enabled""",
                trigger.trigger_id,
                trigger.name,
                trigger.event_pattern,
                trigger.handler_url,
                trigger.enabled,
            )

    async def get(self, trigger_id: str) -> TriggerDefinition | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_TRIGGER_COLUMNS} FROM trigger_definitions WHERE trigger_id = $1",  # nosec B608
                trigger_id,
            )
        return _to_trigger(row) if row is not None else None

    async def remove(self, trigger_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("DELETE FROM trigger_definitions WHERE trigger_id = $1", trigger_id)

    async def list_triggers(self) -> list[TriggerDefinition]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_TRIGGER_COLUMNS} FROM trigger_definitions"  # nosec B608
            )
        return [_to_trigger(row) for row in rows]

    async def get_matching(self, event_type: str) -> list[TriggerDefinition]:
        """Enabled triggers whose pattern matches, filtered in Python.

        Glob semantics are not expressible in portable SQL, so the database
        narrows to `enabled` and the pattern match happens here — the same split
        the SQLite store makes, so the two cannot disagree about what "matches"
        means.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_TRIGGER_COLUMNS} FROM trigger_definitions WHERE enabled"  # nosec B608
            )
        return [trigger for trigger in map(_to_trigger, rows) if trigger.matches(event_type)]

    async def set_enabled(self, trigger_id: str, enabled: bool) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE trigger_definitions SET enabled = $2 WHERE trigger_id = $1",
                trigger_id,
                enabled,
            )


class PgInvocationStore:
    """PostgreSQL-backed invocation store — the idempotency guarantee.

    `(trigger_id, event_id)` is the primary key, so two workers handed the same
    event converge on one row rather than each starting its own handler run.
    That is the property in-memory could not offer across processes, and the
    reason this store exists.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get(self, trigger_id: str, event_id: int) -> HandlerInvocation | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""SELECT {_INVOCATION_COLUMNS} FROM handler_invocations
                    WHERE trigger_id = $1 AND event_id = $2""",  # nosec B608
                trigger_id,
                event_id,
            )
        return _to_invocation(row) if row is not None else None

    async def get_or_create(self, trigger_id: str, event_id: int) -> HandlerInvocation:
        """Return the existing invocation, or create a pending one — atomically.

        The `DO UPDATE SET trigger_id = EXCLUDED.trigger_id` looks pointless and
        is load-bearing: `ON CONFLICT DO NOTHING` returns no row on conflict, so
        the loser of a race would have to SELECT again and could still find
        nothing if the winner's transaction had not committed. A no-op update
        makes the statement always RETURN the surviving row, in one round trip
        that cannot observe a gap.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""INSERT INTO handler_invocations
                    (trigger_id, event_id, status, attempts, last_error, created_at)
                    VALUES ($1, $2, $3, 0, '', $4)
                    ON CONFLICT (trigger_id, event_id)
                    DO UPDATE SET trigger_id = EXCLUDED.trigger_id
                    RETURNING {_INVOCATION_COLUMNS}""",  # nosec B608
                trigger_id,
                event_id,
                InvocationStatus.PENDING.value,
                time.time(),
            )
        return _to_invocation(row)

    async def save(self, invocation: HandlerInvocation) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO handler_invocations
                   (trigger_id, event_id, status, attempts, last_error, created_at)
                   VALUES ($1, $2, $3, $4, $5, $6)
                   ON CONFLICT (trigger_id, event_id) DO UPDATE SET
                     status = EXCLUDED.status,
                     attempts = EXCLUDED.attempts,
                     last_error = EXCLUDED.last_error""",
                invocation.trigger_id,
                invocation.event_id,
                invocation.status.value,
                invocation.attempts,
                invocation.last_error,
                invocation.created_at,
            )

    async def list_for_event(self, event_id: int) -> list[HandlerInvocation]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""SELECT {_INVOCATION_COLUMNS} FROM handler_invocations
                    WHERE event_id = $1""",  # nosec B608
                event_id,
            )
        return [_to_invocation(row) for row in rows]


__all__ = ["PgEventLog", "PgInvocationStore", "PgTriggerStore"]
