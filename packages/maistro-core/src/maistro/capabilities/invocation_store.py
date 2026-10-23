"""Durable persistence adapter for canonical capability Invocations (SQLite).

The container's capability effect context wires this store for SQLite and uses
:class:`maistro.capabilities.pg_invocation_store.PgInvocationStore` for
PostgreSQL. It is distinct from ``maistro.events.invocations.SqliteInvocationStore``,
which stores handler invocations for the event subsystem — the only
``PgInvocationStore`` for this table. An earlier duplicate lived here too, but
its columns (``payload_json``, a ``datetime`` timestamp) never matched Alembic
revision 035's actual DDL (``payload`` JSONB, ``created_at`` a float) and
nothing in production wired it -- removed rather than fixed (#1079 Finding 3).

The schema is also represented by Alembic revision 035 -- the effect ledger
with its persisted ``effect_scope`` admission column and the Run-scoped
unique claim index. ``ensure_schema`` keeps fresh SQLite databases and
existing local databases compatible while the migration remains the deployment
source of truth for PostgreSQL. Both stores preserve the complete
resolved-provider snapshot and claim effects before dispatch, so a restart or
another worker cannot silently repeat a polling effect.
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
from maistro.sqlite_schema import execute_schema_script, serialized_schema_upgrade

if TYPE_CHECKING:
    import aiosqlite


_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS capability_invocations (
    invocation_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    node_run_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    binding_id TEXT NOT NULL,
    effect_key TEXT NOT NULL,
    effect_scope TEXT NOT NULL DEFAULT '',
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
``effect_scope or node_run_id``; every write normalizes an empty scope to the
node_run_id (see ``_row_values``), so the partial unique index spans NodeRun
visits exactly like the in-memory store's ``effect_identity`` guard.

The UPDATE + DROP + CREATE trio is an in-place schema migration as well as the
fresh schema definition, mirroring ``idx_canonical_runs_occurrence`` in the
canonical Runs store: ``CREATE UNIQUE INDEX IF NOT EXISTS`` would silently keep
the pre-scope ``node_run_id``-keyed index on an existing SQLite file, and two
concurrent NodeRun visits of one logical effect could then dispatch the same
external effect twice. The predicate covers every non-FAILED status -- a
completed prior record must also refuse a second claim, closing the
check-then-insert window where the first visit terminalizes between the
loser's history read and its insert. The UPDATE backfills the scope of rows
written before the column existed so index creation cannot fail on legacy
data: under the old contract at most one row per
``(run_id, node_run_id, binding_id, effect_key)`` was ever non-failed (the old
admission check blocked every non-failed duplicate), so the backfilled scopes
stay unique within the index predicate."""


class SqliteInvocationStore:
    """SQLite InvocationStore preserving complete resolved-provider provenance."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
        self._lock = asyncio.Lock()

    async def ensure_schema(self) -> None:
        async with serialized_schema_upgrade(self._conn):
            await execute_schema_script(self._conn, _TABLE_DDL)
            columns = await self._conn.execute("PRAGMA table_info(capability_invocations)")
            existing = {str(row[1]) for row in await columns.fetchall()}
            # Column backfills must precede the claim DDL: a legacy database
            # may lack ``effect_scope``/``revision``, and the claim UPDATE and
            # index reference the column.
            if "effect_scope" not in existing:
                await self._conn.execute(
                    "ALTER TABLE capability_invocations ADD COLUMN effect_scope TEXT NOT NULL DEFAULT ''"
                )
            if "revision" not in existing:
                await self._conn.execute(
                    "ALTER TABLE capability_invocations ADD COLUMN revision INTEGER NOT NULL DEFAULT 0"
                )
            await execute_schema_script(self._conn, _CLAIM_DDL)

    async def create(self, invocation: Invocation) -> Invocation:
        async with self._lock:
            # Serialize the active-effect check with the insert across all
            # connections. The check and the partial unique index both key the
            # logical effect identity (``effect_scope or node_run_id``), so a
            # concurrent NodeRun visit of the same stable effect is refused
            # here and not merely by the in-process history read (#1194).
            # A failed loser must be reported as an unsafe retry and must not
            # leave its connection holding a transaction lock.
            try:
                await self._conn.execute("BEGIN IMMEDIATE")
                cursor = await self._conn.execute(
                    """SELECT 1 FROM capability_invocations
                       WHERE run_id = ? AND effect_scope = ? AND binding_id = ?
                         AND effect_key = ? AND status IN (?, ?, ?, ?)
                       LIMIT 1""",
                    (
                        invocation.run_id,
                        invocation.effect_scope or invocation.node_run_id,
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
                        effect_key, effect_scope, status, revision, created_at, payload_json
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
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
                    effect_key = ?, effect_scope = ?, status = ?, revision = ?, created_at = ?, payload_json = ?
                   WHERE invocation_id = ? AND revision = ?""",
                (
                    invocation.run_id,
                    invocation.node_run_id,
                    invocation.attempt_id,
                    invocation.binding.binding_id,
                    invocation.effect_key,
                    invocation.effect_scope or invocation.node_run_id,
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

    async def claim(self, invocation: Invocation) -> Invocation:
        """Serialize the logical effect across connections, not just instances.

        ``BEGIN IMMEDIATE`` takes the database write lock before the history
        read, so two workers on separate connections cannot both observe an
        empty history and double-dispatch. The re-read keys the normalized
        logical identity (``effect_scope or node_run_id``), so a retry under a
        new NodeRun with the same stable scope sees the winner's row (#1194).
        The partial unique index is the final guard; a losing insert is
        reported as an unsafe retry instead of leaving the connection holding
        a transaction lock. A completed prior under the same logical scope is
        a replay and is returned, not raised.
        """
        async with self._lock:
            try:
                await self._conn.execute("BEGIN IMMEDIATE")
                cursor = await self._conn.execute(
                    """SELECT payload_json FROM capability_invocations
                       WHERE run_id = ? AND effect_scope = ? AND binding_id = ?
                         AND effect_key = ?
                       ORDER BY created_at DESC, invocation_id DESC LIMIT 1""",
                    (
                        invocation.run_id,
                        invocation.effect_scope or invocation.node_run_id,
                        invocation.binding.binding_id,
                        invocation.effect_key,
                    ),
                )
                row = await cursor.fetchone()
                if row is not None:
                    existing = Invocation.model_validate_json(str(row[0]))
                    if existing.status is InvocationStatus.COMPLETED:
                        await self._conn.rollback()
                        return existing
                    if existing.status is not InvocationStatus.FAILED:
                        raise UnsafeEffectRetry(
                            f"effect {invocation.effect_key!r} has outcome "
                            f"{existing.status.value!r}; manual/reconciliation evidence "
                            "is required before retry"
                        )
                await self._conn.execute(
                    """INSERT INTO capability_invocations (
                        invocation_id, run_id, node_run_id, attempt_id, binding_id,
                        effect_key, effect_scope, status, revision, created_at, payload_json
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    self._row_values(invocation),
                )
                await self._conn.commit()
            except UnsafeEffectRetry:
                await self._conn.rollback()
                raise
            except sqlite3.IntegrityError as exc:
                await self._conn.rollback()
                raise UnsafeEffectRetry(
                    f"effect {invocation.effect_key!r} already has an active or "
                    "completed Invocation"
                ) from exc
            except BaseException:
                await self._conn.rollback()
                raise
            return invocation.model_copy(deep=True)

    async def list_effect(
        self,
        *,
        run_id: str,
        node_run_id: str | None,
        binding_id: str,
        effect_key: str,
        effect_scope: str | None = None,
    ) -> list[Invocation]:
        params: tuple[str, ...]
        if effect_scope is not None:
            query = """SELECT payload_json FROM capability_invocations
               WHERE run_id = ? AND effect_scope = ? AND binding_id = ? AND effect_key = ?
               ORDER BY created_at ASC, invocation_id ASC"""
            params = (run_id, effect_scope, binding_id, effect_key)
        elif node_run_id is not None:
            query = """SELECT payload_json FROM capability_invocations
               WHERE run_id = ? AND node_run_id = ? AND binding_id = ? AND effect_key = ?
               ORDER BY created_at ASC, invocation_id ASC"""
            params = (run_id, node_run_id, binding_id, effect_key)
        else:
            # ``node_run_id=None`` spans every node run under the run for this
            # binding+effect_key pair (the develop list_effect contract). In
            # SQL the discriminator is dropped rather than bound to NULL: an
            # ``= NULL`` comparison matches no row at all.
            query = """SELECT payload_json FROM capability_invocations
               WHERE run_id = ? AND binding_id = ? AND effect_key = ?
               ORDER BY created_at ASC, invocation_id ASC"""
            params = (run_id, binding_id, effect_key)
        cursor = await self._conn.execute(query, params)
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
        # The scope column carries the logical effect identity: an empty
        # ``effect_scope`` means the identity is the physical node_run_id, and
        # the claim index keys the normalized value, never ``''``.
        return (
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
            invocation.model_dump_json(),
        )


__all__ = ["SqliteInvocationStore"]
