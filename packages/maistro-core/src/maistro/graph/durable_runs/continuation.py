"""What is left of a durable graph run once the spine is the store's.

`DurableRunRecord` is two things wearing one shape: the canonical Run,
NodeRuns and Attempts -- which belong in `RunStore` and nowhere else -- and the
Graph-specific continuation that has no home on the spine at all, because a
frontier, a blackboard and a routing history are not execution lifecycle
(ADR-062, ADR-082826-d9f5). This module is that second half, stored beside the
canonical rows rather than wrapped around them.

The index columns (`status`, `project_id`, `created_at`, `resume_at`) are
denormalized from the canonical Run/continuation on every write. They exist so
recovery can find eligible graph runs with bounded indexed queries rather than
a scan of every Run on the spine; the Run remains the lifecycle authority, and
assembly always reads the status back from it.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from maistro.graph.execution_state import GraphExecutionState
from maistro.graph.traversal_commit import TraversalCheckpoint, TraversalCommit
from maistro.runs.model import RunStatus

from .types import DurableRunRecord

if TYPE_CHECKING:  # pragma: no cover - typing only
    import aiosqlite

_RECOVERY_VISIBLE_STATUSES = frozenset({RunStatus.WAITING, RunStatus.PAUSED, RunStatus.RUNNING})


class GraphContinuation(BaseModel):
    """Graph traversal state for one canonical Run, and its lookup columns."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    graph_state: GraphExecutionState
    traversal_checkpoints: tuple[TraversalCheckpoint, ...] = Field(default_factory=tuple)
    traversal_commits: tuple[TraversalCommit, ...] = Field(default_factory=tuple)
    resume_at: datetime | None = None
    version: int = Field(default=0, ge=0)
    status: RunStatus = RunStatus.CREATED
    project_id: str = ""
    created_at: datetime | None = None

    @classmethod
    def of(cls, record: DurableRunRecord) -> GraphContinuation:
        return cls(
            run_id=record.run_id,
            graph_state=record.graph_state,
            traversal_checkpoints=record.traversal_checkpoints,
            traversal_commits=record.traversal_commits,
            resume_at=record.resume_at,
            version=record.version,
            status=record.run.status,
            project_id=record.run.project_id,
            created_at=record.run.created_at,
        )


@runtime_checkable
class GraphContinuationStore(Protocol):
    """Persist the Graph half of a durable run, keyed by canonical Run id."""

    async def create(self, continuation: GraphContinuation) -> GraphContinuation: ...

    async def get(self, run_id: str) -> GraphContinuation | None: ...

    async def update(self, continuation: GraphContinuation) -> GraphContinuation:
        """Persist a strictly newer optimistic-concurrency version."""
        ...

    async def delete(self, run_id: str) -> bool: ...

    async def list_run_ids_by_status(
        self,
        status: RunStatus,
        *,
        limit: int = 100,
        project_id: str | None = None,
        after: tuple[str, str] | None = None,
    ) -> list[str]:
        """Run ids in ``status``, oldest-created-first.

        ``after`` is a ``(created_at_iso, run_id)`` keyset cursor: strictly
        newer than what a caller has already inspected. Fair bounded scans
        (#1056, #1109) page through it rather than re-reading the same fixed
        prefix every tick.
        """
        ...

    async def list_due_run_ids(
        self,
        *,
        now: datetime,
        limit: int = 100,
        after: tuple[str, str] | None = None,
    ) -> list[str]:
        """Return persisted wait/claim continuations whose deadline is due.

        ``after`` is a ``(resume_at_iso, run_id)`` keyset cursor, the same
        deadline-then-run_id order the underlying index uses (#1098).
        """
        ...

    async def list_run_ids_for_project(self, project_id: str, *, limit: int = 25) -> list[str]: ...


def _clone(continuation: GraphContinuation) -> GraphContinuation:
    return GraphContinuation.model_validate_json(continuation.model_dump_json())


def _created_cursor(row: GraphContinuation) -> tuple[str, str]:
    """The ``(created_at_iso, run_id)`` keyset position of one row (#1056, #1109)."""
    created = row.created_at.isoformat() if row.created_at is not None else ""
    return (created, row.run_id)


def _due_cursor(row: GraphContinuation) -> tuple[str, str]:
    """The ``(resume_at_iso, run_id)`` keyset position of one due row (#1098)."""
    assert row.resume_at is not None  # narrowed by the due-status/deadline filter above
    return (row.resume_at.isoformat(), row.run_id)


class InMemoryGraphContinuationStore:
    """In-process continuation store, for tests and single-process homelab runs."""

    def __init__(self) -> None:
        self._rows: dict[str, GraphContinuation] = {}
        self._lock = asyncio.Lock()

    async def create(self, continuation: GraphContinuation) -> GraphContinuation:
        async with self._lock:
            if continuation.run_id in self._rows:
                raise ValueError(f"run_id collision: {continuation.run_id!r}")
            self._rows[continuation.run_id] = _clone(continuation)
            return _clone(continuation)

    async def get(self, run_id: str) -> GraphContinuation | None:
        stored = self._rows.get(run_id)
        return _clone(stored) if stored is not None else None

    async def update(self, continuation: GraphContinuation) -> GraphContinuation:
        async with self._lock:
            existing = self._rows.get(continuation.run_id)
            if existing is None:
                raise KeyError(f"no such run: {continuation.run_id!r}")
            if continuation.version <= existing.version:
                raise ValueError(
                    f"version regression: stored={existing.version} incoming={continuation.version}"
                )
            self._rows[continuation.run_id] = _clone(continuation)
            return _clone(continuation)

    async def delete(self, run_id: str) -> bool:
        async with self._lock:
            return self._rows.pop(run_id, None) is not None

    async def list_run_ids_by_status(
        self,
        status: RunStatus,
        *,
        limit: int = 100,
        project_id: str | None = None,
        after: tuple[str, str] | None = None,
    ) -> list[str]:
        rows = [
            row
            for row in self._rows.values()
            if row.status is status and (project_id is None or row.project_id == project_id)
        ]
        rows.sort(key=lambda row: (row.created_at or datetime.min, row.run_id))
        if after is not None:
            rows = [row for row in rows if _created_cursor(row) > after]
        return [row.run_id for row in rows[:limit]]

    async def list_due_run_ids(
        self,
        *,
        now: datetime,
        limit: int = 100,
        after: tuple[str, str] | None = None,
    ) -> list[str]:
        rows = [
            row
            for row in self._rows.values()
            if row.status in _RECOVERY_VISIBLE_STATUSES
            and row.resume_at is not None
            and row.resume_at <= now
        ]
        rows.sort(key=lambda row: (row.resume_at, row.run_id))
        if after is not None:
            rows = [row for row in rows if _due_cursor(row) > after]
        return [row.run_id for row in rows[:limit]]

    async def list_run_ids_for_project(self, project_id: str, *, limit: int = 25) -> list[str]:
        rows = [row for row in self._rows.values() if row.project_id == project_id]
        rows.sort(
            key=lambda row: (row.created_at or datetime.min, row.run_id),
            reverse=True,
        )
        return [row.run_id for row in rows[:limit]]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS graph_continuations (
    run_id            TEXT PRIMARY KEY,
    status            TEXT NOT NULL,
    project_id        TEXT NOT NULL,
    created_at        TEXT,
    resume_at         TEXT,
    version           INTEGER NOT NULL DEFAULT 0,
    continuation_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_graph_continuations_status
    ON graph_continuations (status, project_id);

CREATE INDEX IF NOT EXISTS idx_graph_continuations_project
    ON graph_continuations (project_id, created_at);

CREATE INDEX IF NOT EXISTS idx_graph_continuations_resume_at
    ON graph_continuations (resume_at);
"""


class SqliteGraphContinuationStore:
    """The homelab twin, on the same connection as the canonical spine."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
        self._lock = asyncio.Lock()

    async def ensure_schema(self) -> None:
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()

    async def create(self, continuation: GraphContinuation) -> GraphContinuation:
        async with self._lock:
            if await self._read(continuation.run_id) is not None:
                raise ValueError(f"run_id collision: {continuation.run_id!r}")
            await self._write(continuation, insert=True)
            return _clone(continuation)

    async def get(self, run_id: str) -> GraphContinuation | None:
        return await self._read(run_id)

    async def update(self, continuation: GraphContinuation) -> GraphContinuation:
        async with self._lock:
            existing = await self._read(continuation.run_id)
            if existing is None:
                raise KeyError(f"no such run: {continuation.run_id!r}")
            if continuation.version <= existing.version:
                raise ValueError(
                    f"version regression: stored={existing.version} incoming={continuation.version}"
                )
            await self._write(continuation, insert=False)
            return _clone(continuation)

    async def delete(self, run_id: str) -> bool:
        async with self._lock:
            cursor = await self._conn.execute(
                "DELETE FROM graph_continuations WHERE run_id = ?",
                (run_id,),
            )
            await self._conn.commit()
            return cursor.rowcount > 0

    async def list_run_ids_by_status(
        self,
        status: RunStatus,
        *,
        limit: int = 100,
        project_id: str | None = None,
        after: tuple[str, str] | None = None,
    ) -> list[str]:
        sql = "SELECT run_id FROM graph_continuations WHERE status = ?"
        params: list[object] = [status.value]
        if project_id is not None:
            sql += " AND project_id = ?"
            params.append(project_id)
        if after is not None:
            sql += " AND (created_at, run_id) > (?, ?)"
            params.extend(after)
        sql += " ORDER BY created_at ASC, run_id ASC LIMIT ?"
        params.append(limit)
        cursor = await self._conn.execute(sql, params)
        return [str(row[0]) for row in await cursor.fetchall()]

    async def list_due_run_ids(
        self,
        *,
        now: datetime,
        limit: int = 100,
        after: tuple[str, str] | None = None,
    ) -> list[str]:
        sql = """SELECT run_id FROM graph_continuations
                WHERE status IN (?, ?, ?)
                  AND resume_at IS NOT NULL
                  AND resume_at <= ?"""
        params: list[object] = [
            RunStatus.WAITING.value,
            RunStatus.PAUSED.value,
            RunStatus.RUNNING.value,
            now.isoformat(),
        ]
        if after is not None:
            sql += " AND (resume_at, run_id) > (?, ?)"
            params.extend(after)
        sql += " ORDER BY resume_at ASC, run_id ASC LIMIT ?"
        params.append(limit)
        cursor = await self._conn.execute(sql, params)
        return [str(row[0]) for row in await cursor.fetchall()]

    async def list_run_ids_for_project(self, project_id: str, *, limit: int = 25) -> list[str]:
        cursor = await self._conn.execute(
            "SELECT run_id FROM graph_continuations WHERE project_id = ? "
            "ORDER BY created_at DESC, run_id DESC LIMIT ?",
            (project_id, limit),
        )
        return [str(row[0]) for row in await cursor.fetchall()]

    async def _read(self, run_id: str) -> GraphContinuation | None:
        cursor = await self._conn.execute(
            "SELECT continuation_json FROM graph_continuations WHERE run_id = ?",
            (run_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return GraphContinuation.model_validate_json(row[0])

    async def _write(self, continuation: GraphContinuation, *, insert: bool) -> None:
        values = (
            continuation.status.value,
            continuation.project_id,
            continuation.created_at.isoformat() if continuation.created_at else None,
            continuation.resume_at.isoformat() if continuation.resume_at else None,
            continuation.version,
            continuation.model_dump_json(),
        )
        if insert:
            await self._conn.execute(
                """INSERT INTO graph_continuations
                       (status, project_id, created_at, resume_at, version,
                        continuation_json, run_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (*values, continuation.run_id),
            )
        else:
            await self._conn.execute(
                """UPDATE graph_continuations
                      SET status = ?, project_id = ?, created_at = ?, resume_at = ?,
                          version = ?, continuation_json = ?
                    WHERE run_id = ?""",
                (*values, continuation.run_id),
            )
        await self._conn.commit()


__all__ = [
    "GraphContinuation",
    "GraphContinuationStore",
    "InMemoryGraphContinuationStore",
    "SqliteGraphContinuationStore",
]
