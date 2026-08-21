"""Handler invocation records with idempotency keys (ADR-086 / SPEC-070226-b234).

Each (trigger_id, event_id) pair is a unique idempotency key: a handler is
invoked at most once successfully per event. A crash mid-handler leaves the
invocation in a non-terminal status; replay retries the SAME row instead of
creating a duplicate, so redelivery produces no duplicate committed effect.
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

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


@runtime_checkable
class InvocationStore(Protocol):
    """Durable store of handler invocations, unique on (trigger_id, event_id)."""

    async def get(self, trigger_id: str, event_id: int) -> HandlerInvocation | None: ...

    async def get_or_create(self, trigger_id: str, event_id: int) -> HandlerInvocation:
        """Return the existing invocation for the key, or create a pending one.

        This is the idempotency primitive: replay after a crash finds the
        existing row rather than creating a second one.
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
            "SELECT trigger_id, event_id, status, attempts, last_error, created_at "
            "FROM handler_invocations WHERE trigger_id = ? AND event_id = ?",
            (trigger_id, event_id),
        )
        row = await cursor.fetchone()
        return self._row_to_invocation(tuple(row)) if row is not None else None

    async def get_or_create(self, trigger_id: str, event_id: int) -> HandlerInvocation:
        await self._conn.execute(
            """INSERT OR IGNORE INTO handler_invocations
               (trigger_id, event_id, status, attempts, last_error, created_at)
               VALUES (?,?,?,?,?,?)""",
            (trigger_id, event_id, InvocationStatus.PENDING.value, 0, "", time.time()),
        )
        await self._conn.commit()
        invocation = await self.get(trigger_id, event_id)
        assert invocation is not None  # nosec B101 - row was just upserted
        return invocation

    async def save(self, invocation: HandlerInvocation) -> None:
        await self._conn.execute(
            """INSERT INTO handler_invocations
               (trigger_id, event_id, status, attempts, last_error, created_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(trigger_id, event_id) DO UPDATE SET
                 status=excluded.status, attempts=excluded.attempts,
                 last_error=excluded.last_error""",
            (
                invocation.trigger_id,
                invocation.event_id,
                invocation.status.value,
                invocation.attempts,
                invocation.last_error,
                invocation.created_at,
            ),
        )
        await self._conn.commit()

    async def list_for_event(self, event_id: int) -> list[HandlerInvocation]:
        cursor = await self._conn.execute(
            "SELECT trigger_id, event_id, status, attempts, last_error, created_at "
            "FROM handler_invocations WHERE event_id = ?",
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
        )
