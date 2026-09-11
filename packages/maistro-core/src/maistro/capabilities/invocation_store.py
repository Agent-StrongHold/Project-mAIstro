"""Durable persistence adapters for canonical capability Invocations.

This module is intentionally distinct from
:mod:`maistro.events.invocations`: the latter records event-handler delivery,
while ``capability_invocations`` records provider effects keyed by
``(run_id, node_run_id, binding_id, effect_key)``. The Container wires these
stores into the governed capability context and the ``033`` migration owns the
PostgreSQL schema.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from maistro.capabilities.invocation import Invocation, InvocationStatus, UnsafeEffectRetry

if TYPE_CHECKING:
    import aiosqlite


_SCHEMA = """
CREATE TABLE IF NOT EXISTS capability_invocations (
    invocation_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    node_run_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    binding_id TEXT NOT NULL,
    effect_key TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at REAL NOT NULL,
    payload_json TEXT NOT NULL,
    UNIQUE(run_id, node_run_id, binding_id, effect_key)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_capability_invocation_effect
    ON capability_invocations (run_id, node_run_id, binding_id, effect_key);
CREATE INDEX IF NOT EXISTS idx_capability_invocation_effect
    ON capability_invocations (
        run_id, node_run_id, binding_id, effect_key, created_at, invocation_id
    );
CREATE INDEX IF NOT EXISTS idx_capability_invocation_attempt
    ON capability_invocations (attempt_id, created_at, invocation_id);
"""


class SqliteInvocationStore:
    """SQLite InvocationStore preserving complete resolved-provider provenance."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
        self._lock = asyncio.Lock()

    async def ensure_schema(self) -> None:
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()

    async def create(self, invocation: Invocation) -> Invocation:
        async with self._lock:
            try:
                await self._conn.execute(
                    """INSERT INTO capability_invocations (
                        invocation_id, run_id, node_run_id, attempt_id, binding_id,
                        effect_key, status, created_at, payload_json
                    ) VALUES (?,?,?,?,?,?,?,?,?)""",
                    self._row_values(invocation),
                )
                await self._conn.commit()
            except Exception:
                await self._conn.rollback()
                raise
        return invocation.model_copy(deep=True)

    async def reopen_failed(self, existing: Invocation, replacement: Invocation) -> Invocation:
        async with self._lock:
            await self._conn.execute("BEGIN IMMEDIATE")
            try:
                cursor = await self._conn.execute(
                    """UPDATE capability_invocations SET
                       invocation_id=?, attempt_id=?, status=?, created_at=?, payload_json=?
                       WHERE run_id=? AND node_run_id=? AND binding_id=? AND effect_key=?
                         AND invocation_id=? AND status=?""",
                    (
                        replacement.invocation_id,
                        replacement.attempt_id,
                        replacement.status.value,
                        replacement.created_at.timestamp(),
                        replacement.model_dump_json(),
                        existing.run_id,
                        existing.node_run_id,
                        existing.binding.binding_id,
                        existing.effect_key,
                        existing.invocation_id,
                        InvocationStatus.FAILED.value,
                    ),
                )
                if cursor.rowcount != 1:
                    raise UnsafeEffectRetry("failed Invocation is no longer eligible for retry")
                await self._conn.commit()
            except Exception:
                await self._conn.rollback()
                raise
        return replacement.model_copy(deep=True)

    async def get(self, invocation_id: str) -> Invocation | None:
        cursor = await self._conn.execute(
            "SELECT payload_json FROM capability_invocations WHERE invocation_id = ?",
            (invocation_id,),
        )
        row = await cursor.fetchone()
        return Invocation.model_validate_json(str(row[0])) if row is not None else None

    async def save(self, invocation: Invocation) -> Invocation:
        async with self._lock:
            cursor = await self._conn.execute(
                """UPDATE capability_invocations SET
                    run_id = ?, node_run_id = ?, attempt_id = ?, binding_id = ?,
                    effect_key = ?, status = ?, created_at = ?, payload_json = ?
                   WHERE invocation_id = ?""",
                (
                    invocation.run_id,
                    invocation.node_run_id,
                    invocation.attempt_id,
                    invocation.binding.binding_id,
                    invocation.effect_key,
                    invocation.status.value,
                    invocation.created_at.timestamp(),
                    invocation.model_dump_json(),
                    invocation.invocation_id,
                ),
            )
            if cursor.rowcount != 1:
                await self._conn.rollback()
                raise KeyError(f"Invocation {invocation.invocation_id!r} does not exist")
            await self._conn.commit()
        return invocation.model_copy(deep=True)

    async def list_effect(
        self,
        *,
        run_id: str,
        node_run_id: str,
        binding_id: str,
        effect_key: str,
    ) -> list[Invocation]:
        cursor = await self._conn.execute(
            """SELECT payload_json FROM capability_invocations
               WHERE run_id = ? AND node_run_id = ? AND binding_id = ? AND effect_key = ?
               ORDER BY created_at ASC, invocation_id ASC""",
            (run_id, node_run_id, binding_id, effect_key),
        )
        rows = await cursor.fetchall()
        return [Invocation.model_validate_json(str(row[0])) for row in rows]

    @staticmethod
    def _row_values(invocation: Invocation) -> tuple[object, ...]:
        return (
            invocation.invocation_id,
            invocation.run_id,
            invocation.node_run_id,
            invocation.attempt_id,
            invocation.binding.binding_id,
            invocation.effect_key,
            invocation.status.value,
            invocation.created_at.timestamp(),
            invocation.model_dump_json(),
        )


class PgInvocationStore:
    """PostgreSQL-backed canonical capability Invocation store.

    The logical effect identity is a unique constraint, not a read-before-write
    convention. A losing replica receives the database conflict before it can
    dispatch a second provider call.
    """

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def ensure_schema(self) -> None:
        from maistro.capabilities.durable_schema import ensure_capability_schema

        await ensure_capability_schema(self._pool)

    async def create(self, invocation: Invocation) -> Invocation:
        await self._pool.execute(
            """INSERT INTO capability_invocations
               (invocation_id, run_id, node_run_id, attempt_id, binding_id,
                effect_key, status, created_at, payload)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb)""",
            invocation.invocation_id,
            invocation.run_id,
            invocation.node_run_id,
            invocation.attempt_id,
            invocation.binding.binding_id,
            invocation.effect_key,
            invocation.status.value,
            invocation.created_at.timestamp(),
            invocation.model_dump_json(),
        )
        return invocation.model_copy(deep=True)

    async def reopen_failed(self, existing: Invocation, replacement: Invocation) -> Invocation:
        async with self._pool.acquire() as conn, conn.transaction():
            result = await conn.execute(
                """UPDATE capability_invocations SET
                   invocation_id=$1, attempt_id=$2, status=$3, created_at=$4, payload=$5::jsonb
                   WHERE run_id=$6 AND node_run_id=$7 AND binding_id=$8 AND effect_key=$9
                     AND invocation_id=$10 AND status=$11""",
                replacement.invocation_id,
                replacement.attempt_id,
                replacement.status.value,
                replacement.created_at.timestamp(),
                replacement.model_dump_json(),
                existing.run_id,
                existing.node_run_id,
                existing.binding.binding_id,
                existing.effect_key,
                existing.invocation_id,
                InvocationStatus.FAILED.value,
            )
            if result != "UPDATE 1":
                raise UnsafeEffectRetry("failed Invocation is no longer eligible for retry")
        return replacement.model_copy(deep=True)

    async def get(self, invocation_id: str) -> Invocation | None:
        row = await self._pool.fetchrow(
            "SELECT payload FROM capability_invocations WHERE invocation_id = $1",
            invocation_id,
        )
        return _invocation_from_payload(row["payload"]) if row is not None else None

    async def save(self, invocation: Invocation) -> Invocation:
        result = await self._pool.execute(
            """UPDATE capability_invocations SET
               run_id=$1, node_run_id=$2, attempt_id=$3, binding_id=$4,
               effect_key=$5, status=$6, created_at=$7, payload=$8::jsonb
               WHERE invocation_id=$9""",
            invocation.run_id,
            invocation.node_run_id,
            invocation.attempt_id,
            invocation.binding.binding_id,
            invocation.effect_key,
            invocation.status.value,
            invocation.created_at.timestamp(),
            invocation.model_dump_json(),
            invocation.invocation_id,
        )
        if result != "UPDATE 1":
            raise KeyError(f"Invocation {invocation.invocation_id!r} does not exist")
        return invocation.model_copy(deep=True)

    async def list_effect(
        self,
        *,
        run_id: str,
        node_run_id: str,
        binding_id: str,
        effect_key: str,
    ) -> list[Invocation]:
        rows = await self._pool.fetch(
            """SELECT payload FROM capability_invocations
               WHERE run_id=$1 AND node_run_id=$2 AND binding_id=$3 AND effect_key=$4
               ORDER BY created_at ASC, invocation_id ASC""",
            run_id,
            node_run_id,
            binding_id,
            effect_key,
        )
        return [_invocation_from_payload(row["payload"]) for row in rows]


def _invocation_from_payload(payload: Any) -> Invocation:
    if isinstance(payload, str):
        return Invocation.model_validate_json(payload)
    return Invocation.model_validate(json.loads(json.dumps(payload)))


__all__ = ["PgInvocationStore", "SqliteInvocationStore"]
