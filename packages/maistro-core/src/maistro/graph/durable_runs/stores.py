"""Stores for canonical durable graph checkpoints."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from maistro.graph.execution_state import GraphExecutionState, thaw_json_value
from maistro.runs.lifecycle import transition_node_run, transition_run
from maistro.runs.model import RunStatus

from .types import DurableRunRecord


def _clone(record: DurableRunRecord) -> DurableRunRecord:
    return DurableRunRecord.model_validate_json(record.model_dump_json())


def _replace_state(
    state: GraphExecutionState,
    **updates: object,
) -> GraphExecutionState:
    values = state.model_dump(mode="json")
    values.update({key: thaw_json_value(value) for key, value in updates.items()})
    return GraphExecutionState.model_validate(values)


def _replace_record(record: DurableRunRecord, **updates: object) -> DurableRunRecord:
    values = record.model_dump(mode="json")
    values.update({key: thaw_json_value(value) for key, value in updates.items()})
    return DurableRunRecord.model_validate(values)


def _paused_node_run_index(record: DurableRunRecord, node_id: str) -> int:
    for index in range(len(record.node_runs) - 1, -1, -1):
        node_run = record.node_runs[index]
        if node_run.node_id == node_id and node_run.status is RunStatus.PAUSED:
            return index
    raise ValueError(f"run {record.run_id!r} has no paused NodeRun for node {node_id!r}")


def _pause_metadata_after_answer(
    record: DurableRunRecord,
    metadata: dict[str, Any],
    node_id: str,
) -> dict[str, Any]:
    pauses_raw = metadata.get("pauses", {})
    pauses = dict(pauses_raw) if isinstance(pauses_raw, Mapping) else {}
    pauses.pop(node_id, None)
    if not pauses:
        metadata.pop("pauses", None)
        metadata.pop("pause", None)
        return metadata

    metadata["pauses"] = pauses
    first_node_id = next(
        active_id for active_id in record.graph_state.active_node_ids if active_id in pauses
    )
    metadata["pause"] = pauses[first_node_id]
    return metadata


def _answer_record(
    record: DurableRunRecord,
    node_id: str,
    answer: dict[str, Any],
) -> DurableRunRecord:
    if record.run.status is not RunStatus.PAUSED:
        raise ValueError(f"run {record.run_id!r} not paused on HITL (status={record.run.status})")
    if node_id not in record.graph_state.active_node_ids:
        raise ValueError(
            f"run {record.run_id!r} waiting on frontier "
            f"{record.graph_state.active_node_ids!r}, not {node_id!r}"
        )

    paused_index = _paused_node_run_index(record, node_id)
    answered = {**answer, "answered_at": datetime.now(UTC).isoformat()}
    metadata = dict(record.graph_state.metadata)
    answers = dict(record.hitl_answers)
    answers[node_id] = answered
    metadata["hitl_answers"] = answers
    metadata = _pause_metadata_after_answer(record, metadata, node_id)

    node_runs = list(record.node_runs)
    node_runs[paused_index] = transition_node_run(
        node_runs[paused_index],
        RunStatus.QUEUED,
    )
    remaining_paused = any(node_run.status is RunStatus.PAUSED for node_run in node_runs)
    run = record.run if remaining_paused else transition_run(record.run, RunStatus.QUEUED)
    graph_state = _replace_state(record.graph_state, metadata=metadata)
    return _replace_record(
        record,
        run=run,
        graph_state=graph_state,
        node_runs=tuple(node_runs),
        resume_at=record.resume_at if remaining_paused else None,
        version=record.version + 1,
    )


class InMemoryDurableRunStore:
    """In-process optimistic-concurrency checkpoint store."""

    def __init__(self) -> None:
        self._rows: dict[str, DurableRunRecord] = {}
        self._lock = asyncio.Lock()

    async def create(self, record: DurableRunRecord) -> DurableRunRecord:
        async with self._lock:
            if record.run_id in self._rows:
                raise ValueError(f"run_id collision: {record.run_id!r}")
            self._rows[record.run_id] = _clone(record)
            return _clone(self._rows[record.run_id])

    async def get(self, run_id: str) -> DurableRunRecord | None:
        record = self._rows.get(run_id)
        return _clone(record) if record is not None else None

    async def update(self, record: DurableRunRecord) -> DurableRunRecord:
        async with self._lock:
            existing = self._rows.get(record.run_id)
            if existing is None:
                raise KeyError(f"no such run: {record.run_id!r}")
            if record.version <= existing.version:
                raise ValueError(
                    f"version regression: stored={existing.version} incoming={record.version}"
                )
            self._rows[record.run_id] = _clone(record)
            return _clone(self._rows[record.run_id])

    async def list_by_status(
        self,
        status: RunStatus,
        *,
        limit: int = 100,
        project_id: str | None = None,
    ) -> list[DurableRunRecord]:
        out: list[DurableRunRecord] = []
        for record in self._rows.values():
            if record.run.status is not status:
                continue
            if project_id is not None and record.run.project_id != project_id:
                continue
            out.append(_clone(record))
            if len(out) >= limit:
                break
        return out

    async def list_for_project(self, project_id: str, *, limit: int = 25) -> list[DurableRunRecord]:
        runs = [record for record in self._rows.values() if record.run.project_id == project_id]
        runs.sort(key=lambda record: record.run.created_at, reverse=True)
        return [_clone(record) for record in runs[:limit]]

    async def submit_hitl_answer(
        self,
        run_id: str,
        node_id: str,
        answer: dict[str, Any],
    ) -> DurableRunRecord:
        async with self._lock:
            record = self._rows.get(run_id)
            if record is None:
                raise KeyError(f"no such run: {run_id!r}")
            updated = _answer_record(record, node_id, answer)
            self._rows[run_id] = updated
            return _clone(updated)


_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS durable_graph_runs (
    run_id          TEXT PRIMARY KEY,
    status          TEXT NOT NULL,
    active_node_id  TEXT,
    project_id      TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    resume_at       TEXT,
    version         INTEGER NOT NULL DEFAULT 0,
    record_json     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_durable_graph_runs_status
    ON durable_graph_runs(status);
CREATE INDEX IF NOT EXISTS idx_durable_graph_runs_project
    ON durable_graph_runs(project_id);
CREATE INDEX IF NOT EXISTS idx_durable_graph_runs_resume_at
    ON durable_graph_runs(resume_at);
"""

_LEGACY_TABLE = "durable_runs"


def _legacy_row_count(conn: sqlite3.Connection) -> int:
    """Return legacy durable row count without assuming the legacy column schema."""
    table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (_LEGACY_TABLE,),
    ).fetchone()
    if table is None:
        return 0
    row = conn.execute("SELECT COUNT(*) AS count FROM durable_runs").fetchone()
    return int(row["count"] if isinstance(row, sqlite3.Row) else row[0])


def _reject_unmigrated_legacy_rows(conn: sqlite3.Connection) -> None:
    """Refuse to hide legacy records that cannot be scope-migrated safely."""
    count = _legacy_row_count(conn)
    if count == 0:
        return
    raise RuntimeError(
        "legacy durable_runs contains "
        f"{count} persisted run(s) from the pre-canonical schema; automatic migration is unsafe "
        "because those records do not carry workspace_id. Migrate or explicitly archive the "
        "legacy rows before opening the canonical durable graph store."
    )


class SqliteDurableRunStore:
    """SQLite-backed canonical durable graph checkpoint store.

    The pre-canonical store used ``durable_runs`` records that had Project but
    no Workspace ownership. Those rows cannot be projected into canonical Run
    state without inventing scope, so construction fails closed while any are
    present instead of silently starting an apparently empty replacement table.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._path = str(db_path)
        self._lock = asyncio.Lock()
        with self._connect() as conn:
            _reject_unmigrated_legacy_rows(conn)
            conn.executescript(_SCHEMA_SQL)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _to_row(record: DurableRunRecord) -> dict[str, Any]:
        return {
            "run_id": record.run_id,
            "status": record.run.status.value,
            "active_node_id": record.active_node_id,
            "project_id": record.run.project_id,
            "created_at": record.run.created_at.isoformat(),
            "resume_at": record.resume_at.isoformat() if record.resume_at else None,
            "version": record.version,
            "record_json": record.model_dump_json(),
        }

    @staticmethod
    def _from_row(row: sqlite3.Row) -> DurableRunRecord:
        return DurableRunRecord.model_validate_json(row["record_json"])

    async def create(self, record: DurableRunRecord) -> DurableRunRecord:
        async with self._lock:
            try:
                return await asyncio.to_thread(_create_sync, self, record)
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"run_id collision: {record.run_id!r}") from exc

    async def get(self, run_id: str) -> DurableRunRecord | None:
        return await asyncio.to_thread(_get_sync, self, run_id)

    async def update(self, record: DurableRunRecord) -> DurableRunRecord:
        async with self._lock:
            return await asyncio.to_thread(_update_sync, self, record)

    async def list_by_status(
        self,
        status: RunStatus,
        *,
        limit: int = 100,
        project_id: str | None = None,
    ) -> list[DurableRunRecord]:
        return await asyncio.to_thread(
            _list_by_status_sync,
            self,
            status,
            limit,
            project_id,
        )

    async def list_for_project(self, project_id: str, *, limit: int = 25) -> list[DurableRunRecord]:
        return await asyncio.to_thread(
            _list_for_project_sync,
            self,
            project_id,
            limit,
        )

    async def submit_hitl_answer(
        self,
        run_id: str,
        node_id: str,
        answer: dict[str, Any],
    ) -> DurableRunRecord:
        async with self._lock:
            current = await asyncio.to_thread(_get_sync, self, run_id)
            if current is None:
                raise KeyError(f"no such run: {run_id!r}")
            return await asyncio.to_thread(
                _update_sync,
                self,
                _answer_record(current, node_id, answer),
            )


def _create_sync(
    store: SqliteDurableRunStore,
    record: DurableRunRecord,
) -> DurableRunRecord:
    row = store._to_row(record)
    with store._connect() as conn:
        conn.execute(
            """
            INSERT INTO durable_graph_runs(
                run_id, status, active_node_id, project_id, created_at,
                resume_at, version, record_json
            ) VALUES (
                :run_id, :status, :active_node_id, :project_id, :created_at,
                :resume_at, :version, :record_json
            )
            """,
            row,
        )
        conn.commit()
    return _clone(record)


def _get_sync(
    store: SqliteDurableRunStore,
    run_id: str,
) -> DurableRunRecord | None:
    with store._connect() as conn:
        row = conn.execute(
            "SELECT * FROM durable_graph_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    return store._from_row(row) if row else None


def _update_sync(
    store: SqliteDurableRunStore,
    record: DurableRunRecord,
) -> DurableRunRecord:
    row = store._to_row(record)
    with store._connect() as conn:
        cursor = conn.execute(
            """
            UPDATE durable_graph_runs
               SET status = :status,
                   active_node_id = :active_node_id,
                   project_id = :project_id,
                   created_at = :created_at,
                   resume_at = :resume_at,
                   version = :version,
                   record_json = :record_json
             WHERE run_id = :run_id
               AND version < :version
            """,
            row,
        )
        if cursor.rowcount == 0:
            existing = conn.execute(
                "SELECT version FROM durable_graph_runs WHERE run_id = ?",
                (record.run_id,),
            ).fetchone()
            conn.commit()
            if existing is None:
                raise KeyError(f"no such run: {record.run_id!r}")
            raise ValueError(
                f"version regression: stored={existing['version']} incoming={record.version}"
            )
        conn.commit()
    return _clone(record)


def _list_by_status_sync(
    store: SqliteDurableRunStore,
    status: RunStatus,
    limit: int,
    project_id: str | None,
) -> list[DurableRunRecord]:
    query = "SELECT * FROM durable_graph_runs WHERE status = ?"
    params: list[Any] = [status.value]
    if project_id is not None:
        query += " AND project_id = ?"
        params.append(project_id)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with store._connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [store._from_row(row) for row in rows]


def _list_for_project_sync(
    store: SqliteDurableRunStore,
    project_id: str,
    limit: int,
) -> list[DurableRunRecord]:
    with store._connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM durable_graph_runs
             WHERE project_id = ?
             ORDER BY created_at DESC
             LIMIT ?
            """,
            (project_id, limit),
        ).fetchall()
    return [store._from_row(row) for row in rows]


__all__ = ["InMemoryDurableRunStore", "SqliteDurableRunStore"]
