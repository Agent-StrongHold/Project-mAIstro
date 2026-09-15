"""Durable persistence adapters for canonical capability Invocations.

This is the SQLite durable adapter for the canonical capability Invocation
lifecycle. It is distinct from ``maistro.events.invocations.SqliteInvocationStore``,
which stores handler invocations for the event subsystem. The container selects
this store for SQLite-backed capability effects; PostgreSQL uses
``maistro.capabilities.pg_invocation_store.PgInvocationStore``.

The schema is also represented by Alembic revision 034. ``ensure_schema`` keeps
fresh SQLite databases and existing local databases compatible while the
migration remains the deployment source of truth for PostgreSQL.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING

from maistro.capabilities.invocation import (
    Invocation,
    InvocationStatus,
    StaleInvocationUpdate,
    UnsafeEffectRetry,
)

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
    revision INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_capability_invocation_effect
    ON capability_invocations (
        run_id, node_run_id, binding_id, effect_key, created_at, invocation_id
    );
CREATE INDEX IF NOT EXISTS idx_capability_invocation_attempt
    ON capability_invocations (attempt_id, created_at, invocation_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_capability_invocation_active_effect
    ON capability_invocations (run_id, node_run_id, binding_id, effect_key)
    WHERE status IN ('created', 'running', 'unknown');
"""


class SqliteInvocationStore:
    """SQLite InvocationStore preserving complete resolved-provider provenance."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
        self._lock = asyncio.Lock()

    async def ensure_schema(self) -> None:
        await self._conn.executescript(_SCHEMA)
        columns = await self._conn.execute("PRAGMA table_info(capability_invocations)")
        if "revision" not in {str(row[1]) for row in await columns.fetchall()}:
            await self._conn.execute(
                "ALTER TABLE capability_invocations ADD COLUMN revision INTEGER NOT NULL DEFAULT 0"
            )
        await self._conn.commit()

    async def create(self, invocation: Invocation) -> Invocation:
        async with self._lock:
            # Serialize the active-effect check with the insert across all
            # connections. The partial unique index is the final guard, but a
            # failed loser must be reported as an unsafe retry and must not
            # leave its connection holding a transaction lock.
            try:
                await self._conn.execute("BEGIN IMMEDIATE")
                cursor = await self._conn.execute(
                    """SELECT 1 FROM capability_invocations
                       WHERE run_id = ? AND node_run_id = ? AND binding_id = ?
                         AND effect_key = ? AND status IN (?, ?, ?, ?)
                       LIMIT 1""",
                    (
                        invocation.run_id,
                        invocation.node_run_id,
                        invocation.binding.binding_id,
                        invocation.effect_key,
                        InvocationStatus.CREATED.value,
                        InvocationStatus.RUNNING.value,
                        InvocationStatus.COMPLETED.value,
                        InvocationStatus.UNKNOWN.value,
                    ),
                )
                if await cursor.fetchone() is not None:
                    await self._conn.rollback()
                    raise UnsafeEffectRetry(
                        f"effect {invocation.effect_key!r} already has an active or completed Invocation"
                    )
                await self._conn.execute(
                    """INSERT INTO capability_invocations (
                        invocation_id, run_id, node_run_id, attempt_id, binding_id,
                        effect_key, status, revision, created_at, payload_json
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    self._row_values(invocation),
                )
                await self._conn.commit()
            except UnsafeEffectRetry:
                raise
            except sqlite3.IntegrityError as exc:
                await self._conn.rollback()
                raise UnsafeEffectRetry(
                    f"effect {invocation.effect_key!r} already has an active or completed Invocation"
                ) from exc
            except BaseException:
                await self._conn.rollback()
                raise
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
                    effect_key = ?, status = ?, revision = ?, created_at = ?, payload_json = ?
                   WHERE invocation_id = ? AND revision = ?""",
                (
                    invocation.run_id,
                    invocation.node_run_id,
                    invocation.attempt_id,
                    invocation.binding.binding_id,
                    invocation.effect_key,
                    invocation.status.value,
                    invocation.revision + 1,
                    invocation.created_at.timestamp(),
                    invocation.model_copy(
                        update={"revision": invocation.revision + 1}
                    ).model_dump_json(),
                    invocation.invocation_id,
                    invocation.revision,
                ),
            )
            if cursor.rowcount != 1:
                current = await self.get(invocation.invocation_id)
                await self._conn.rollback()
                if current is None:
                    raise KeyError(f"Invocation {invocation.invocation_id!r} does not exist")
                raise StaleInvocationUpdate(
                    f"Invocation {invocation.invocation_id!r} was updated concurrently"
                )
            await self._conn.commit()
        return invocation.model_copy(update={"revision": invocation.revision + 1}, deep=True)

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

    async def list_ambiguous(self, *, stale_before: datetime) -> list[Invocation]:
        cursor = await self._conn.execute(
            """SELECT payload_json FROM capability_invocations
               WHERE status IN (?, ?, ?)
               ORDER BY created_at ASC, invocation_id ASC""",
            (
                InvocationStatus.CREATED.value,
                InvocationStatus.RUNNING.value,
                InvocationStatus.UNKNOWN.value,
            ),
        )
        rows = await cursor.fetchall()
        items = [Invocation.model_validate_json(str(row[0])) for row in rows]
        return [
            item
            for item in items
            if item.status is InvocationStatus.UNKNOWN
            or (
                item.status in {InvocationStatus.CREATED, InvocationStatus.RUNNING}
                and (item.started_at or item.created_at) <= stale_before
            )
        ]

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
            invocation.revision,
            invocation.created_at.timestamp(),
            invocation.model_dump_json(),
        )


__all__ = ["SqliteInvocationStore"]
