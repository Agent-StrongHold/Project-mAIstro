"""Stores for canonical durable graph checkpoints."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from maistro.graph.execution_state import GraphExecutionState, thaw_json_value
from maistro.runs.lifecycle import settle_open_node_run, transition_node_run, transition_run
from maistro.runs.model import TERMINAL_RUN_STATUSES, RunStatus

from .hitl import (
    HitlDeadlineElapsed,
    HitlDeadlinePending,
    hitl_deadline,
    hitl_pause,
    settlement_time,
)
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


def answer_record(
    record: DurableRunRecord,
    node_id: str,
    answer: dict[str, Any],
    *,
    at: datetime | None = None,
) -> DurableRunRecord:
    if record.run.status is not RunStatus.PAUSED:
        raise ValueError(f"run {record.run_id!r} not paused on HITL (status={record.run.status})")
    if node_id not in record.graph_state.active_node_ids:
        raise ValueError(
            f"run {record.run_id!r} waiting on frontier "
            f"{record.graph_state.active_node_ids!r}, not {node_id!r}"
        )

    paused_index = _paused_node_run_index(record, node_id)
    moment = settlement_time(at)
    deadline = hitl_deadline(record, node_id, require_pause=False)
    if deadline is not None and deadline <= moment:
        raise HitlDeadlineElapsed(
            f"run {record.run_id!r} HITL deadline elapsed for node {node_id!r} "
            f"at {deadline.isoformat()}"
        )
    # The pause payload the *node* wrote is the only server-side fact in a
    # resume, and `_pause_metadata_after_answer` is about to delete it. Stamp it
    # onto the answer first, after the caller's keys so a submitted `_pause`
    # cannot displace it.
    #
    # `agent.delegate_remote` is why this exists: it paused carrying the child
    # Run's id, and on resume could only read the answer, so the canonical
    # execution identity either vanished or was whatever the responder claimed.
    # A node that needs to know which execution it paused on must not have to
    # ask the party it was waiting for.
    pauses_before = record.graph_state.metadata.get("pauses", {})
    own_pause = pauses_before.get(node_id) if isinstance(pauses_before, Mapping) else None
    answered: dict[str, Any] = {**answer, "answered_at": moment.isoformat()}
    if isinstance(own_pause, Mapping):
        answered["_pause"] = dict(own_pause)
    metadata = dict(record.graph_state.metadata)
    answers = dict(record.hitl_answers)
    answers[node_id] = answered
    metadata["hitl_answers"] = answers
    metadata = _pause_metadata_after_answer(record, metadata, node_id)

    node_runs = list(record.node_runs)
    node_runs[paused_index] = transition_node_run(
        node_runs[paused_index],
        RunStatus.QUEUED,
        at=moment,
    )
    remaining_paused = any(node_run.status is RunStatus.PAUSED for node_run in node_runs)
    run = (
        record.run if remaining_paused else transition_run(record.run, RunStatus.QUEUED, at=moment)
    )
    graph_state = _replace_state(record.graph_state, metadata=metadata)
    return _replace_record(
        record,
        run=run,
        graph_state=graph_state,
        node_runs=tuple(node_runs),
        resume_at=record.resume_at if remaining_paused else None,
        version=record.version + 1,
    )


def settle_hitl_record(
    record: DurableRunRecord,
    node_id: str,
    outcome: Literal["timed_out", "cancelled"],
    *,
    at: datetime | None = None,
) -> DurableRunRecord:
    """Apply the one canonical terminal decision for a durable human pause."""
    if record.run.status is not RunStatus.PAUSED:
        raise ValueError(f"run {record.run_id!r} not paused on HITL (status={record.run.status})")
    if node_id not in record.graph_state.active_node_ids:
        raise ValueError(
            f"run {record.run_id!r} waiting on frontier "
            f"{record.graph_state.active_node_ids!r}, not {node_id!r}"
        )

    paused_index = _paused_node_run_index(record, node_id)
    pause = hitl_pause(record, node_id)
    moment = settlement_time(at)
    deadline = hitl_deadline(record, node_id)
    if outcome == "timed_out" and (deadline is None or deadline > moment):
        detail = (
            "has no deadline" if deadline is None else f"is pending until {deadline.isoformat()}"
        )
        raise HitlDeadlinePending(
            f"run {record.run_id!r} HITL deadline for node {node_id!r} {detail}"
        )

    # Once the durable deadline is reached, cancellation cannot outrun timeout
    # merely because the expiry tick has not observed the record yet.
    settled_outcome: Literal["timed_out", "cancelled"] = outcome
    if deadline is not None and deadline <= moment:
        settled_outcome = "timed_out"
    target = RunStatus.TIMED_OUT if settled_outcome == "timed_out" else RunStatus.CANCELLED

    if target is RunStatus.TIMED_OUT:
        assert deadline is not None
        reason = f"human input for node {node_id!r} timed out at {deadline.isoformat()}"
    else:
        reason = f"human input for node {node_id!r} was cancelled"

    node_runs = list(record.node_runs)
    node_runs[paused_index] = transition_node_run(
        node_runs[paused_index],
        target,
        at=moment,
        error=reason,
    )
    for index, node_run in enumerate(node_runs):
        if index == paused_index or node_run.status in TERMINAL_RUN_STATUSES:
            continue
        node_runs[index] = settle_open_node_run(node_run, target, at=moment)

    metadata = dict(record.graph_state.metadata)
    settlements_raw = metadata.get("hitl_settlements", {})
    settlements = dict(settlements_raw) if isinstance(settlements_raw, Mapping) else {}
    settlements[node_id] = {
        "outcome": settled_outcome,
        "decided_at": moment.isoformat(),
        "node_id": node_id,
        "node_run_id": node_runs[paused_index].node_run_id,
        "pause": pause,
    }
    metadata["hitl_settlements"] = settlements
    metadata.pop("pauses", None)
    metadata.pop("pause", None)
    metadata.pop("deferred_frontier", None)
    metadata.pop("deferred_fanins", None)

    graph_state = _replace_state(
        record.graph_state,
        active_node_ids=(),
        metadata=metadata,
    )
    run = transition_run(record.run, target, at=moment, error=reason)
    return _replace_record(
        record,
        run=run,
        graph_state=graph_state,
        node_runs=tuple(node_runs),
        resume_at=None,
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
        *,
        at: datetime | None = None,
    ) -> DurableRunRecord:
        async with self._lock:
            record = self._rows.get(run_id)
            if record is None:
                raise KeyError(f"no such run: {run_id!r}")
            updated = answer_record(record, node_id, answer, at=at)
            self._rows[run_id] = updated
            return _clone(updated)

    async def timeout_hitl(
        self,
        run_id: str,
        node_id: str,
        *,
        at: datetime | None = None,
    ) -> DurableRunRecord:
        async with self._lock:
            record = self._rows.get(run_id)
            if record is None:
                raise KeyError(f"no such run: {run_id!r}")
            updated = settle_hitl_record(record, node_id, "timed_out", at=at)
            self._rows[run_id] = updated
            return _clone(updated)

    async def cancel_hitl(
        self,
        run_id: str,
        node_id: str,
        *,
        at: datetime | None = None,
    ) -> DurableRunRecord:
        async with self._lock:
            record = self._rows.get(run_id)
            if record is None:
                raise KeyError(f"no such run: {run_id!r}")
            updated = settle_hitl_record(record, node_id, "cancelled", at=at)
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
        *,
        at: datetime | None = None,
    ) -> DurableRunRecord:
        async with self._lock:
            return await asyncio.to_thread(
                _mutate_hitl_sync,
                self,
                run_id,
                lambda current: answer_record(current, node_id, answer, at=at),
            )

    async def timeout_hitl(
        self,
        run_id: str,
        node_id: str,
        *,
        at: datetime | None = None,
    ) -> DurableRunRecord:
        async with self._lock:
            return await asyncio.to_thread(
                _mutate_hitl_sync,
                self,
                run_id,
                lambda current: settle_hitl_record(current, node_id, "timed_out", at=at),
            )

    async def cancel_hitl(
        self,
        run_id: str,
        node_id: str,
        *,
        at: datetime | None = None,
    ) -> DurableRunRecord:
        async with self._lock:
            return await asyncio.to_thread(
                _mutate_hitl_sync,
                self,
                run_id,
                lambda current: settle_hitl_record(current, node_id, "cancelled", at=at),
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


def _mutate_hitl_sync(
    store: SqliteDurableRunStore,
    run_id: str,
    mutate: Callable[[DurableRunRecord], DurableRunRecord],
) -> DurableRunRecord:
    """Serialize one HITL decision and its optimistic write in one transaction."""
    with store._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        persisted = conn.execute(
            "SELECT * FROM durable_graph_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if persisted is None:
            raise KeyError(f"no such run: {run_id!r}")

        current = store._from_row(persisted)
        updated = mutate(current)
        row = {**store._to_row(updated), "expected_version": current.version}
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
               AND version = :expected_version
            """,
            row,
        )
        if cursor.rowcount != 1:
            raise ValueError(f"concurrent HITL decision for run {run_id!r}")
    return _clone(updated)


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
