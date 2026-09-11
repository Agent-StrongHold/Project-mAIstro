"""Durable, append-only event log (ADR-086 / SPEC-070226-b234).

Events are appended before handling; a crash mid-handling replays from the
log on restart rather than dropping the event. The log is immutable: there
is no update or delete API.

Protocol-driven per maistro-core conventions: business logic depends on
``EventLogStore``; concrete implementations are in-memory (tests, homelab)
and SQLite (single-instance durability, aiosqlite — mirrors
``maistro.persistence.sqlite_*`` stores).
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    import aiosqlite

    from maistro.events.bus import Event


@dataclass(frozen=True)
class LoggedEvent:
    """An immutable event row in the durable log.

    ``id`` is a monotonically increasing integer assigned by the store on
    append; it doubles as the replay cursor for the processing loop.
    """

    id: int
    event_type: str
    entity_type: str = ""
    entity_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "event_type": self.event_type,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "payload": self.payload,
            "source": self.source,
            "created_at": self.created_at,
        }


@runtime_checkable
class EventLogStore(Protocol):
    """Append-only durable event log and its replay acknowledgements."""

    async def append(
        self,
        event_type: str,
        *,
        entity_type: str = "",
        entity_id: str = "",
        payload: dict[str, Any] | None = None,
        source: str = "",
    ) -> LoggedEvent:
        """Persist a new event and return it with its assigned id."""
        ...

    async def get(self, event_id: int) -> LoggedEvent | None:
        """Fetch a single event by id."""
        ...

    async def query(
        self,
        *,
        event_type: str | None = None,
        since: float | None = None,
        until: float | None = None,
        after_id: int = 0,
        limit: int = 100,
    ) -> list[LoggedEvent]:
        """Query events ascending by id.

        ``after_id``/``limit`` provide keyset pagination (pass the last id of
        the previous page as ``after_id``); ``event_type``, ``since`` and
        ``until`` filter by type and created_at time window.
        """
        ...

    async def get_replay_cursor(self, consumer_id: str) -> int:
        """Return the last event acknowledged by a durable consumer."""
        ...

    async def acknowledge_replay(self, consumer_id: str, event_id: int) -> int:
        """Durably acknowledge an event, never moving a cursor backwards."""
        ...


def append_from_bus_event(event: Event) -> dict[str, Any]:
    """Map an in-memory bus :class:`~maistro.events.bus.Event` to append() kwargs."""
    return {
        "event_type": event.event_type,
        "entity_type": event.category.value,
        "entity_id": event.correlation_id,
        "payload": dict(event.payload),
        "source": event.source,
    }


class InMemoryEventLog:
    """In-memory :class:`EventLogStore` (tests, dry-run)."""

    def __init__(self) -> None:
        self._events: list[LoggedEvent] = []
        self._next_id = 1
        self._replay_cursors: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def append(
        self,
        event_type: str,
        *,
        entity_type: str = "",
        entity_id: str = "",
        payload: dict[str, Any] | None = None,
        source: str = "",
    ) -> LoggedEvent:
        async with self._lock:
            event = LoggedEvent(
                id=self._next_id,
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                payload=dict(payload or {}),
                source=source,
            )
            self._next_id += 1
            self._events.append(event)
            return event

    async def get(self, event_id: int) -> LoggedEvent | None:
        for e in self._events:
            if e.id == event_id:
                return e
        return None

    async def query(
        self,
        *,
        event_type: str | None = None,
        since: float | None = None,
        until: float | None = None,
        after_id: int = 0,
        limit: int = 100,
    ) -> list[LoggedEvent]:
        result: list[LoggedEvent] = []
        for e in self._events:
            if e.id <= after_id:
                continue
            if event_type is not None and e.event_type != event_type:
                continue
            if since is not None and e.created_at < since:
                continue
            if until is not None and e.created_at > until:
                continue
            result.append(e)
            if len(result) >= limit:
                break
        return result

    async def get_replay_cursor(self, consumer_id: str) -> int:
        return self._replay_cursors.get(consumer_id, 0)

    async def acknowledge_replay(self, consumer_id: str, event_id: int) -> int:
        if event_id < 0:
            raise ValueError("event_id must be non-negative")
        async with self._lock:
            current = self._replay_cursors.get(consumer_id, 0)
            acknowledged = max(current, event_id)
            self._replay_cursors[consumer_id] = acknowledged
            return acknowledged


_SCHEMA = """
CREATE TABLE IF NOT EXISTS event_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT '',
    entity_id TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL DEFAULT '{}',
    source TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_event_log_type_time
    ON event_log (event_type, created_at);
CREATE TABLE IF NOT EXISTS event_replay_cursors (
    consumer_id TEXT PRIMARY KEY,
    event_id INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL
);
"""


class SqliteEventLog:
    """SQLite-backed :class:`EventLogStore` (homelab / single-instance)."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def ensure_schema(self) -> None:
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()

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
        cursor = await self._conn.execute(
            """INSERT INTO event_log
               (event_type, entity_type, entity_id, payload, source, created_at)
               VALUES (?,?,?,?,?,?)""",
            (
                event_type,
                entity_type,
                entity_id,
                json.dumps(payload or {}),
                source,
                created_at,
            ),
        )
        await self._conn.commit()
        row_id = cursor.lastrowid
        assert row_id is not None  # nosec B101 - INSERT always assigns a rowid
        return LoggedEvent(
            id=row_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=dict(payload or {}),
            source=source,
            created_at=created_at,
        )

    async def get(self, event_id: int) -> LoggedEvent | None:
        cursor = await self._conn.execute(
            "SELECT id, event_type, entity_type, entity_id, payload, source, created_at "
            "FROM event_log WHERE id = ?",
            (event_id,),
        )
        row = await cursor.fetchone()
        return self._row_to_event(tuple(row)) if row is not None else None

    async def query(
        self,
        *,
        event_type: str | None = None,
        since: float | None = None,
        until: float | None = None,
        after_id: int = 0,
        limit: int = 100,
    ) -> list[LoggedEvent]:
        conditions = ["id > ?"]
        params: list[Any] = [after_id]
        if event_type is not None:
            conditions.append("event_type = ?")
            params.append(event_type)
        if since is not None:
            conditions.append("created_at >= ?")
            params.append(since)
        if until is not None:
            conditions.append("created_at <= ?")
            params.append(until)
        params.append(limit)
        query = (
            "SELECT id, event_type, entity_type, entity_id, payload, source, created_at "
            "FROM event_log WHERE " + " AND ".join(conditions) + " ORDER BY id ASC LIMIT ?"
        )
        cursor = await self._conn.execute(query, params)
        rows = await cursor.fetchall()
        return [self._row_to_event(tuple(r)) for r in rows]

    async def get_replay_cursor(self, consumer_id: str) -> int:
        cursor = await self._conn.execute(
            "SELECT event_id FROM event_replay_cursors WHERE consumer_id = ?",
            (consumer_id,),
        )
        row = await cursor.fetchone()
        return int(row[0]) if row is not None else 0

    async def acknowledge_replay(self, consumer_id: str, event_id: int) -> int:
        if event_id < 0:
            raise ValueError("event_id must be non-negative")
        now = time.time()
        await self._conn.execute(
            """INSERT INTO event_replay_cursors (consumer_id, event_id, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(consumer_id) DO UPDATE SET
                 event_id = MAX(event_replay_cursors.event_id, excluded.event_id),
                 updated_at = excluded.updated_at""",
            (consumer_id, event_id, now),
        )
        await self._conn.commit()
        return await self.get_replay_cursor(consumer_id)

    @staticmethod
    def _row_to_event(row: tuple[Any, ...]) -> LoggedEvent:
        return LoggedEvent(
            id=row[0],
            event_type=row[1],
            entity_type=row[2] or "",
            entity_id=row[3] or "",
            payload=json.loads(row[4] or "{}"),
            source=row[5] or "",
            created_at=row[6],
        )
