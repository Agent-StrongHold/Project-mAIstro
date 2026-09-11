"""Durable persistence adapters for canonical capability Invocations.

The container's capability effect context wires this store for SQLite and
uses :class:`PgInvocationStore` for PostgreSQL. The similarly named
:class:`maistro.events.invocations.SqliteInvocationStore` is a separate handler
invocation store and is not interchangeable with this one.

The capability tables are created by ``ensure_schema`` rather than an Alembic
revision. Both stores preserve the complete resolved-provider snapshot and
claim logical effects before dispatch, so a restart or another worker cannot
silently repeat a polling effect.
"""

from __future__ import annotations

import asyncio
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
    payload_json TEXT NOT NULL
);
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
            await self._conn.execute(
                """INSERT INTO capability_invocations (
                    invocation_id, run_id, node_run_id, attempt_id, binding_id,
                    effect_key, status, created_at, payload_json
                ) VALUES (?,?,?,?,?,?,?,?,?)""",
                self._row_values(invocation),
            )
            await self._conn.commit()
        return invocation.model_copy(deep=True)

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

    async def claim(self, invocation: Invocation) -> Invocation:
        """Serialize the logical effect on the shared SQLite connection."""
        async with self._lock:
            cursor = await self._conn.execute(
                """SELECT payload_json FROM capability_invocations
                   WHERE run_id = ? AND node_run_id = ? AND binding_id = ? AND effect_key = ?
                   ORDER BY created_at DESC, invocation_id DESC LIMIT 1""",
                (
                    invocation.run_id,
                    invocation.node_run_id,
                    invocation.binding.binding_id,
                    invocation.effect_key,
                ),
            )
            row = await cursor.fetchone()
            if row is not None:
                existing = Invocation.model_validate_json(str(row[0]))
                if existing.status is InvocationStatus.FAILED:
                    pass
                elif existing.status is InvocationStatus.COMPLETED:
                    return existing
                else:
                    raise UnsafeEffectRetry(
                        f"effect {invocation.effect_key!r} has outcome "
                        f"{existing.status.value!r}; manual/reconciliation evidence is required before retry"
                    )
            await self._conn.execute(
                """INSERT INTO capability_invocations (
                    invocation_id, run_id, node_run_id, attempt_id, binding_id,
                    effect_key, status, created_at, payload_json
                ) VALUES (?,?,?,?,?,?,?,?,?)""",
                self._row_values(invocation),
            )
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
    """PostgreSQL InvocationStore with an advisory-locked effect claim."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def ensure_schema(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS capability_invocations (
                    invocation_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    node_run_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL,
                    binding_id TEXT NOT NULL,
                    effect_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at DOUBLE PRECISION NOT NULL,
                    payload_json JSONB NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_capability_invocation_effect
                    ON capability_invocations
                    (run_id, node_run_id, binding_id, effect_key, created_at, invocation_id);
                """
            )

    @staticmethod
    def _decode(value: Any) -> Invocation:
        return (
            Invocation.model_validate_json(value)
            if isinstance(value, str)
            else Invocation.model_validate(value)
        )

    @staticmethod
    def _identity(invocation: Invocation) -> str:
        return ":".join(invocation.effect_identity)

    async def create(self, invocation: Invocation) -> Invocation:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO capability_invocations (
                    invocation_id, run_id, node_run_id, attempt_id, binding_id,
                    effect_key, status, created_at, payload_json
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb)""",
                *SqliteInvocationStore._row_values(invocation)[:8],
                invocation.model_dump_json(),
            )
        return invocation.model_copy(deep=True)

    async def claim(self, invocation: Invocation) -> Invocation:
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                f"capability-effect:{self._identity(invocation)}",
            )
            row = await conn.fetchrow(
                """SELECT payload_json FROM capability_invocations
                   WHERE run_id=$1 AND node_run_id=$2 AND binding_id=$3 AND effect_key=$4
                   ORDER BY created_at DESC, invocation_id DESC LIMIT 1 FOR UPDATE""",
                invocation.run_id,
                invocation.node_run_id,
                invocation.binding.binding_id,
                invocation.effect_key,
            )
            if row is not None:
                existing = self._decode(row["payload_json"])
                if existing.status is InvocationStatus.FAILED:
                    pass
                elif existing.status is InvocationStatus.COMPLETED:
                    return existing
                else:
                    raise UnsafeEffectRetry(
                        f"effect {invocation.effect_key!r} has outcome "
                        f"{existing.status.value!r}; manual/reconciliation evidence is required before retry"
                    )
            await conn.execute(
                """INSERT INTO capability_invocations (
                    invocation_id, run_id, node_run_id, attempt_id, binding_id,
                    effect_key, status, created_at, payload_json
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb)""",
                *SqliteInvocationStore._row_values(invocation)[:8],
                invocation.model_dump_json(),
            )
            return invocation.model_copy(deep=True)

    async def get(self, invocation_id: str) -> Invocation | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT payload_json FROM capability_invocations WHERE invocation_id=$1",
                invocation_id,
            )
        return self._decode(row["payload_json"]) if row is not None else None

    async def save(self, invocation: Invocation) -> Invocation:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """UPDATE capability_invocations SET
                    run_id=$1, node_run_id=$2, attempt_id=$3, binding_id=$4,
                    effect_key=$5, status=$6, created_at=$7, payload_json=$8::jsonb
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
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT payload_json FROM capability_invocations
                   WHERE run_id=$1 AND node_run_id=$2 AND binding_id=$3 AND effect_key=$4
                   ORDER BY created_at ASC, invocation_id ASC""",
                run_id,
                node_run_id,
                binding_id,
                effect_key,
            )
        return [self._decode(row["payload_json"]) for row in rows]


__all__ = ["PgInvocationStore", "SqliteInvocationStore"]
