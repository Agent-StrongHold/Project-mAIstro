"""SQLite persistence for the canonical Run -> NodeRun -> Attempt spine."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime
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
    DEFAULT_PURGE_BATCH,
    ActiveAttemptExists,
    AttemptNotFound,
    NodeRunNotFound,
    RunIntegrityError,
    RunNotFound,
    StaleExecutionFence,
    is_purgeable,
    validate_accepted_outcome_against_attempt,
)

if TYPE_CHECKING:
    import aiosqlite

#: Terminal Run statuses as the database spells them. Derived from the model
#: rather than written out, so a new terminal status cannot silently become one
#: retention refuses to sweep.
_TERMINAL_STATUS_VALUES = sorted(status.value for status in TERMINAL_RUN_STATUSES)

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
        # Every mutation serialises on this. The connection is one serial
        # resource — aiosqlite drives a single thread — so the lock costs
        # nothing real, and without it concurrent coroutines sharing this store
        # broke in two ways the spine conformance suite (#132) caught:
        #
        #   - `create_attempt`'s `BEGIN IMMEDIATE` is a cross-*connection* lock,
        #     not a cross-coroutine one. Two coroutines on this connection both
        #     issued it, and the loser got `OperationalError: cannot start a
        #     transaction within a transaction` — a raw driver error where the
        #     caller expects `ActiveAttemptExists`, on the path the whole retry
        #     model rests on.
        #   - `create_node_run` had no transaction at all, so two callers read
        #     the same `MAX(ordinal)` and the loser got a raw `IntegrityError`.
        #
        # The graph executor and the task runner both drive this store from
        # concurrent coroutines, so "one caller at a time" was never true.
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
        retention_expires_at: datetime | None = None,
    ) -> Run:
        await self._validate_graph_scope(graph)
        if parent_node_run_id is not None and parent_run_id is None:
            raise RunIntegrityError("parent_node_run_id requires parent_run_id")
        if parent_run_id is not None:
            parent = await self._require_run(parent_run_id)
            if parent.workspace_id != graph.workspace_id:
                raise RunIntegrityError("child Run cannot cross Workspace boundaries")
            if parent.project_id != graph.project_id and not allow_cross_project:
                raise RunIntegrityError(
                    "child Run cannot implicitly cross Project boundaries; "
                    "caller must authorize and request the destination Project",
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
            retention_expires_at=retention_expires_at,
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

    async def _purge_candidates(self, limit: int) -> list[tuple[str, Run]]:
        """Terminal Runs carrying a deadline and descended from by nobody.

        Ordered by deadline, so the caller can stop at the first unexpired one
        rather than parsing the whole batch. `json_extract` is only used to
        *narrow* and *order*; the comparison against the cutoff happens in
        Python against a parsed datetime, because comparing ISO-8601 strings
        lexically is only correct while every one of them carries the same UTC
        offset — true today, and not something to make load-bearing.
        """
        cursor = await self._conn.execute(
            f"""SELECT run_id, payload FROM canonical_runs r
                WHERE r.status IN ({",".join("?" * len(_TERMINAL_STATUS_VALUES))})
                  AND json_extract(r.payload, '$.retention_expires_at') IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM canonical_runs c WHERE c.parent_run_id = r.run_id
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM canonical_node_runs n
                      JOIN canonical_runs c2 ON c2.parent_node_run_id = n.node_run_id
                      WHERE n.run_id = r.run_id
                  )
                ORDER BY json_extract(r.payload, '$.retention_expires_at')
                LIMIT ?""",
            (*_TERMINAL_STATUS_VALUES, limit),
        )
        return [(row[0], Run.model_validate_json(row[1])) for row in await cursor.fetchall()]

    async def purge_expired_runs(
        self,
        *,
        now: datetime | None = None,
        limit: int = DEFAULT_PURGE_BATCH,
    ) -> int:
        """Delete up to ``limit`` expired terminal Runs. Returns how many went.

        Deletes in the order the foreign keys require — Attempts, NodeRuns,
        Runs — under the same write lock every other mutation takes, so a
        concurrent transition cannot land on a Run this sweep is removing.
        """
        if limit <= 0:
            raise ValueError("limit must be positive")
        cutoff = now if now is not None else datetime.now(UTC)
        async with self._write_lock:
            doomed = []
            for run_id, run in await self._purge_candidates(limit):
                if not is_purgeable(run, cutoff):
                    break
                doomed.append(run_id)
            if not doomed:
                return 0
            placeholders = ",".join("?" * len(doomed))
            await self._conn.execute(
                f"""DELETE FROM canonical_attempts WHERE node_run_id IN (
                        SELECT node_run_id FROM canonical_node_runs
                        WHERE run_id IN ({placeholders})
                    )""",
                tuple(doomed),
            )
            await self._conn.execute(
                f"DELETE FROM canonical_node_runs WHERE run_id IN ({placeholders})",
                tuple(doomed),
            )
            await self._conn.execute(
                f"DELETE FROM canonical_runs WHERE run_id IN ({placeholders})",
                tuple(doomed),
            )
            await self._conn.commit()
        return len(doomed)

    async def transition_run(
        self,
        run_id: str,
        target: RunStatus,
        *,
        at: datetime | None = None,
        result: object | None = None,
        error: str | None = None,
    ) -> Run:
        # Read and write under one lock. Splitting them lets a second coroutine
        # read the same prior state and write over this one's transition.
        async with self._write_lock:
            run = await self._require_run(run_id)
            updated = transition_run(run, target, at=at, result=result, error=error)
            await self._update_payload(
                "canonical_runs", "run_id", run_id, updated.status.value, updated.model_dump_json()
            )
        return updated

    async def create_node_run(self, run_id: str, *, node_id: str) -> NodeRun:
        async with self._write_lock:
            return await self._create_node_run(run_id, node_id=node_id)

    async def _create_node_run(self, run_id: str, *, node_id: str) -> NodeRun:
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
            return await self._create_attempt(
                node_run_id,
                runtime_id=runtime_id,
                executor_id=executor_id,
                deadline_at=deadline_at,
                resume_checkpoint_id=resume_checkpoint_id,
                lease_holder=lease_holder,
            )

    async def _create_attempt(
        self,
        node_run_id: str,
        *,
        runtime_id: str = "python",
        executor_id: str = "",
        deadline_at: datetime | None = None,
        resume_checkpoint_id: str | None = None,
        lease_holder: str | None = None,
    ) -> Attempt:
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
            # Fence checked inside the lock: outside it, a stale worker could
            # pass a check that was true when it ran and false when it wrote.
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
