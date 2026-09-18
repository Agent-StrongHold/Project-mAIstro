"""Handler invocation records with idempotency keys (ADR-086 / SPEC-070226-b234).

Each (trigger_id, event_id) pair is a unique idempotency key: a handler is
invoked at most once successfully per event. A crash mid-handler leaves the
invocation in a non-terminal status; replay retries the SAME row instead of
creating a duplicate, so redelivery produces no duplicate committed effect.

**The key deduplicates rows; the lease deduplicates dispatch.** Those are not
the same guarantee, and conflating them is how "at most once successfully" gets
claimed by a store that cannot deliver it. Two workers calling `get_or_create`
on one key converge on a single row and *both* receive it in a non-terminal
status — whereupon both would call the handler. So dispatch goes through
`claim`, which hands the invocation to exactly one caller and returns `None` to
the rest. The lease expires, because a worker that dies mid-handler must not
wedge the event forever; `MAX_ATTEMPTS` still bounds the retries that follow.

This only became reachable with a store more than one process can open — which
is why the PostgreSQL backend is where it had to be answered (#135). In-memory
and SQLite implement the same contract so one conformance suite covers all
three, and so the semantics cannot drift per backend.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import aiosqlite

MAX_ATTEMPTS = 3
"""A failing handler is retried until this many attempts, then marked failed."""

DEFAULT_LEASE_SECONDS = 300.0
"""How long a claimed invocation stays owned before another worker may take it.

Long enough that a slow handler is not stolen from mid-run, short enough that a
worker killed between claiming and finishing does not strand the event until
someone notices. A handler that legitimately runs longer than this needs its own
lease, not a longer global default -- which is why `claim` takes the value.
"""


class InvocationStatus(StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"


TERMINAL_STATUSES = frozenset({InvocationStatus.SUCCESS, InvocationStatus.FAILED})


@dataclass
class HandlerInvocation:
    """One trigger firing for one event. Keyed by (trigger_id, event_id)."""

    trigger_id: str
    event_id: int
    status: InvocationStatus = InvocationStatus.PENDING
    attempts: int = 0
    last_error: str = ""
    created_at: float = field(default_factory=time.time)
    lease_expires_at: float = 0.0
    """When the current dispatch lease lapses; 0 means nobody holds one."""

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def is_leased_at(self, now: float) -> bool:
        """Whether another worker's dispatch lease is still live at `now`."""
        return self.lease_expires_at > now


@runtime_checkable
class InvocationStore(Protocol):
    """Durable store of handler invocations, unique on (trigger_id, event_id)."""

    async def get(self, trigger_id: str, event_id: int) -> HandlerInvocation | None: ...

    async def get_or_create(self, trigger_id: str, event_id: int) -> HandlerInvocation:
        """Return the existing invocation for the key, or create a pending one.

        The bookkeeping primitive: replay after a crash finds the existing row
        rather than creating a second one. It is **not** permission to dispatch
        — every racing caller gets the same non-terminal row back. Use `claim`
        before invoking a handler.
        """
        ...

    async def claim(
        self, trigger_id: str, event_id: int, *, lease_seconds: float = DEFAULT_LEASE_SECONDS
    ) -> HandlerInvocation | None:
        """Take exclusive ownership of dispatching this (trigger, event), or `None`.

        Atomic, and the atomicity is the point: of N workers racing on one key,
        exactly one gets an invocation back and the rest get `None`. Returns
        `None` when the invocation is already terminal, or when another worker
        holds a lease that has not yet expired.

        Claiming increments `attempts`, so a handler that keeps dying still
        reaches `MAX_ATTEMPTS` rather than retrying forever.
        """
        ...

    async def save(self, invocation: HandlerInvocation) -> None:
        """Persist updated status/attempts/last_error for an existing invocation."""
        ...

    async def list_for_event(self, event_id: int) -> list[HandlerInvocation]: ...


class InMemoryInvocationStore:
    """In-memory :class:`InvocationStore`."""

    def __init__(self) -> None:
        self._invocations: dict[tuple[str, int], HandlerInvocation] = {}
        self._lock = asyncio.Lock()

    async def get(self, trigger_id: str, event_id: int) -> HandlerInvocation | None:
        return self._invocations.get((trigger_id, event_id))

    async def get_or_create(self, trigger_id: str, event_id: int) -> HandlerInvocation:
        async with self._lock:
            key = (trigger_id, event_id)
            existing = self._invocations.get(key)
            if existing is not None:
                return existing
            invocation = HandlerInvocation(trigger_id=trigger_id, event_id=event_id)
            self._invocations[key] = invocation
            return invocation

    async def claim(
        self, trigger_id: str, event_id: int, *, lease_seconds: float = DEFAULT_LEASE_SECONDS
    ) -> HandlerInvocation | None:
        # The whole body is inside the lock: read, decide and write have to be
        # one step, or two coroutines both read "unleased" and both claim.
        async with self._lock:
            now = time.time()
            key = (trigger_id, event_id)
            invocation = self._invocations.get(key)
            if invocation is None:
                invocation = HandlerInvocation(trigger_id=trigger_id, event_id=event_id)
                self._invocations[key] = invocation
            elif invocation.is_terminal or invocation.is_leased_at(now):
                return None
            invocation.attempts += 1
            invocation.lease_expires_at = now + lease_seconds
            return invocation

    async def save(self, invocation: HandlerInvocation) -> None:
        async with self._lock:
            self._invocations[(invocation.trigger_id, invocation.event_id)] = invocation

    async def list_for_event(self, event_id: int) -> list[HandlerInvocation]:
        return [i for i in self._invocations.values() if i.event_id == event_id]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS handler_invocations (
    trigger_id TEXT NOT NULL,
    event_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    lease_expires_at REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (trigger_id, event_id)
)
"""


class SqliteInvocationStore:
    """SQLite-backed :class:`InvocationStore`.

    The composite primary key enforces the (trigger_id, event_id) idempotency
    key at the storage layer; ``get_or_create`` uses ``INSERT OR IGNORE`` so
    concurrent replays converge on a single row.
    """

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def ensure_schema(self) -> None:
        await self._conn.execute(_SCHEMA)
        await self._conn.commit()

    async def get(self, trigger_id: str, event_id: int) -> HandlerInvocation | None:
        cursor = await self._conn.execute(
            "SELECT trigger_id, event_id, status, attempts, last_error, created_at, "
            "lease_expires_at FROM handler_invocations WHERE trigger_id = ? AND event_id = ?",
            (trigger_id, event_id),
        )
        row = await cursor.fetchone()
        return self._row_to_invocation(tuple(row)) if row is not None else None

    async def get_or_create(self, trigger_id: str, event_id: int) -> HandlerInvocation:
        await self._conn.execute(
            """INSERT OR IGNORE INTO handler_invocations
               (trigger_id, event_id, status, attempts, last_error, created_at, lease_expires_at)
               VALUES (?,?,?,?,?,?,0)""",
            (trigger_id, event_id, InvocationStatus.PENDING.value, 0, "", time.time()),
        )
        await self._conn.commit()
        invocation = await self.get(trigger_id, event_id)
        assert invocation is not None  # nosec B101 - row was just upserted
        return invocation

    async def claim(
        self, trigger_id: str, event_id: int, *, lease_seconds: float = DEFAULT_LEASE_SECONDS
    ) -> HandlerInvocation | None:
        # `RETURNING` on the upsert, so the decision and the write are one
        # statement. The `WHERE` on the DO UPDATE is what makes it a claim: a
        # row that is terminal or still leased matches nothing, updates nothing
        # and returns nothing.
        now = time.time()
        cursor = await self._conn.execute(
            """INSERT INTO handler_invocations
               (trigger_id, event_id, status, attempts, last_error, created_at, lease_expires_at)
               VALUES (?,?,?,1,'',?,?)
               ON CONFLICT(trigger_id, event_id) DO UPDATE SET
                 attempts = handler_invocations.attempts + 1,
                 lease_expires_at = excluded.lease_expires_at
               WHERE handler_invocations.status NOT IN (?,?)
                 AND handler_invocations.lease_expires_at <= ?
               RETURNING trigger_id, event_id, status, attempts, last_error, created_at,
                         lease_expires_at""",
            (
                trigger_id,
                event_id,
                InvocationStatus.PENDING.value,
                now,
                now + lease_seconds,
                InvocationStatus.SUCCESS.value,
                InvocationStatus.FAILED.value,
                now,
            ),
        )
        row = await cursor.fetchone()
        await self._conn.commit()
        return self._row_to_invocation(tuple(row)) if row is not None else None

    async def save(self, invocation: HandlerInvocation) -> None:
        await self._conn.execute(
            """INSERT INTO handler_invocations
               (trigger_id, event_id, status, attempts, last_error, created_at, lease_expires_at)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(trigger_id, event_id) DO UPDATE SET
                 status=excluded.status, attempts=excluded.attempts,
                 last_error=excluded.last_error,
                 lease_expires_at=excluded.lease_expires_at""",
            (
                invocation.trigger_id,
                invocation.event_id,
                invocation.status.value,
                invocation.attempts,
                invocation.last_error,
                invocation.created_at,
                invocation.lease_expires_at,
            ),
        )
        await self._conn.commit()

    async def list_for_event(self, event_id: int) -> list[HandlerInvocation]:
        cursor = await self._conn.execute(
            "SELECT trigger_id, event_id, status, attempts, last_error, created_at, "
            "lease_expires_at FROM handler_invocations WHERE event_id = ?",
            (event_id,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_invocation(tuple(r)) for r in rows]

    @staticmethod
    def _row_to_invocation(row: tuple[object, ...]) -> HandlerInvocation:
        return HandlerInvocation(
            trigger_id=str(row[0]),
            event_id=int(row[1]),  # type: ignore[call-overload]
            status=InvocationStatus(str(row[2])),
            attempts=int(row[3]),  # type: ignore[call-overload]
            last_error=str(row[4] or ""),
            created_at=float(row[5]),  # type: ignore[arg-type]
            lease_expires_at=float(row[6] or 0),  # type: ignore[arg-type]
        )
