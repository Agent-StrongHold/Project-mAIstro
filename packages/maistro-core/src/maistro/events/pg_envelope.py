"""PostgreSQL persistence for the canonical :class:`EventEnvelope` (#61).

This is deliberately separate from ADR-086's legacy ``PgEventLog``. The latter
owns a reactor delivery cursor over ``LoggedEvent``; this store owns canonical
Event identity and deterministic sequence within one Workspace stream.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from maistro.events.envelope import EventEnvelope, correlated

if TYPE_CHECKING:
    import asyncpg

_SCHEMA = """
CREATE TABLE IF NOT EXISTS canonical_event_log (
    event_id TEXT PRIMARY KEY,
    stream_id TEXT NOT NULL,
    sequence BIGINT NOT NULL,
    type TEXT NOT NULL,
    timestamp DOUBLE PRECISION NOT NULL,
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
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE(stream_id, sequence)
);
CREATE INDEX IF NOT EXISTS idx_canonical_event_stream
    ON canonical_event_log (stream_id, sequence);
CREATE INDEX IF NOT EXISTS idx_canonical_event_run
    ON canonical_event_log (run_id, sequence);
"""

_SCHEMA_LOCK_KEY = 0x6D61_6531  # "mae1"


async def ensure_canonical_event_schema(pool: asyncpg.Pool) -> None:
    """Create the canonical Event table for standalone/supplied-pool callers."""
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock($1)", _SCHEMA_LOCK_KEY)
        await conn.execute(_SCHEMA)


class PgEventStore:
    """Canonical EventStore backed by PostgreSQL.

    Every append takes an event-id lock before the stream lock. The first makes
    idempotency deterministic even if a malformed retry changes stream scope;
    the second serializes ``MAX(sequence)+1`` allocation within one Workspace.
    The lock order is fixed for all writers, avoiding cross-stream deadlocks.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def ensure_schema(self) -> None:
        await ensure_canonical_event_schema(self._pool)

    async def append(self, event: EventEnvelope) -> EventEnvelope:
        event = correlated(event)
        if event.sequence is not None:
            raise ValueError("sequence is store-assigned and must be None on append")

        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                f"canonical-event:{event.event_id}",
            )
            existing = await conn.fetchrow(
                "SELECT * FROM canonical_event_log WHERE event_id = $1", event.event_id
            )
            if existing is not None:
                return _row_to_event(existing)

            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                f"canonical-stream:{event.stream_id}",
            )
            sequence = await conn.fetchval(
                "SELECT COALESCE(MAX(sequence), 0) + 1 "
                "FROM canonical_event_log WHERE stream_id = $1",
                event.stream_id,
            )
            persisted = replace(event, sequence=int(sequence))
            await conn.execute(
                """INSERT INTO canonical_event_log (
                    event_id, stream_id, sequence, type, timestamp,
                    workspace_id, stream_scope, project_id, run_id, node_run_id,
                    attempt_id, invocation_id, session_id, correlation_id, causation_id,
                    source, actor_id, payload, provenance
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18::jsonb,$19::jsonb
                )""",
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
            )
            return persisted

    async def get(self, event_id: str) -> EventEnvelope | None:
        row = await self._pool.fetchrow(
            "SELECT * FROM canonical_event_log WHERE event_id = $1", event_id
        )
        return _row_to_event(row) if row is not None else None

    async def list_stream(
        self,
        stream_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> list[EventEnvelope]:
        if limit < 1:
            return []
        rows = await self._pool.fetch(
            """SELECT * FROM canonical_event_log
               WHERE stream_id = $1 AND sequence > $2
               ORDER BY sequence ASC LIMIT $3""",
            stream_id,
            after_sequence,
            limit,
        )
        return [_row_to_event(row) for row in rows]


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        loaded = json.loads(value)
        return dict(loaded)
    return dict(value or {})


def _row_to_event(row: Any) -> EventEnvelope:
    return EventEnvelope(
        event_id=row["event_id"],
        sequence=int(row["sequence"]),
        type=row["type"],
        timestamp=float(row["timestamp"]),
        workspace_id=row["workspace_id"],
        stream_scope=row["stream_scope"],
        project_id=row["project_id"],
        run_id=row["run_id"],
        node_run_id=row["node_run_id"],
        attempt_id=row["attempt_id"],
        invocation_id=row["invocation_id"],
        session_id=row["session_id"],
        correlation_id=row["correlation_id"],
        causation_id=row["causation_id"],
        source=row["source"],
        actor_id=row["actor_id"],
        payload=_json_object(row["payload"]),
        provenance=_json_object(row["provenance"]),
    )


__all__ = ["PgEventStore", "ensure_canonical_event_schema"]
