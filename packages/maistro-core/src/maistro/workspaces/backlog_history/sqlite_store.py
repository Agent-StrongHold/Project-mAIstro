"""SQLite persistence for the Workspace BacklogItem history (#101).

Append-only by construction: the only write is an `INSERT`, and the only read
is ordered by the per-(workspace, item) `sequence` the store assigns inside
its own `BEGIN IMMEDIATE` — read and insert are one transaction, so a second
process on the same file cannot record two entries as the same point in the
story, and the `UNIQUE` index is the constraint's own backstop.

The journal holds its own connection, as the session (#327) and schedule
(#1199) stores hold theirs: the connection the Project and Run stores share
carries writers — `ClaimingSqliteRunStore` foremost — whose locks, commits and
rollbacks are their own, so a journal transaction paused between its sequence
read and its insert would have a sibling's `commit()` land inside it, or a
sibling's `rollback()` discard it, while `append()` reported success. A
transaction belongs to its connection; this one is the journal's alone.

There is deliberately no foreign key to `workspace_backlog_items`: that table
belongs to the #98 slice and this journal must not fail to exist where items
are not durable yet. An entry is scoped by (workspace_id, project_id, item_id)
identity, the same identity the item store uses.
"""

from __future__ import annotations

import asyncio
import builtins
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from maistro.sqlite_schema import execute_schema_script, serialized_schema_upgrade
from maistro.workspaces.backlog_history.model import (
    BacklogEventAlreadyExists,
    BacklogHistoryError,
    BacklogHistoryEvent,
    BacklogHistoryEventKind,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS workspace_backlog_history (
    event_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    kind TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    UNIQUE (workspace_id, item_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_workspace_backlog_history_workspace
    ON workspace_backlog_history(workspace_id, project_id, item_id, sequence);
"""

_NEXT_SEQUENCE = """
SELECT COALESCE(MAX(sequence), 0) + 1 FROM workspace_backlog_history
 WHERE workspace_id = ? AND item_id = ?
"""

_SELECT = """
SELECT payload FROM workspace_backlog_history
 WHERE workspace_id = ?
   AND (? IS NULL OR project_id = ?)
   AND (? IS NULL OR item_id = ?)
   AND (? IS NULL OR kind = ?)
 ORDER BY item_id, sequence
"""


class SqliteBacklogHistoryStore:
    """Durable, append-only BacklogItem history for a single instance."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
        # One connection, so this orders same-process writers; `BEGIN
        # IMMEDIATE` is what protects a second process sharing this file.
        # The lock is this store's, so the connection must be too: a sibling
        # store paused between its DML and its commit on a shared connection
        # is an unlocked writer mid-transaction, and this rollback below would
        # then discard *its* work — the reason the container opens the journal
        # its own connection, as it does the session store's (#327) and the
        # schedule store's (#1199).
        self._write_lock = asyncio.Lock()

    async def ensure_schema(self) -> None:
        await self._conn.execute("PRAGMA foreign_keys = ON")
        async with serialized_schema_upgrade(self._conn):
            await execute_schema_script(self._conn, _SCHEMA)

    @asynccontextmanager
    async def _serialized_write(self) -> AsyncIterator[None]:
        """Take this connection's one write-critical section.

        `BEGIN IMMEDIATE` takes SQLite's write lock before the sequence read
        rather than at the insert, which is what makes `append`'s read-then-
        write one unit instead of two halves another writer can land between.
        """
        async with self._write_lock:
            await self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                await self._conn.rollback()
                raise
            else:
                await self._conn.commit()

    async def append(self, event: BacklogHistoryEvent) -> BacklogHistoryEvent:
        async with self._serialized_write():
            async with self._conn.execute(
                _NEXT_SEQUENCE, (event.workspace_id, event.item_id)
            ) as cursor:
                row = await cursor.fetchone()
            if row is None:  # pragma: no cover - COALESCE always yields one row
                raise BacklogHistoryError("the history sequence query returned no row")
            (sequence,) = row
            recorded = event.model_copy(update={"sequence": sequence}, deep=True)
            try:
                await self._conn.execute(
                    """INSERT INTO workspace_backlog_history
                           (event_id, workspace_id, project_id, item_id, sequence,
                            kind, occurred_at, payload)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        recorded.event_id,
                        recorded.workspace_id,
                        recorded.project_id,
                        recorded.item_id,
                        sequence,
                        recorded.kind.value,
                        _iso(recorded.occurred_at),
                        recorded.model_dump_json(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise BacklogEventAlreadyExists(recorded.event_id) from exc
        return recorded

    async def history_for_item(
        self,
        workspace_id: str,
        item_id: str,
        *,
        kind: BacklogHistoryEventKind | None = None,
    ) -> builtins.list[BacklogHistoryEvent]:
        return await self._select(workspace_id, item_id=item_id, kind=kind)

    async def history_for_workspace(
        self,
        workspace_id: str,
        *,
        project_id: str | None = None,
        item_id: str | None = None,
        kind: BacklogHistoryEventKind | None = None,
    ) -> builtins.list[BacklogHistoryEvent]:
        return await self._select(workspace_id, project_id=project_id, item_id=item_id, kind=kind)

    async def _select(
        self,
        workspace_id: str,
        *,
        project_id: str | None = None,
        item_id: str | None = None,
        kind: BacklogHistoryEventKind | None = None,
    ) -> builtins.list[BacklogHistoryEvent]:
        kind_value = None if kind is None else BacklogHistoryEventKind(kind).value
        async with self._conn.execute(
            _SELECT,
            (workspace_id, project_id, project_id, item_id, item_id, kind_value, kind_value),
        ) as cursor:
            rows = await cursor.fetchall()
        return [BacklogHistoryEvent.model_validate_json(row[0]) for row in rows]


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


if TYPE_CHECKING:

    def _vulture_store_contract_usage() -> None:
        """Keep the journal contract visible to the production-only scan.

        ``SqliteBacklogHistoryStore.history_for_workspace`` implements the
        Workspace-wide audit read of ``BacklogHistoryStore``; its consumer
        today is the conformance suite, outside the ``packages/*/src`` scope
        Vulture ratchets. See ``maistro.workspaces.backlog_history.store``'s
        shim for the full situation.
        """
        _ = (SqliteBacklogHistoryStore.history_for_workspace,)

    _ = _vulture_store_contract_usage


__all__ = ["SqliteBacklogHistoryStore"]
