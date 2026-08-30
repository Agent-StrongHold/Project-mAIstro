"""Durable persistence adapters for canonical capability Invocations.

**Unreached, and durable only in the SQLite sense.** Nothing constructs
:class:`SqliteInvocationStore` outside tests. The container does wire a class of
the same name -- :class:`maistro.events.invocations.SqliteInvocationStore`, a
different store over a different table -- and both are re-exported from
:mod:`maistro.capabilities`, so the collision is easy to read the wrong way
round. The wired one is the events store; this one is not wired.

Its table has no migration. ``capability_invocations`` is created by
``ensure_schema`` and appears in no revision under ``alembic/versions``, so it
does not exist in any PostgreSQL deployment and there is no PostgreSQL twin of
this store. That is a consequence of being unreached, not an omission to fix
separately: the migration lands with the wiring, in #55.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from maistro.capabilities.invocation import Invocation

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


__all__ = ["SqliteInvocationStore"]
