"""PostgreSQL persistence for canonical capability Invocations."""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

from maistro.capabilities.invocation import (
    Invocation,
    InvocationStatus,
    StaleInvocationUpdate,
    UnsafeEffectRetry,
)

if TYPE_CHECKING:
    import asyncpg


_SCHEMA = """
CREATE TABLE IF NOT EXISTS capability_invocations (
    invocation_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    node_run_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    binding_id TEXT NOT NULL,
    effect_key TEXT NOT NULL,
    effect_scope TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    revision BIGINT NOT NULL DEFAULT 0,
    created_at DOUBLE PRECISION NOT NULL,
    payload JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_capability_invocation_effect
    ON capability_invocations (run_id, node_run_id, binding_id, effect_key, created_at, invocation_id);
CREATE INDEX IF NOT EXISTS idx_capability_invocation_attempt
    ON capability_invocations (attempt_id, created_at, invocation_id);
"""

_CLAIM_DDL = """
UPDATE capability_invocations SET effect_scope = node_run_id WHERE effect_scope = '';
DROP INDEX IF EXISTS uq_capability_invocation_active_effect;
CREATE UNIQUE INDEX uq_capability_invocation_active_effect
    ON capability_invocations (run_id, effect_scope, binding_id, effect_key)
    WHERE status IN ('created', 'running', 'completed', 'unknown');
"""
"""The active-effect claim is keyed by the logical effect identity, not the
physical NodeRun (#42, #1194). ``Invocation.effect_identity`` is
``effect_scope or node_run_id``; ``create`` normalizes an empty scope to the
node_run_id, so the partial unique index spans NodeRun visits exactly like the
in-memory store's ``effect_identity`` guard. The predicate covers every
non-FAILED status: a completed prior record must also refuse a second claim,
closing the check-then-insert window where the first visit terminalizes
between the loser's history read and its insert. The UPDATE + DROP + CREATE
trio also reconciles databases deployed by Alembic revision 035's earlier
node_run_id-keyed index; backfilling the scope of pre-column rows keeps index
creation safe because the old contract never admitted two non-failed rows for
one ``(run_id, node_run_id, binding_id, effect_key)``. Runs after every
``ensure_schema`` so the runtime-backed schema agrees with migration 035
without waiting for a re-migration."""


class PgInvocationStore:
    """PostgreSQL-backed canonical capability Invocation store.

    Effect admission uses a partial unique index and terminal writes use a
    revision compare-and-swap. Both are database guarantees, so a second
    worker cannot dispatch or overwrite a reconciliation merely because it
    has a stale in-process view.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def ensure_schema(self) -> None:
        async with self._pool.acquire() as connection, connection.transaction():
            # Column ALTERs must precede the claim DDL: a database deployed by
            # an earlier revision 035 lacks ``effect_scope`` and ``revision``,
            # and both the backfill UPDATE and the claim index reference the
            # column.
            for statement in _SCHEMA.split(";"):
                if statement.strip():
                    await connection.execute(statement)
            await connection.execute(
                "ALTER TABLE capability_invocations "
                "ADD COLUMN IF NOT EXISTS revision BIGINT NOT NULL DEFAULT 0"
            )
            await connection.execute(
                "ALTER TABLE capability_invocations "
                "ADD COLUMN IF NOT EXISTS effect_scope TEXT NOT NULL DEFAULT ''"
            )
            for statement in _CLAIM_DDL.split(";"):
                if statement.strip():
                    await connection.execute(statement)

    async def create(self, invocation: Invocation) -> Invocation:
        payload = json.loads(invocation.model_dump_json())
        row = await self._pool.fetchrow(
            """INSERT INTO capability_invocations (
                   invocation_id, run_id, node_run_id, attempt_id, binding_id,
                   effect_key, effect_scope, status, revision, created_at, payload
               ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb)
               ON CONFLICT DO NOTHING
               RETURNING invocation_id""",
            invocation.invocation_id,
            invocation.run_id,
            invocation.node_run_id,
            invocation.attempt_id,
            invocation.binding.binding_id,
            invocation.effect_key,
            invocation.effect_scope or invocation.node_run_id,
            invocation.status.value,
            invocation.revision,
            invocation.created_at.timestamp(),
            json.dumps(payload),
        )
        if row is None:
            existing = await self._find_effect(invocation)
            if existing is not None:
                raise UnsafeEffectRetry(
                    f"effect {invocation.effect_key!r} already has an active or completed Invocation"
                )
            raise ValueError(f"Invocation {invocation.invocation_id!r} already exists")
        return invocation.model_copy(deep=True)

    async def get(self, invocation_id: str) -> Invocation | None:
        row = await self._pool.fetchrow(
            "SELECT payload FROM capability_invocations WHERE invocation_id = $1",
            invocation_id,
        )
        return _row_to_invocation(row) if row is not None else None

    async def save(self, invocation: Invocation) -> Invocation:
        next_revision = invocation.revision + 1
        payload = json.loads(
            invocation.model_copy(update={"revision": next_revision}).model_dump_json()
        )
        result = await self._pool.execute(
            """UPDATE capability_invocations SET
                   run_id=$1, node_run_id=$2, attempt_id=$3, binding_id=$4,
                   effect_key=$5, status=$6, revision=$7, created_at=$8, payload=$9::jsonb
               WHERE invocation_id=$10 AND revision=$11""",
            invocation.run_id,
            invocation.node_run_id,
            invocation.attempt_id,
            invocation.binding.binding_id,
            invocation.effect_key,
            invocation.status.value,
            next_revision,
            invocation.created_at.timestamp(),
            json.dumps(payload),
            invocation.invocation_id,
            invocation.revision,
        )
        if result != "UPDATE 1":
            current = await self.get(invocation.invocation_id)
            if current is None:
                raise KeyError(f"Invocation {invocation.invocation_id!r} does not exist")
            raise StaleInvocationUpdate(
                f"Invocation {invocation.invocation_id!r} was updated concurrently"
            )
        return invocation.model_copy(update={"revision": next_revision}, deep=True)

    async def list_effect(
        self,
        *,
        run_id: str,
        node_run_id: str,
        binding_id: str,
        effect_key: str,
        effect_scope: str | None = None,
    ) -> list[Invocation]:
        if effect_scope is None:
            rows = await self._pool.fetch(
                """SELECT payload FROM capability_invocations
                   WHERE run_id=$1 AND node_run_id=$2 AND binding_id=$3 AND effect_key=$4
                   ORDER BY created_at ASC, invocation_id ASC""",
                run_id,
                node_run_id,
                binding_id,
                effect_key,
            )
        else:
            rows = await self._pool.fetch(
                """SELECT payload FROM capability_invocations
                   WHERE run_id=$1 AND effect_scope=$2 AND binding_id=$3 AND effect_key=$4
                   ORDER BY created_at ASC, invocation_id ASC""",
                run_id,
                effect_scope,
                binding_id,
                effect_key,
            )
        return [_row_to_invocation(row) for row in rows]

    async def list_ambiguous(self, *, stale_before: datetime) -> list[Invocation]:
        rows = await self._pool.fetch(
            """SELECT payload FROM capability_invocations
               WHERE status IN ($1,$2,$3)
               ORDER BY created_at ASC, invocation_id ASC""",
            InvocationStatus.CREATED.value,
            InvocationStatus.RUNNING.value,
            InvocationStatus.UNKNOWN.value,
        )
        items = [_row_to_invocation(row) for row in rows]
        return [
            item
            for item in items
            if item.status is InvocationStatus.UNKNOWN
            or (
                item.status in {InvocationStatus.CREATED, InvocationStatus.RUNNING}
                and (item.started_at or item.created_at) <= stale_before
            )
        ]

    async def _find_effect(self, invocation: Invocation) -> Invocation | None:
        row = await self._pool.fetchrow(
            """SELECT payload FROM capability_invocations
               WHERE run_id=$1 AND effect_scope=$2 AND binding_id=$3 AND effect_key=$4
               ORDER BY created_at DESC, invocation_id DESC LIMIT 1""",
            invocation.run_id,
            invocation.effect_scope or invocation.node_run_id,
            invocation.binding.binding_id,
            invocation.effect_key,
        )
        return _row_to_invocation(row) if row is not None else None


def _row_to_invocation(row: Any) -> Invocation:
    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return Invocation.model_validate(payload)


__all__ = ["PgInvocationStore"]
