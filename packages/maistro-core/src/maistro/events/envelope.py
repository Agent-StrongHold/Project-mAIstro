"""Canonical event envelope and append-only persistence contract.

The envelope carries stable execution correlation IDs while leaving domain payloads
opaque. The canonical durable store assigns sequence numbers monotonically within a
Workspace event stream. Events outside a Workspace require an explicit alternate
stream scope so no implicit global ordering authority is created.
"""

from __future__ import annotations

import asyncio
import copy
import json
import time
from dataclasses import asdict, dataclass, field, replace
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable
from uuid import uuid4

from maistro.observability.correlation import current_execution_context

if TYPE_CHECKING:
    import aiosqlite


@dataclass(frozen=True)
class EventEnvelope:
    """Immutable canonical event envelope.

    ``sequence`` is ``None`` until the event is durably appended. Stores assign a
    monotonically increasing sequence within :attr:`stream_id`. Workspace events
    always derive that stream from ``workspace_id``; non-Workspace events must set
    ``stream_scope`` explicitly. Domain-specific data belongs in ``payload``.
    """

    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: uuid4().hex)
    sequence: int | None = None
    timestamp: float = field(default_factory=time.time)
    workspace_id: str = ""
    stream_scope: str = ""
    project_id: str = ""
    run_id: str = ""
    node_run_id: str = ""
    attempt_id: str = ""
    invocation_id: str = ""
    session_id: str = ""
    correlation_id: str = ""
    causation_id: str = ""
    source: str = ""
    actor_id: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.type.strip():
            raise ValueError("type must be a non-empty string")
        if not self.event_id.strip():
            raise ValueError("event_id must be a non-empty string")
        if not self.workspace_id.strip() and not self.stream_scope.strip():
            raise ValueError("non-Workspace events require an explicit stream_scope")
        if self.workspace_id.strip() and self.stream_scope.strip():
            raise ValueError("Workspace events must not define a competing stream_scope")
        if self.sequence is not None and self.sequence < 1:
            raise ValueError("sequence must be positive when present")
        object.__setattr__(self, "payload", copy.deepcopy(self.payload))
        object.__setattr__(self, "provenance", copy.deepcopy(self.provenance))

    @property
    def stream_id(self) -> str:
        """Return the canonical ordering scope for this event."""
        if self.workspace_id:
            return f"workspace:{self.workspace_id}"
        return f"scope:{self.stream_scope}"

    def to_dict(self) -> dict[str, Any]:
        """Return a serialization-ready copy of the envelope."""
        return asdict(self)


#: Envelope fields filled from an identically named id on the execution context.
_CORRELATABLE_FIELDS: tuple[str, ...] = (
    "project_id",
    "run_id",
    "node_run_id",
    "attempt_id",
    "invocation_id",
    "session_id",
)


def correlated(event: EventEnvelope) -> EventEnvelope:
    """Return `event` with its blank correlation fields filled from context.

    Every producer fills these by hand today. `governed_invocation` sets
    `correlation_id` at four separate call sites and `runs.recovery_events` at
    a fifth; `invocation_id` is assigned in exactly one place in the whole of
    `packages/*/src`. Nothing checked that a producer set the ids it could
    have, so an omission emitted a silently uncorrelated event -- the same
    failure #698 fixed for node metrics, in another subsystem (#707).

    What the producer set is never touched: an event *about* another Run says
    something the ambient context does not know.

    `workspace_id` is deliberately not among the fillable fields. The envelope's
    own invariant requires `workspace_id` or `stream_scope` and forbids both, so
    by the time an envelope exists a blank `workspace_id` is not an omission --
    it is a producer that chose an explicit alternate stream, and overwriting
    that would move the event to a different stream or raise outright.

    `correlation_id` falls back to the Run, which is what all five hand-written
    producers already do: "what happened during this Run" is the question a
    reader arrives with.
    """
    context = current_execution_context()
    if not context:
        return event

    overlay: dict[str, Any] = {
        name: value
        for name in _CORRELATABLE_FIELDS
        if not getattr(event, name) and (value := getattr(context, name))
    }
    if not event.correlation_id and context.run_id:
        overlay["correlation_id"] = context.run_id
    if not overlay:
        return event
    return replace(event, **overlay)


@runtime_checkable
class EventStore(Protocol):
    """Append-only persistence for canonical :class:`EventEnvelope` objects."""

    async def append(self, event: EventEnvelope) -> EventEnvelope:
        """Persist ``event`` idempotently and assign its stream sequence."""
        ...

    async def get(self, event_id: str) -> EventEnvelope | None:
        """Return one event by its stable event ID."""
        ...

    async def list_stream(
        self,
        stream_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> list[EventEnvelope]:
        """Return one stream in ascending sequence order."""
        ...


class InMemoryEventStore:
    """Concurrency-safe in-memory EventStore for tests and local execution."""

    def __init__(self) -> None:
        self._events_by_id: dict[str, EventEnvelope] = {}
        self._streams: dict[str, list[EventEnvelope]] = {}
        self._lock = asyncio.Lock()

    async def append(self, event: EventEnvelope) -> EventEnvelope:
        async with self._lock:
            # Before the idempotency check, not after: the fill has to happen
            # on the event that will be written, and an event already present
            # is returned as it was stored rather than re-correlated (#707).
            event = correlated(event)
            existing = self._events_by_id.get(event.event_id)
            if existing is not None:
                return existing
            if event.sequence is not None:
                raise ValueError("sequence is store-assigned and must be None on append")

            stream = self._streams.setdefault(event.stream_id, [])
            persisted = replace(
                event,
                sequence=len(stream) + 1,
                payload=copy.deepcopy(event.payload),
                provenance=copy.deepcopy(event.provenance),
            )
            stream.append(persisted)
            self._events_by_id[persisted.event_id] = persisted
            return persisted

    async def get(self, event_id: str) -> EventEnvelope | None:
        return self._events_by_id.get(event_id)

    async def list_stream(
        self,
        stream_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> list[EventEnvelope]:
        if limit < 1:
            return []
        return [
            event
            for event in self._streams.get(stream_id, [])
            if event.sequence is not None and event.sequence > after_sequence
        ][:limit]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS canonical_event_log (
    event_id TEXT PRIMARY KEY,
    stream_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    type TEXT NOT NULL,
    timestamp REAL NOT NULL,
    workspace_id TEXT NOT NULL DEFAULT '',
    stream_scope TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT '',
    run_id TEXT NOT NULL DEFAULT '',
    node_run_id TEXT NOT NULL DEFAULT '',
    attempt_id TEXT NOT NULL DEFAULT '',
    invocation_id TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    correlation_id TEXT NOT NULL DEFAULT '',
    causation_id TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    actor_id TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL DEFAULT '{}',
    provenance TEXT NOT NULL DEFAULT '{}',
    UNIQUE(stream_id, sequence)
);
CREATE INDEX IF NOT EXISTS idx_canonical_event_stream
    ON canonical_event_log (stream_id, sequence);
CREATE INDEX IF NOT EXISTS idx_canonical_event_run
    ON canonical_event_log (run_id, sequence);
"""


class SqliteEventStore:
    """SQLite implementation of the canonical EventStore contract.

    ``BEGIN IMMEDIATE`` makes sequence allocation a single SQLite write authority
    across connections. The uniqueness constraint remains a final invariant guard.
    """

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
        self._lock = asyncio.Lock()

    async def ensure_schema(self) -> None:
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()

    async def append(self, event: EventEnvelope) -> EventEnvelope:
        async with self._lock:
            # Before the idempotency check, not after: the fill has to happen
            # on the event that will be written, and an event already present
            # is returned as it was stored rather than re-correlated (#707).
            event = correlated(event)
            if event.sequence is not None:
                raise ValueError("sequence is store-assigned and must be None on append")

            await self._conn.execute("BEGIN IMMEDIATE")
            try:
                cursor = await self._conn.execute(
                    "SELECT * FROM canonical_event_log WHERE event_id = ?",
                    (event.event_id,),
                )
                existing = await cursor.fetchone()
                if existing is not None:
                    await self._conn.commit()
                    return self._row_to_event(tuple(existing))

                cursor = await self._conn.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 "
                    "FROM canonical_event_log WHERE stream_id = ?",
                    (event.stream_id,),
                )
                row = await cursor.fetchone()
                sequence = int(row[0]) if row is not None else 1
                persisted = replace(
                    event,
                    sequence=sequence,
                    payload=copy.deepcopy(event.payload),
                    provenance=copy.deepcopy(event.provenance),
                )
                await self._conn.execute(
                    """INSERT INTO canonical_event_log (
                        event_id, stream_id, sequence, type, timestamp,
                        workspace_id, stream_scope, project_id, run_id, node_run_id,
                        attempt_id, invocation_id, session_id, correlation_id, causation_id,
                        source, actor_id, payload, provenance
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        persisted.event_id,
                        persisted.stream_id,
                        persisted.sequence,
                        persisted.type,
                        persisted.timestamp,
                        persisted.workspace_id,
                        persisted.stream_scope,
                        persisted.project_id,
                        persisted.run_id,
                        persisted.node_run_id,
                        persisted.attempt_id,
                        persisted.invocation_id,
                        persisted.session_id,
                        persisted.correlation_id,
                        persisted.causation_id,
                        persisted.source,
                        persisted.actor_id,
                        json.dumps(persisted.payload),
                        json.dumps(persisted.provenance),
                    ),
                )
                await self._conn.commit()
                return persisted
            except Exception:
                await self._conn.rollback()
                raise

    async def get(self, event_id: str) -> EventEnvelope | None:
        cursor = await self._conn.execute(
            "SELECT * FROM canonical_event_log WHERE event_id = ?",
            (event_id,),
        )
        row = await cursor.fetchone()
        return self._row_to_event(tuple(row)) if row is not None else None

    async def list_stream(
        self,
        stream_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> list[EventEnvelope]:
        if limit < 1:
            return []
        cursor = await self._conn.execute(
            """SELECT * FROM canonical_event_log
               WHERE stream_id = ? AND sequence > ?
               ORDER BY sequence ASC LIMIT ?""",
            (stream_id, after_sequence, limit),
        )
        rows = await cursor.fetchall()
        return [self._row_to_event(tuple(row)) for row in rows]

    @staticmethod
    def _row_to_event(row: tuple[Any, ...]) -> EventEnvelope:
        return EventEnvelope(
            event_id=row[0],
            sequence=row[2],
            type=row[3],
            timestamp=row[4],
            workspace_id=row[5],
            stream_scope=row[6],
            project_id=row[7],
            run_id=row[8],
            node_run_id=row[9],
            attempt_id=row[10],
            invocation_id=row[11],
            session_id=row[12],
            correlation_id=row[13],
            causation_id=row[14],
            source=row[15],
            actor_id=row[16],
            payload=json.loads(row[17]),
            provenance=json.loads(row[18]),
        )
