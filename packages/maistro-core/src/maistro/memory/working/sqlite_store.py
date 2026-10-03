"""Durable workspace working-memory log over the deployment's SQLite database.

Same convention as ``workspaces/campaigns/sqlite_store.py`` (which follows
``quota/sqlite_usage_log.py``): an injected ``aiosqlite`` connection, plain
typed columns for everything that filters or orders, a JSON payload column
the model round-trips through, and an ``ensure_schema()`` that runs through
the shared ``serialized_schema_upgrade`` discipline so concurrent
initializations sharing one database cannot interleave. One connection, one
operation lock: append and commit stay one operation for ordinary callers.

Two tables, both append-only in practice:

* ``workspace_working_log`` — the observation log. Rows are never updated or
  deleted except by ``purge_workspace`` (retention, driven by Workspace
  deletion); resets and simplification are appended markers, so the log
  stays a lossless record (#301, M4-H).
* ``workspace_working_results`` — full results behind references,
  content-addressed per Workspace. Identical results inside one Workspace
  are one row; ``put_result`` is idempotent.

Retention is declared in ``quality/durable-table-retention.json`` with
``purge_workspace`` as the driven deletion path.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING, Any

from maistro.memory.working.types import (
    ObservationKind,
    WorkingResult,
    WorkspaceObservation,
)
from maistro.sqlite_schema import serialized_schema_upgrade

if TYPE_CHECKING:
    import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS workspace_working_log (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id TEXT NOT NULL,
    entry_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    cycle INTEGER NOT NULL,
    run_id TEXT NOT NULL DEFAULT '',
    result_ref TEXT,
    digest TEXT NOT NULL DEFAULT '',
    survive_reset INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    UNIQUE (workspace_id, entry_id)
)
"""

_LOG_INDEX_SCHEMA = """
CREATE INDEX IF NOT EXISTS idx_workspace_working_log_ws
    ON workspace_working_log (workspace_id, seq)
"""

_RESULTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS workspace_working_results (
    workspace_id TEXT NOT NULL,
    result_id TEXT NOT NULL,
    source TEXT NOT NULL,
    digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    content TEXT NOT NULL,
    meta TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (workspace_id, result_id)
)
"""


def _entry_row(entry: WorkspaceObservation) -> tuple[Any, ...]:
    return (
        entry.workspace_id,
        entry.entry_id,
        entry.kind.value,
        entry.cycle,
        entry.run_id,
        entry.result_ref,
        entry.digest,
        int(entry.survive_reset),
        entry.created_at.isoformat(),
        entry.to_json(),
    )


def _entry_from_row(row: Any) -> WorkspaceObservation:
    """Rebuild an entry with its log position from the row, not the payload:
    ``seq`` belongs to the log (it is assigned on ``append``), so the column
    is authoritative and the payload's ``seq`` (``None`` for a pre-append
    entry) is ignored."""
    return replace(WorkspaceObservation.from_json(str(row[1])), seq=int(row[0]))


class SqliteWorkspaceLogStore:
    """The durable twin. Must agree with :class:`InMemoryWorkspaceLogStore`
    on every rule the conformance suite exercises."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
        self._lock = asyncio.Lock()

    async def ensure_schema(self) -> None:
        async with self._lock, serialized_schema_upgrade(self._conn):
            for script in (_SCHEMA, _LOG_INDEX_SCHEMA, _RESULTS_SCHEMA):
                await self._conn.execute(script)

    async def append(self, entry: WorkspaceObservation) -> WorkspaceObservation:
        async with self._lock:
            cursor = await self._conn.execute(
                "INSERT INTO workspace_working_log"
                " (workspace_id, entry_id, kind, cycle, run_id, result_ref,"
                "  digest, survive_reset, created_at, payload)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                _entry_row(entry),
            )
            stored = replace(entry, seq=cursor.lastrowid)
            await self._conn.commit()
            return stored

    async def list_entries(
        self,
        workspace_id: str,
        *,
        kinds: tuple[ObservationKind, ...] | None = None,
        after_seq: int = 0,
        limit: int | None = None,
        survive_reset: bool | None = None,
    ) -> list[WorkspaceObservation]:
        sql = "SELECT seq, payload FROM workspace_working_log WHERE workspace_id = ? AND seq > ?"
        params: list[Any] = [workspace_id, after_seq]
        if kinds is not None:
            sql += f" AND kind IN ({', '.join('?' for _ in kinds)})"
            params.extend(k.value for k in kinds)
        if survive_reset is not None:
            sql += " AND survive_reset = ?"
            params.append(int(survive_reset))
        sql += " ORDER BY seq ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        async with self._lock:
            cursor = await self._conn.execute(sql, params)
            rows = await cursor.fetchall()
        return [_entry_from_row(row) for row in rows]

    async def get_entry(self, workspace_id: str, entry_id: str) -> WorkspaceObservation | None:
        async with self._lock:
            cursor = await self._conn.execute(
                "SELECT seq, payload FROM workspace_working_log"
                " WHERE workspace_id = ? AND entry_id = ?",
                (workspace_id, entry_id),
            )
            row = await cursor.fetchone()
        return _entry_from_row(row) if row is not None else None

    async def latest_entry(
        self,
        workspace_id: str,
        *,
        kinds: tuple[ObservationKind, ...] | None = None,
    ) -> WorkspaceObservation | None:
        sql = "SELECT seq, payload FROM workspace_working_log WHERE workspace_id = ?"
        params: list[Any] = [workspace_id]
        if kinds is not None:
            sql += f" AND kind IN ({', '.join('?' for _ in kinds)})"
            params.extend(k.value for k in kinds)
        sql += " ORDER BY seq DESC LIMIT 1"
        async with self._lock:
            cursor = await self._conn.execute(sql, params)
            row = await cursor.fetchone()
        return _entry_from_row(row) if row is not None else None

    async def put_result(self, result: WorkingResult) -> bool:
        async with self._lock:
            cursor = await self._conn.execute(
                "INSERT OR IGNORE INTO workspace_working_results"
                " (workspace_id, result_id, source, digest, created_at, content, meta)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    result.workspace_id,
                    result.result_id,
                    result.source,
                    result.digest,
                    result.created_at.isoformat(),
                    result.content,
                    json.dumps(result.meta, sort_keys=True),
                ),
            )
            await self._conn.commit()
            return cursor.rowcount > 0

    async def get_result(self, workspace_id: str, result_id: str) -> WorkingResult | None:
        async with self._lock:
            cursor = await self._conn.execute(
                "SELECT source, digest, created_at, content, meta"
                " FROM workspace_working_results WHERE workspace_id = ? AND result_id = ?",
                (workspace_id, result_id),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return WorkingResult(
            workspace_id=workspace_id,
            result_id=result_id,
            source=str(row[0]),
            content=str(row[3]),
            created_at=datetime.fromisoformat(str(row[2])),
            meta=json.loads(str(row[4])),
        )

    async def purge_workspace(self, workspace_id: str) -> int:
        async with self._lock:
            cursor = await self._conn.execute(
                "DELETE FROM workspace_working_log WHERE workspace_id = ?",
                (workspace_id,),
            )
            purged = cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
            await self._conn.execute(
                "DELETE FROM workspace_working_results WHERE workspace_id = ?",
                (workspace_id,),
            )
            await self._conn.commit()
        return purged
