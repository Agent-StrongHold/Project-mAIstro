"""Transactional outbox for canonical event publication.

A caller stages an EventEnvelope on the same SQLite connection and transaction as
its domain-state mutation. Committing that transaction makes both durable; rolling
it back makes neither durable. A separate publisher drains committed outbox rows
to the canonical EventStore. Publication is at-least-once, while stable event IDs
make logical delivery to the canonical store idempotent.

Ordering guarantee (#1162): rows of one stream (``workspace:<id>`` or
``scope:<id>``) are published in the order they were staged, ascending
``outbox_id``. A row whose durable append keeps failing therefore delays only the
later rows of *its own* stream -- never rows of unrelated streams, and never the
whole outbox. When a row exhausts its attempt bound it is dead-lettered
(``failed_at`` is set, with ``attempts`` and ``last_error`` keeping the failure
evidence); that disposition is terminal and releases the stream, so the
dead-lettered event is skipped and later same-stream rows proceed from the next
publisher pass. Across streams there is no ordering contract.

Per-row fault isolation (#1162): a durable append that raises is recorded on the
row -- ``attempts`` increments and ``last_error``/``next_attempt_at`` are
persisted in their own committed transaction -- and the drain moves on. The row
is retried on later passes once its backoff has elapsed, up to
``MAX_PUBLISH_ATTEMPTS`` total attempts; past that bound it is dead-lettered
rather than retried forever. Idempotence is unchanged: ``published_at`` is
committed only after the append returns, so a crash between the two republishes
the same stable event ID, and EventStore's idempotent append returns the
existing canonical event.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from maistro.events.envelope import (
    EventEnvelope,
    EventStore,
    correlated,
    reconstruct_persisted_event,
)
from maistro.observability.correlation import detached_execution_context

if TYPE_CHECKING:
    import aiosqlite

logger = logging.getLogger("maistro.events.outbox")

MAX_PUBLISH_ATTEMPTS = 3
"""Total attempts a failing outbox row gets before it is dead-lettered.

Mirrors ``MAX_ATTEMPTS`` in :mod:`maistro.events.invocations`: a row is retried
on later publisher passes until this many attempts have been recorded, then it
is dead-lettered and never attempted again.
"""

DEFAULT_RETRY_BACKOFF_SECONDS = 1.0
"""How long a row that just failed waits before its next attempt is due."""


@dataclass(frozen=True)
class OutboxDeadLetter:
    """One row that exhausted its attempt bound, with its failure evidence."""

    outbox_id: int
    event_id: str
    stream_id: str
    attempts: int
    last_error: str
    failed_at: float


_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS canonical_event_outbox (
    outbox_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    stream_id TEXT NOT NULL DEFAULT '',
    event_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    next_attempt_at REAL NOT NULL DEFAULT 0,
    published_at REAL,
    failed_at REAL
);
"""

#: Created after any legacy-shape column upgrade: the stream index names
#: columns a pre-#1162 table only gains through ``ensure_schema``'s ALTERs.
_INDEX_SCHEMA = """
CREATE INDEX IF NOT EXISTS idx_canonical_event_outbox_pending
    ON canonical_event_outbox (outbox_id) WHERE published_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_canonical_event_outbox_stream_pending
    ON canonical_event_outbox (stream_id, outbox_id)
    WHERE published_at IS NULL AND failed_at IS NULL;
"""


class SqliteEventOutbox:
    """SQLite transactional staging and per-row fault-isolated publication."""

    def __init__(
        self,
        conn: aiosqlite.Connection,
        *,
        max_attempts: int = MAX_PUBLISH_ATTEMPTS,
        retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Configure publication fault handling.

        ``max_attempts`` bounds the total recorded attempts per row before it is
        dead-lettered; ``retry_backoff_seconds`` delays a failed row's next
        attempt; ``clock`` supplies drain timestamps (injectable so backoff is
        testable without sleeping).
        """
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be non-negative")
        self._conn = conn
        self._max_attempts = max_attempts
        self._retry_backoff_seconds = retry_backoff_seconds
        self._clock = clock

    async def ensure_schema(self) -> None:
        """Create or upgrade the outbox schema and commit the schema transaction.

        Columns added after the first release (the #1162 fault-isolation state)
        are appended to pre-existing tables, so a database created by an older
        revision upgrades in place instead of silently keeping the old shape
        that the drain's statements would not fit. Each statement below is a
        module literal; nothing caller-influenced ever reaches ``execute``.
        """
        await self._conn.executescript(_TABLE_SCHEMA)
        cursor = await self._conn.execute("PRAGMA table_info(canonical_event_outbox)")
        present = {str(row[1]) for row in await cursor.fetchall()}
        if "stream_id" not in present:
            await self._conn.execute(
                "ALTER TABLE canonical_event_outbox ADD COLUMN stream_id TEXT NOT NULL DEFAULT ''"
            )
        if "attempts" not in present:
            await self._conn.execute(
                "ALTER TABLE canonical_event_outbox ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0"
            )
        if "last_error" not in present:
            await self._conn.execute(
                "ALTER TABLE canonical_event_outbox ADD COLUMN last_error TEXT NOT NULL DEFAULT ''"
            )
        if "next_attempt_at" not in present:
            await self._conn.execute(
                "ALTER TABLE canonical_event_outbox "
                "ADD COLUMN next_attempt_at REAL NOT NULL DEFAULT 0"
            )
        if "failed_at" not in present:
            await self._conn.execute("ALTER TABLE canonical_event_outbox ADD COLUMN failed_at REAL")
        await self._conn.executescript(_INDEX_SCHEMA)
        await self._conn.commit()
        await self._backfill_stream_ids()

    async def _backfill_stream_ids(self) -> None:
        """Derive ``stream_id`` for rows staged before the column existed.

        A row's stream is a pure function of its stored envelope, so the
        backfill is idempotent and only legacy rows ever match. A row whose JSON
        no longer parses keeps the empty stream, where it can only ever hold
        back other corrupt rows rather than any real stream.
        """
        cursor = await self._conn.execute(
            "SELECT outbox_id, event_json FROM canonical_event_outbox WHERE stream_id = ''"
        )
        rows = await cursor.fetchall()
        for outbox_id, event_json in rows:
            try:
                stream_id = reconstruct_persisted_event(**json.loads(str(event_json))).stream_id
            except (TypeError, ValueError, KeyError):
                continue
            await self._conn.execute(
                "UPDATE canonical_event_outbox SET stream_id = ? WHERE outbox_id = ?",
                (stream_id, int(outbox_id)),
            )
        if rows:
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
        event = correlated(event)
        # `replace()` with no field changes still re-invokes `__post_init__`,
        # revalidating `payload`/`provenance` against whatever they hold *right
        # now*. Freezing the dataclass only blocks attribute rebinding, not
        # dict mutation, so a caller can mutate either field in place after
        # constructing a valid envelope and before staging it -- this closes
        # that gap without duplicating the bound check here (Codex, #1164).
        event = replace(event)
        serialized = json.dumps(event.to_dict(), sort_keys=True)
        # The stream is stored so the drain can hold a stream's rows back behind
        # a retrying head without re-parsing every envelope to find it.
        await self._conn.execute(
            """INSERT INTO canonical_event_outbox
                 (event_id, stream_id, event_json, created_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(event_id) DO NOTHING""",
            (event.event_id, event.stream_id, serialized, time.time()),
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
        """Publish due pending rows and mark them delivered, isolating faults.

        Rows are considered in ``outbox_id`` order once they are unpublished,
        not dead-lettered, and past any backoff; ``limit`` bounds how many such
        rows one call inspects. A row whose parse or durable append raises gets
        its failure recorded (``attempts`` incremented, ``last_error`` and
        ``next_attempt_at`` persisted and committed) and the drain moves on, so
        the failure holds back only later rows of the same stream. Once
        ``max_attempts`` total attempts are recorded the row is dead-lettered
        (``failed_at``) and never attempted again; :meth:`dead_letters` reads
        the disposition.

        If publication succeeds but the process exits before ``published_at`` is
        committed, the next call republishes the same stable event ID. EventStore's
        idempotent append contract then returns the existing canonical event.
        """
        if limit < 1:
            return 0
        now = self._clock()
        cursor = await self._conn.execute(
            """SELECT outbox_id, stream_id, event_id, event_json, attempts
               FROM canonical_event_outbox AS r
               WHERE r.published_at IS NULL
                 AND r.failed_at IS NULL
                 AND r.next_attempt_at <= ?
                 AND NOT EXISTS (
                     SELECT 1 FROM canonical_event_outbox AS blocked
                     WHERE blocked.stream_id = r.stream_id
                       AND blocked.outbox_id < r.outbox_id
                       AND blocked.published_at IS NULL
                       AND blocked.failed_at IS NULL
                       AND blocked.next_attempt_at > ?
                 )
               ORDER BY r.outbox_id ASC
               LIMIT ?""",
            (now, now, limit),
        )
        rows = await cursor.fetchall()
        published = 0
        # Streams whose head was selected above, failed this pass, and is not
        # yet terminal. (A head still inside its backoff is excluded from the
        # selection itself by the NOT EXISTS clause, so followers never leapfrog
        # it between passes either.)
        blocked_streams: set[str] = set()
        for outbox_id, stream_id, event_id, event_json, attempts in rows:
            stream = str(stream_id)
            if stream in blocked_streams:
                continue
            try:
                event = reconstruct_persisted_event(**json.loads(str(event_json)))
                # Detached: the publisher is not the producer. Whatever execution it
                # happens to be running under has nothing to do with an event staged
                # in another one, and `append` would otherwise fill this event's
                # blanks from it.
                with detached_execution_context():
                    await event_store.append(event)
            except Exception as exc:
                if await self._record_failure(int(outbox_id), str(event_id), int(attempts), exc):
                    # Terminal disposition: the dead letter releases its stream,
                    # so later same-stream rows flow on this and later passes.
                    continue
                blocked_streams.add(stream)
                continue
            await self._conn.execute(
                """UPDATE canonical_event_outbox SET published_at = ?
                   WHERE outbox_id = ? AND published_at IS NULL""",
                (self._clock(), int(outbox_id)),
            )
            await self._conn.commit()
            published += 1
        return published

    async def _record_failure(
        self,
        outbox_id: int,
        event_id: str,
        attempts: int,
        exc: Exception,
    ) -> bool:
        """Persist one failed attempt for the row; dead-letter past the bound.

        Returns whether the row reached its terminal dead-letter disposition.
        """
        attempts += 1
        error = f"{type(exc).__name__}: {exc}".strip()
        now = self._clock()
        if attempts >= self._max_attempts:
            await self._conn.execute(
                """UPDATE canonical_event_outbox
                   SET attempts = ?, last_error = ?, failed_at = ?
                   WHERE outbox_id = ?
                     AND published_at IS NULL AND failed_at IS NULL""",
                (attempts, error, now, outbox_id),
            )
            await self._conn.commit()
            logger.warning(
                "Outbox event %s dead-lettered after %d attempts: %s",
                event_id,
                attempts,
                error,
            )
            return True
        await self._conn.execute(
            """UPDATE canonical_event_outbox
               SET attempts = ?, last_error = ?, next_attempt_at = ?
               WHERE outbox_id = ?
                 AND published_at IS NULL AND failed_at IS NULL""",
            (attempts, error, now + self._retry_backoff_seconds, outbox_id),
        )
        await self._conn.commit()
        return False

    async def dead_letters(self, *, limit: int = 100) -> list[OutboxDeadLetter]:
        """Return dead-lettered rows, oldest first, with their failure evidence."""
        if limit < 1:
            return []
        cursor = await self._conn.execute(
            """SELECT outbox_id, event_id, stream_id, attempts, last_error, failed_at
               FROM canonical_event_outbox
               WHERE failed_at IS NOT NULL
               ORDER BY outbox_id ASC LIMIT ?""",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [
            OutboxDeadLetter(
                outbox_id=int(row[0]),
                event_id=str(row[1]),
                stream_id=str(row[2]),
                attempts=int(row[3]),
                last_error=str(row[4] or ""),
                failed_at=float(row[5]),
            )
            for row in rows
        ]

    async def pending_count(self) -> int:
        """Return unpublished rows still awaiting publication or a due retry.

        Dead-lettered rows are excluded: their disposition is terminal and
        observable through :meth:`dead_letters`, and counting them as pending
        would make one poison event look like permanently backed-up work.
        """
        cursor = await self._conn.execute(
            """SELECT COUNT(*) FROM canonical_event_outbox
               WHERE published_at IS NULL AND failed_at IS NULL"""
        )
        row = await cursor.fetchone()
        return int(row[0]) if row is not None else 0
