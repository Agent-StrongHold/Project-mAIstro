"""PostgreSQL persistence for the canonical :class:`EventEnvelope` (#61).

This is deliberately separate from ADR-086's legacy ``PgEventLog``. The latter
owns a reactor delivery cursor over ``LoggedEvent``; this store owns canonical
Event identity and deterministic sequence within one Workspace stream.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from maistro.events.envelope import (
    EventAppendResult,
    EventEnvelope,
    correlated,
    reconstruct_persisted_event,
)

if TYPE_CHECKING:
    import asyncpg


async def ensure_canonical_event_schema(pool: asyncpg.Pool) -> None:
    """Require migration 030's read/write contract without changing the schema.

    The historical name is retained for supplied-pool callers. Alembic alone
    owns DDL; this preflight also runs through CapabilityEffectContext, so an
    unmigrated pool must fail rather than silently creating a second schema.
    Check the columns used by DML and the two uniqueness guarantees on which
    event identity and stream ordering depend. Additional columns/indexes from
    newer migrations are compatible and must not require an exact head stamp.
    """
    async with pool.acquire() as conn:
        await conn.execute(
            """SELECT event_id, stream_id, sequence, type, timestamp,
                      workspace_id, stream_scope, project_id, run_id, node_run_id,
                      attempt_id, invocation_id, session_id, correlation_id, causation_id,
                      source, actor_id, payload, provenance
               FROM canonical_event_log LIMIT 0"""
        )
        indexes = await conn.fetch(
            """SELECT array_agg(a.attname ORDER BY k.ord) AS columns
               FROM pg_index i
               JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS k(attnum, ord) ON TRUE
               JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum
               WHERE i.indrelid = 'canonical_event_log'::regclass
                 AND i.indisunique AND i.indisvalid AND i.indisready AND i.indimmediate
                 AND i.indpred IS NULL AND i.indexprs IS NULL
                 AND k.ord <= i.indnkeyatts
               GROUP BY i.indexrelid"""
        )
    keys = {tuple(row["columns"]) for row in indexes}
    if not {("event_id",), ("stream_id", "sequence")} <= keys:
        raise RuntimeError(
            "PostgreSQL canonical_event_log lacks required unique keys; "
            "apply and verify Alembic migrations before starting the application"
        )


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
        """Check the Alembic-managed schema; never create or repair it."""
        await ensure_canonical_event_schema(self._pool)

    async def append(self, event: EventEnvelope) -> EventEnvelope:
        return (await self.append_with_disposition(event)).event

    async def append_with_disposition(self, event: EventEnvelope) -> EventAppendResult:
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
                return EventAppendResult(_row_to_event(existing), inserted=False)

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
            return EventAppendResult(persisted, inserted=True)

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
    # Bypasses the payload/provenance size bound: a row written before #1164
    # tightened it must stay readable (see reconstruct_persisted_event).
    return reconstruct_persisted_event(
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
