"""SQLite persistence for the canonical Run -> NodeRun -> Attempt spine."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING, Any

from maistro.graph.definitions import Graph
from maistro.projects.scope_store import ProjectScopeStore
from maistro.runs.lifecycle import transition_attempt, transition_node_run, transition_run
from maistro.runs.model import (
    TERMINAL_RUN_STATUSES,
    AcceptedNodeOutcome,
    Attempt,
    AttemptStatus,
    ExecutionLease,
    GraphSnapshot,
    NodeRun,
    Run,
    RunStatus,
)
from maistro.runs.store import (
    ActiveAttemptExists,
    AttemptNotFound,
    NodeRunNotFound,
    RunIntegrityError,
    RunNotFound,
    StaleExecutionFence,
    validate_accepted_outcome_against_attempt,
    validate_child_scope,
)

if TYPE_CHECKING:
    import aiosqlite

_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS canonical_runs (
    run_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    parent_run_id TEXT,
    parent_node_run_id TEXT,
    status TEXT NOT NULL,
    payload TEXT NOT NULL,
    FOREIGN KEY (parent_run_id) REFERENCES canonical_runs(run_id),
    FOREIGN KEY (parent_node_run_id) REFERENCES canonical_node_runs(node_run_id)
);

CREATE INDEX IF NOT EXISTS idx_canonical_runs_workspace_project
    ON canonical_runs(workspace_id, project_id);
CREATE INDEX IF NOT EXISTS idx_canonical_runs_parent
    ON canonical_runs(parent_run_id);

CREATE TABLE IF NOT EXISTS canonical_node_runs (
    node_run_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    status TEXT NOT NULL,
    payload TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES canonical_runs(run_id) ON DELETE RESTRICT,
    UNIQUE (run_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_canonical_node_runs_run
    ON canonical_node_runs(run_id, ordinal);

CREATE TABLE IF NOT EXISTS canonical_attempts (
    attempt_id TEXT PRIMARY KEY,
    node_run_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    status TEXT NOT NULL,
    payload TEXT NOT NULL,
    FOREIGN KEY (node_run_id) REFERENCES canonical_node_runs(node_run_id) ON DELETE RESTRICT,
    UNIQUE (node_run_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_canonical_attempts_node_run
    ON canonical_attempts(node_run_id, ordinal);
CREATE UNIQUE INDEX IF NOT EXISTS idx_canonical_attempts_one_active
    ON canonical_attempts(node_run_id)
    WHERE status IN ('created', 'running');
"""


class SqliteRunStore:
    """Durable reference store for canonical execution identity and lifecycle."""

    def __init__(
        self,
        conn: aiosqlite.Connection,
        *,
        project_store: ProjectScopeStore,
    ) -> None:
        self._conn = conn
        self._project_store = project_store
        # One connection, and now more than one caller: the task runner drives
        # four workers against this store (#143), and `create_attempt` opens an
        # explicit BEGIN IMMEDIATE. Two of those interleaving on one aiosqlite
        # connection raises "cannot start a transaction within a transaction",
        # and every other mutation here is a read-then-write whose two halves
        # must not be split by another caller's commit. The connection is
        # serial anyway — one thread — so serializing the *operations* costs
        # nothing and is what makes those pairs atomic rather than merely
        # usually atomic.
        #
        # Taken inside each mutating method rather than by a decorator: a
        # decorator's declared return type is `Coroutine`, which pyright does
        # not accept where the `RunStore` protocol asks for the `CoroutineType`
        # a plain `async def` produces — so the store silently stopped
        # satisfying its own protocol.
        self._write_lock = asyncio.Lock()

    async def ensure_schema(self) -> None:
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()

    async def create_run(
        self,
        graph: Graph,
        *,
        parent_run_id: str | None = None,
        parent_node_run_id: str | None = None,
        allow_cross_project: bool = False,
        persona_id: str | None = None,
        actor_principal_id: str | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> Run:
        async with self._write_lock:
            await self._validate_graph_scope(graph)
            if parent_node_run_id is not None and parent_run_id is None:
                raise RunIntegrityError("parent_node_run_id requires parent_run_id")
            if parent_run_id is not None:
                parent = await self._require_run(parent_run_id)
                validate_child_scope(
                    parent,
                    workspace_id=graph.workspace_id,
                    project_id=graph.project_id,
                    allow_cross_project=allow_cross_project,
                )
                if parent_node_run_id is not None:
                    parent_node_run = await self._require_node_run(parent_node_run_id)
                    if parent_node_run.run_id != parent_run_id:
                        raise RunIntegrityError(
                            "parent_node_run_id does not belong to parent_run_id",
                        )
            run = Run(
                workspace_id=graph.workspace_id,
                project_id=graph.project_id,
                graph=GraphSnapshot.from_graph(graph.model_copy(deep=True)),
                parent_run_id=parent_run_id,
                parent_node_run_id=parent_node_run_id,
                persona_id=persona_id,
                actor_principal_id=actor_principal_id,
                provenance=dict(provenance or {}),
            )
            await self._conn.execute(
                """INSERT INTO canonical_runs
                   (run_id, workspace_id, project_id, parent_run_id,
                    parent_node_run_id, status, payload)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    run.run_id,
                    run.workspace_id,
                    run.project_id,
                    run.parent_run_id,
                    run.parent_node_run_id,
                    run.status.value,
                    run.model_dump_json(),
                ),
            )
            await self._conn.commit()
            return run

    async def get_run(self, run_id: str) -> Run | None:
        row = await self._fetchone(
            "SELECT payload FROM canonical_runs WHERE run_id = ?",
            (run_id,),
        )
        return Run.model_validate_json(row[0]) if row is not None else None

    async def transition_run(
        self,
        run_id: str,
        target: RunStatus,
        *,
        at: datetime | None = None,
        result: object | None = None,
        error: str | None = None,
    ) -> Run:
        async with self._write_lock:
            run = await self._require_run(run_id)
            updated = transition_run(run, target, at=at, result=result, error=error)
            await self._update_payload(
                "canonical_runs", "run_id", run_id, updated.status.value, updated.model_dump_json()
            )
            return updated

    async def create_node_run(self, run_id: str, *, node_id: str) -> NodeRun:
        async with self._write_lock:
            run = await self._require_run(run_id)
            if run.status in TERMINAL_RUN_STATUSES:
                raise RunIntegrityError("cannot create NodeRun under a terminal Run")
            graph = run.graph.materialize()
            if not any(node.node_id == node_id for node in graph.nodes):
                raise RunIntegrityError(
                    f"node_id {node_id!r} is not present in the Run Graph snapshot",
                )
            row = await self._fetchone(
                "SELECT COALESCE(MAX(ordinal), 0) FROM canonical_node_runs WHERE run_id = ?",
                (run_id,),
            )
            ordinal = int(row[0]) + 1 if row is not None else 1
            node_run = NodeRun(run_id=run_id, node_id=node_id, ordinal=ordinal)
            await self._conn.execute(
                """INSERT INTO canonical_node_runs
                   (node_run_id, run_id, node_id, ordinal, status, payload)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    node_run.node_run_id,
                    node_run.run_id,
                    node_run.node_id,
                    node_run.ordinal,
                    node_run.status.value,
                    node_run.model_dump_json(),
                ),
            )
            await self._conn.commit()
            return node_run

    async def get_node_run(self, node_run_id: str) -> NodeRun | None:
        row = await self._fetchone(
            "SELECT payload FROM canonical_node_runs WHERE node_run_id = ?",
            (node_run_id,),
        )
        return NodeRun.model_validate_json(row[0]) if row is not None else None

    async def list_node_runs(self, run_id: str) -> list[NodeRun]:
        await self._require_run(run_id)
        cursor = await self._conn.execute(
            "SELECT payload FROM canonical_node_runs WHERE run_id = ? ORDER BY ordinal",
            (run_id,),
        )
        rows = await cursor.fetchall()
        return [NodeRun.model_validate_json(row[0]) for row in rows]

    async def transition_node_run(
        self,
        node_run_id: str,
        target: RunStatus,
        *,
        at: datetime | None = None,
        result: object | None = None,
        error: str | None = None,
        accepted_outcome: AcceptedNodeOutcome | None = None,
    ) -> NodeRun:
        async with self._write_lock:
            node_run = await self._require_node_run(node_run_id)
            if accepted_outcome is not None:
                if accepted_outcome.node_run_id != node_run_id:
                    raise RunIntegrityError("accepted outcome belongs to a different NodeRun")
                attempt = await self._require_attempt(accepted_outcome.attempt_result.attempt_id)
                validate_accepted_outcome_against_attempt(accepted_outcome, attempt)
            updated = transition_node_run(
                node_run,
                target,
                at=at,
                result=result,
                error=error,
                accepted_outcome=accepted_outcome,
            )
            await self._update_payload(
                "canonical_node_runs",
                "node_run_id",
                node_run_id,
                updated.status.value,
                updated.model_dump_json(),
            )
            return updated

    async def create_attempt(
        self,
        node_run_id: str,
        *,
        runtime_id: str = "python",
        executor_id: str = "",
        deadline_at: datetime | None = None,
        resume_checkpoint_id: str | None = None,
        lease_holder: str | None = None,
    ) -> Attempt:
        async with self._write_lock:
            node_run = await self._require_node_run(node_run_id)
            if node_run.status in TERMINAL_RUN_STATUSES:
                raise RunIntegrityError("cannot create Attempt under a terminal NodeRun")
            await self._conn.execute("BEGIN IMMEDIATE")
            try:
                active = await self._fetchone(
                    """SELECT attempt_id FROM canonical_attempts
                       WHERE node_run_id = ? AND status IN ('created', 'running')
                       LIMIT 1""",
                    (node_run_id,),
                )
                if active is not None:
                    raise ActiveAttemptExists(
                        f"NodeRun {node_run_id!r} already has an active Attempt",
                    )
                row = await self._fetchone(
                    """SELECT COALESCE(MAX(ordinal), 0) FROM canonical_attempts
                       WHERE node_run_id = ?""",
                    (node_run_id,),
                )
                ordinal = int(row[0]) + 1 if row is not None else 1
                attempt = Attempt(
                    node_run_id=node_run_id,
                    ordinal=ordinal,
                    runtime_id=runtime_id,
                    executor_id=executor_id,
                    deadline_at=deadline_at,
                    resume_checkpoint_id=resume_checkpoint_id,
                )
                if lease_holder is not None:
                    lease = ExecutionLease(
                        node_run_id=node_run_id,
                        attempt_id=attempt.attempt_id,
                        lease_epoch=ordinal,
                        holder=lease_holder,
                    )
                    attempt = Attempt.model_validate(
                        {**attempt.model_dump(mode="python"), "execution_lease": lease}
                    )
                await self._conn.execute(
                    """INSERT INTO canonical_attempts
                       (attempt_id, node_run_id, ordinal, status, payload)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        attempt.attempt_id,
                        attempt.node_run_id,
                        attempt.ordinal,
                        attempt.status.value,
                        attempt.model_dump_json(),
                    ),
                )
                await self._conn.commit()
                return attempt
            except ActiveAttemptExists:
                await self._conn.rollback()
                raise
            except sqlite3.IntegrityError as exc:
                await self._conn.rollback()
                active = await self._fetchone(
                    """SELECT attempt_id FROM canonical_attempts
                       WHERE node_run_id = ? AND status IN ('created', 'running')
                       LIMIT 1""",
                    (node_run_id,),
                )
                if active is not None:
                    raise ActiveAttemptExists(
                        f"NodeRun {node_run_id!r} already has an active Attempt",
                    ) from exc
                raise RunIntegrityError("Attempt persistence integrity failure") from exc
            except Exception:
                await self._conn.rollback()
                raise

    async def get_attempt(self, attempt_id: str) -> Attempt | None:
        row = await self._fetchone(
            "SELECT payload FROM canonical_attempts WHERE attempt_id = ?",
            (attempt_id,),
        )
        return Attempt.model_validate_json(row[0]) if row is not None else None

    async def list_attempts(self, node_run_id: str) -> list[Attempt]:
        await self._require_node_run(node_run_id)
        cursor = await self._conn.execute(
            """SELECT payload FROM canonical_attempts
               WHERE node_run_id = ? ORDER BY ordinal""",
            (node_run_id,),
        )
        rows = await cursor.fetchall()
        return [Attempt.model_validate_json(row[0]) for row in rows]

    async def transition_attempt(
        self,
        attempt_id: str,
        target: AttemptStatus,
        *,
        at: datetime | None = None,
        result: object | None = None,
        error: str | None = None,
        metrics: dict[str, object] | None = None,
        fencing_token: str | None = None,
    ) -> Attempt:
        async with self._write_lock:
            attempt = await self._require_attempt(attempt_id)
            self._validate_fence(attempt, fencing_token)
            updated = transition_attempt(
                attempt,
                target,
                at=at,
                result=result,
                error=error,
                metrics=metrics,
            )
            await self._update_payload(
                "canonical_attempts",
                "attempt_id",
                attempt_id,
                updated.status.value,
                updated.model_dump_json(),
            )
            return updated

    @staticmethod
    def _validate_fence(attempt: Attempt, fencing_token: str | None) -> None:
        lease = attempt.execution_lease
        if lease is not None and fencing_token != lease.fencing_token:
            raise StaleExecutionFence(
                f"Attempt {attempt.attempt_id!r} update rejected by execution fence"
            )

    async def _validate_graph_scope(self, graph: Graph) -> None:
        project = await self._project_store.get(graph.project_id)
        if project is None:
            raise RunIntegrityError(
                f"Graph Project {graph.project_id!r} does not exist in canonical Project scope",
            )
        if project.workspace_id != graph.workspace_id:
            raise RunIntegrityError("Graph Project does not belong to the Graph Workspace")

    async def _require_run(self, run_id: str) -> Run:
        run = await self.get_run(run_id)
        if run is None:
            raise RunNotFound(run_id)
        return run

    async def _require_node_run(self, node_run_id: str) -> NodeRun:
        node_run = await self.get_node_run(node_run_id)
        if node_run is None:
            raise NodeRunNotFound(node_run_id)
        return node_run

    async def _require_attempt(self, attempt_id: str) -> Attempt:
        attempt = await self.get_attempt(attempt_id)
        if attempt is None:
            raise AttemptNotFound(attempt_id)
        return attempt

    async def _fetchone(self, query: str, params: tuple[object, ...]) -> Any | None:
        cursor = await self._conn.execute(query, params)
        return await cursor.fetchone()

    async def _update_payload(
        self,
        table: str,
        identity_column: str,
        identity: str,
        status: str,
        payload: str,
    ) -> None:
        allowed = {
            ("canonical_runs", "run_id"),
            ("canonical_node_runs", "node_run_id"),
            ("canonical_attempts", "attempt_id"),
        }
        if (table, identity_column) not in allowed:
            raise ValueError("unsupported canonical execution table")
        await self._conn.execute(
            f"UPDATE {table} SET status = ?, payload = ? WHERE {identity_column} = ?",  # nosec B608
            (status, payload, identity),
        )
        await self._conn.commit()


__all__ = ["SqliteRunStore"]
