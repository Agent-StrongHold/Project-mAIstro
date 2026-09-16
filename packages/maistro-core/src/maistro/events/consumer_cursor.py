"""Durable consumer cursor for the legacy-event replay bridge (ADR-086 / #1163).

`Container.durable_event_cursor` used to be a plain in-process `int`: nothing
outside the running process ever saw it, so every restart replayed
`durable_event_log` from position zero regardless of how much of it had
already settled. Correctness survived that only because `InvocationStore`
dedupes `(trigger_id, event_id)` — the durable cursor here does not change
that: per ADR-082426-82c7 ("the occurrence is the claim, not the cursor"),
a cursor is a resume *optimisation*, and `InvocationStore.claim` stays the
one thing that makes redelivery safe. What this store adds is:

- a **durable position** keyed to a fixed consumer identity, so a restart
  resumes near the last settled point instead of rescanning the whole
  retained log;
- a **claim lease**, so of several replicas that might tick the bridge at
  once, only the holder actually re-scans/redispatches this round — the
  rest skip the tick rather than doing the same (idempotent, but wasted)
  work `_dispatch` would just discard;
- a **fencing token** on `advance`, so a lease that has already been taken
  over cannot clobber the new holder's position with a stale one, and a
  **monotonic** write (`GREATEST`/`MAX`) as a second, independent guard
  against the same failure mode.

Protocol-driven and self-contained in this module, matching the existing
`EventLogStore`/`InvocationStore`/`TriggerStore` convention: in-memory and
SQLite live beside the protocol here, the PostgreSQL twin lives in
`events/pg_stores.py` alongside its siblings.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import aiosqlite

DEFAULT_LEASE_SECONDS = 300.0
"""How long a claimed cursor-tick lease stays owned before another replica may
take it. Mirrors `events.invocations.DEFAULT_LEASE_SECONDS`: long enough that
a normal tick is not stolen mid-run, short enough that a replica killed right
after claiming does not strand the bridge until someone notices.
"""

DEFAULT_HOLE_GRACE_SECONDS = 60.0
"""How long a durable consumer waits at an id the log skipped over before
treating it as an insert that will never commit.

PostgreSQL's `BIGSERIAL` hands out ids at insert time, before the appending
transaction commits, so a slow or rolled-back append leaves a lower id
invisible while a higher one is already readable. A consumer that persisted
its position past the lower id would exclude that event from every later
``id > position`` read, restart included. So `Container.process_durable_events`
keeps its *durable* position below the first such hole until either the id
appears (the append committed; it is read on the next tick) or this many
seconds pass without it (the append aborted, or is slower than any healthy
append, and the position moves on). Sixty seconds is far longer than a
healthy single-row append takes to commit and short enough that an aborted
insert does not stall the bridge's resume point for the rest of the day.
The in-flight handler work is not delayed by this — only the persisted
resume point is.
"""

LEGACY_BRIDGE_CONSUMER_ID = "legacy-event-bridge"
"""The one consumer this store currently serves: `Container.process_durable_events`,
which replays `durable_event_log` (the in-process `EventBus` bridge) into
triggers/handlers. A fixed id rather than a caller-supplied one because there
is exactly one such bridge per container/event log today; a second consumer
of the same log would need its own id so the two do not share one cursor.
"""


@dataclass(frozen=True)
class CursorLease:
    """Exclusive (for `lease_seconds`) permission to advance one consumer's cursor.

    `position` is the durable position as of the claim — the ``after_id`` the
    caller should resume from. `fencing_token` must be presented back to
    `advance`; a stale one (the lease was reclaimed by someone else since)
    means the write is refused rather than silently accepted.
    """

    position: int
    fencing_token: str
    expires_at: float


@runtime_checkable
class ConsumerCursorStore(Protocol):
    """Durable position + claim lease for one durable-event consumer."""

    async def claim(
        self, consumer_id: str, *, holder: str, lease_seconds: float = DEFAULT_LEASE_SECONDS
    ) -> CursorLease | None:
        """Take, or renew, exclusive permission to advance this consumer's cursor.

        Returns `None` when another holder's lease is still live — the caller
        must not tick the bridge in that case; doing so would only repeat
        work the live lease-holder already covers this round. The same
        `holder` calling again before its own lease expires always succeeds
        (a renewal) and keeps the same `fencing_token`; a different holder
        claiming after the previous lease expired gets a fresh token, so a
        write carrying the old one is recognisably stale.
        """
        ...

    async def advance(self, consumer_id: str, *, fencing_token: str, position: int) -> bool:
        """Record a new durable position for the lease identified by `fencing_token`.

        Returns `False` (and writes nothing) if the token no longer matches
        the current lease holder. That is not an error the caller needs to
        handle specially: it means this caller's lease already lapsed and
        was reclaimed, so the new holder's own claim/advance owns the
        position from here — the stale write is simply discarded rather than
        allowed to move the cursor backwards under a holder that no longer
        owns the tick.
        """
        ...


class InMemoryConsumerCursorStore:
    """In-memory :class:`ConsumerCursorStore` (tests, dry-run, single-process homelab)."""

    def __init__(self) -> None:
        self._positions: dict[str, int] = {}
        #: consumer_id -> (holder, fencing_token, lease_expires_at)
        self._leases: dict[str, tuple[str, str, float]] = {}
        self._lock = asyncio.Lock()

    async def claim(
        self, consumer_id: str, *, holder: str, lease_seconds: float = DEFAULT_LEASE_SECONDS
    ) -> CursorLease | None:
        async with self._lock:
            now = time.time()
            existing = self._leases.get(consumer_id)
            if existing is not None:
                existing_holder, existing_token, expires_at = existing
                if expires_at > now and existing_holder != holder:
                    return None
                token = existing_token if existing_holder == holder else uuid.uuid4().hex
            else:
                token = uuid.uuid4().hex
            expires_at = now + lease_seconds
            self._leases[consumer_id] = (holder, token, expires_at)
            return CursorLease(
                position=self._positions.get(consumer_id, 0),
                fencing_token=token,
                expires_at=expires_at,
            )

    async def advance(self, consumer_id: str, *, fencing_token: str, position: int) -> bool:
        async with self._lock:
            existing = self._leases.get(consumer_id)
            if existing is None or existing[1] != fencing_token:
                return False
            current = self._positions.get(consumer_id, 0)
            self._positions[consumer_id] = max(current, position)
            return True


_SCHEMA = """
CREATE TABLE IF NOT EXISTS consumer_cursors (
    consumer_id TEXT PRIMARY KEY,
    position INTEGER NOT NULL DEFAULT 0,
    holder TEXT NOT NULL DEFAULT '',
    fencing_token TEXT NOT NULL DEFAULT '',
    lease_expires_at REAL NOT NULL DEFAULT 0
)
"""


class SqliteConsumerCursorStore:
    """SQLite-backed :class:`ConsumerCursorStore`.

    `claim` is one upsert with a `RETURNING`, same idiom as
    `SqliteInvocationStore.claim`: the `WHERE` on the `DO UPDATE` is what
    makes it a claim (a row held by a still-live different holder matches
    nothing and returns nothing), and the `CASE` keeps the existing
    `fencing_token` on a same-holder renewal so an in-flight `advance` from
    an earlier renewal is not accidentally invalidated by a later one.
    """

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def ensure_schema(self) -> None:
        await self._conn.execute(_SCHEMA)
        await self._conn.commit()

    async def claim(
        self, consumer_id: str, *, holder: str, lease_seconds: float = DEFAULT_LEASE_SECONDS
    ) -> CursorLease | None:
        now = time.time()
        new_token = uuid.uuid4().hex
        cursor = await self._conn.execute(
            """INSERT INTO consumer_cursors
               (consumer_id, position, holder, fencing_token, lease_expires_at)
               VALUES (?, 0, ?, ?, ?)
               ON CONFLICT(consumer_id) DO UPDATE SET
                 holder = excluded.holder,
                 fencing_token = CASE WHEN consumer_cursors.holder = excluded.holder
                                       THEN consumer_cursors.fencing_token
                                       ELSE excluded.fencing_token END,
                 lease_expires_at = excluded.lease_expires_at
               WHERE consumer_cursors.lease_expires_at <= ?
                  OR consumer_cursors.holder = ?
               RETURNING consumer_id, position, fencing_token, lease_expires_at""",
            (consumer_id, holder, new_token, now + lease_seconds, now, holder),
        )
        row = await cursor.fetchone()
        await self._conn.commit()
        return self._row_to_lease(tuple(row)) if row is not None else None

    async def advance(self, consumer_id: str, *, fencing_token: str, position: int) -> bool:
        cursor = await self._conn.execute(
            """UPDATE consumer_cursors SET position = MAX(position, ?)
               WHERE consumer_id = ? AND fencing_token = ?
               RETURNING consumer_id""",
            (position, consumer_id, fencing_token),
        )
        row = await cursor.fetchone()
        await self._conn.commit()
        return row is not None

    @staticmethod
    def _row_to_lease(row: tuple[object, ...]) -> CursorLease:
        return CursorLease(
            position=int(row[1]),  # type: ignore[call-overload]
            fencing_token=str(row[2]),
            expires_at=float(row[3]),  # type: ignore[arg-type]
        )
