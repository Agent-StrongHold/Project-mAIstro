"""Transactional outbox for canonical event publication.

A caller stages an EventEnvelope on the same SQLite connection and transaction as
its domain-state mutation. Committing that transaction makes both durable; rolling
it back makes neither durable. A separate publisher drains committed outbox rows
to the canonical EventStore. Publication is at-least-once, while stable event IDs
make logical delivery to the canonical store idempotent.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from maistro.events.envelope import EventEnvelope, EventStore, correlated
from maistro.observability.correlation import detached_execution_context

if TYPE_CHECKING:
    import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS canonical_event_outbox (
    outbox_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    event_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    published_at REAL
);
CREATE INDEX IF NOT EXISTS idx_canonical_event_outbox_pending
    ON canonical_event_outbox (outbox_id) WHERE published_at IS NULL;
"""


class SqliteEventOutbox:
    """SQLite transactional staging and retry-safe event publication."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def ensure_schema(self) -> None:
        """Create the outbox schema and commit the schema transaction."""
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()

    async def stage(self, event: EventEnvelope) -> int:
        """Stage ``event`` in the caller's current transaction.

        This method intentionally does not commit. The caller must commit or roll
        back the same SQLite connection together with its domain-state mutation.
        A caller-assigned event sequence is rejected because canonical ordering is
        allocated only when the outbox event reaches EventStore.
        """
        if event.sequence is not None:
            raise ValueError("cannot stage an event with a store-assigned sequence")
        # Correlated here, where the producer's execution is still in scope.
        # `EventStore.append` correlates too, but by the time this row reaches a
        # publisher that execution has ended -- so the ids would either be lost
        # or, worse, taken from whatever unrelated execution the publisher was
        # running under (Codex, #707).
        serialized = json.dumps(correlated(event).to_dict(), sort_keys=True)
        await self._conn.execute(
            """INSERT INTO canonical_event_outbox (event_id, event_json, created_at)
               VALUES (?, ?, ?)
               ON CONFLICT(event_id) DO NOTHING""",
            (event.event_id, serialized, time.time()),
        )
        cursor = await self._conn.execute(
            "SELECT outbox_id FROM canonical_event_outbox WHERE event_id = ?",
            (event.event_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise RuntimeError("staged outbox event could not be reloaded")
        return int(row[0])

    async def publish_pending(self, event_store: EventStore, *, limit: int = 100) -> int:
        """Publish committed pending rows in insertion order and mark them delivered.

        If publication succeeds but the process exits before ``published_at`` is
        committed, the next call republishes the same stable event ID. EventStore's
        idempotent append contract then returns the existing canonical event.
        """
        if limit < 1:
            return 0
        cursor = await self._conn.execute(
            """SELECT outbox_id, event_json FROM canonical_event_outbox
               WHERE published_at IS NULL ORDER BY outbox_id ASC LIMIT ?""",
            (limit,),
        )
        rows = await cursor.fetchall()
        published = 0
        for row in rows:
            outbox_id = int(row[0])
            event = EventEnvelope(**json.loads(row[1]))
            # Detached: the publisher is not the producer. Whatever execution it
            # happens to be running under has nothing to do with an event staged
            # in another one, and `append` would otherwise fill this event's
            # blanks from it.
            with detached_execution_context():
                await event_store.append(event)
            await self._conn.execute(
                "UPDATE canonical_event_outbox SET published_at = ? WHERE outbox_id = ?",
                (time.time(), outbox_id),
            )
            await self._conn.commit()
            published += 1
        return published

    async def pending_count(self) -> int:
        """Return the number of committed or transaction-visible unpublished rows."""
        cursor = await self._conn.execute(
            "SELECT COUNT(*) FROM canonical_event_outbox WHERE published_at IS NULL"
        )
        row = await cursor.fetchone()
        return int(row[0]) if row is not None else 0
