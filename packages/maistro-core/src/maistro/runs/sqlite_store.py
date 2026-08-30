"""SQLite persistence for the canonical Run -> NodeRun -> Attempt spine."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from maistro.graph.definitions import Graph
from maistro.projects.scope_store import ProjectScopeStore
from maistro.runs.evidence_json import json_of, model_of_json
from maistro.runs.lifecycle import (
    check_completion_is_earned,
    lease_is_expired,
    reclaim_attempt,
    renew_attempt_lease,
    renewed_lease,
    settle_open_node_run,
    transition_attempt,
    transition_node_run,
    transition_run,
)
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
from maistro.runs.sources import occurrence_key
from maistro.runs.store import (
    DEFAULT_PURGE_BATCH,
    DEFAULT_RECLAIM_BATCH,
    ActiveAttemptExists,
    AttemptNotFound,
    DuplicateOccurrence,
    NodeRunNotFound,
    RunIntegrityError,
    RunNotFound,
    StaleExecutionFence,
    admit_in_state,
    is_purgeable,
    validate_accepted_outcome_against_attempt,
    validate_child_scope,
)

if TYPE_CHECKING:
    import aiosqlite

_TERMINAL_STATUS_VALUES = sorted(status.value for status in TERMINAL_RUN_STATUSES)


def _placeholders(count: int) -> str:
    """`count` SQL parameter marks, comma-separated.

    The one thing this repo interpolates into SQL, and the reason bandit's B608
    findings on the statements below are marked rather than fixed: the returned
    text is `?,?,?`, derived from a length and never from a value. Every datum
    still travels in the parameter tuple, so there is no vector to close — the
    alternative bandit would prefer (a fixed number of marks) cannot express
    `IN` over a variable-length list at all.

    `sqlite_learnings.py` marks the identical pattern the same way.
    """
    return ",".join("?" * count)


#: Held as templates rather than built inline so the interpolation sits on one
#: line that can carry its `# nosec`, and so the SQL itself is readable next to
#: the schema above rather than buried in a call.
_PURGE_CANDIDATES_SQL = """SELECT run_id, payload FROM canonical_runs r
    WHERE r.status IN ({statuses})
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
    LIMIT ?"""

_DELETE_ATTEMPTS_SQL = """DELETE FROM canonical_attempts WHERE node_run_id IN (
        SELECT node_run_id FROM canonical_node_runs WHERE run_id IN ({runs})
    )"""

_DELETE_NODE_RUNS_SQL = "DELETE FROM canonical_node_runs WHERE run_id IN ({runs})"

_DELETE_RUNS_SQL = "DELETE FROM canonical_runs WHERE run_id IN ({runs})"

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

-- One Run per schedule firing (#220). The unique index *is* the claim: two
-- tickers evaluating the same due window both reach the insert, and the
-- database refuses the second rather than a convention in the caller.
--
-- Expression index over the payload rather than columns, because these two
-- fields belong to the schedule admitter and every other admitter would carry
-- them as NULL. `json_extract` is deterministic, which is what SQLite requires
-- of an indexed expression.
--
-- Partial on `schedule_id IS NOT NULL`: only scheduled Runs claim an
-- occurrence, and without the predicate every task and chat Run would collide
-- on `(NULL, NULL)`.
CREATE UNIQUE INDEX IF NOT EXISTS idx_canonical_runs_occurrence
    ON canonical_runs(
        json_extract(payload, '$.provenance.schedule_id'),
        json_extract(payload, '$.provenance.scheduled_for')
    )
    WHERE json_extract(payload, '$.provenance.schedule_id') IS NOT NULL
      AND json_extract(payload, '$.provenance.scheduled_for') IS NOT NULL;

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


_PAYLOAD_TABLES = frozenset(
    {
        ("canonical_runs", "run_id"),
        ("canonical_node_runs", "node_run_id"),
        ("canonical_attempts", "attempt_id"),
    }
)


def _checked_table(table: str, identity_column: str) -> tuple[str, str]:
    """Refuse any table/column pair not on the canonical list.

    The UPDATE below interpolates both, so this is what keeps that from being
    an injection point rather than a formatting convenience.
    """
    if (table, identity_column) not in _PAYLOAD_TABLES:
        raise ValueError("unsupported canonical execution table")
    return table, identity_column


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
        # Staged payload updates, applied and committed together by
        # `_flush`. Only ever non-empty inside one `_write_lock` holder.
        self._pending: list[tuple[tuple[str, str], str, str, str]] = []

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
        initial_status: RunStatus = RunStatus.CREATED,
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
                retention_expires_at=retention_expires_at,
            )
            # Before the insert, not after it: one commit, so there is no window
            # in which a process death leaves a CREATED Run whose provenance
            # names a receipt that was already queued.
            run = admit_in_state(run, initial_status)
            try:
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
                        json_of(run),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                occurrence = occurrence_key(run.provenance)
                if occurrence is None or "idx_canonical_runs_occurrence" not in str(exc):
                    raise
                # Rolled back before raising: the failed INSERT opened a
                # transaction, and leaving it for the next caller to inherit
                # would make an unrelated write commit inside this one.
                await self._conn.rollback()
                raise DuplicateOccurrence(*occurrence) from exc
            await self._conn.commit()
            return run

    async def get_run(self, run_id: str) -> Run | None:
        row = await self._fetchone(
            "SELECT payload FROM canonical_runs WHERE run_id = ?",
            (run_id,),
        )
        return model_of_json(Run, row[0]) if row is not None else None

    async def list_by_status(
        self,
        status: RunStatus,
        *,
        limit: int = 100,
        offset: int = 0,
        project_id: str | None = None,
    ) -> list[Run]:
        """Runs currently in ``status``, oldest first (#251).

        Mirrored from `DurableRunStore.list_by_status` so the two stores stop
        diverging on query surface; oldest-first so a bounded consumer tick
        drains a backlog fairly.

        A caller that needs to see *every* row eventually, rather than only the
        oldest page, passes ``offset`` and walks it: the resume tick does, because
        its filter is applied after the query and a standing prefix of ineligible
        rows would otherwise hide everything behind it forever (#666 review).
        """
        if limit <= 0:
            raise ValueError("limit must be positive")
        if offset < 0:
            raise ValueError("offset must not be negative")
        sql = "SELECT payload FROM canonical_runs WHERE status = ?"
        params: list[object] = [status.value]
        if project_id is not None:
            sql += " AND project_id = ?"
            params.append(project_id)
        sql += " ORDER BY json_extract(payload, '$.created_at'), run_id LIMIT ? OFFSET ?"
        params.append(limit)
        params.append(offset)
        cursor = await self._conn.execute(sql, tuple(params))  # nosec B608
        rows = await cursor.fetchall()
        return [model_of_json(Run, row[0]) for row in rows]

    async def delete_run(self, run_id: str, *, force: bool = False) -> bool:
        """Forget one terminal Run and everything hanging off it.

        The schema declares ``ON DELETE RESTRICT`` between the three tables, so
        the children are removed first and explicitly rather than relying on a
        cascade the schema deliberately does not grant. One transaction, so a
        crash mid-sweep cannot leave NodeRuns whose Run is gone.

        A Run with child Runs is refused rather than deleted. Those children
        hold `parent_run_id`/`parent_node_run_id` foreign keys into exactly the
        rows this would remove: SQLite would fail the constraint partway
        through, and the in-memory store would silently leave the children
        pointing at ids that no longer resolve. Refusing is the one answer both
        can give truthfully.
        """
        run = await self.get_run(run_id)
        if run is None:
            return False
        if run.status not in TERMINAL_RUN_STATUSES and not force:
            raise RunIntegrityError(
                f"cannot delete Run {run_id!r} in non-terminal status {run.status.value!r}"
            )
        children = await self._fetchone(
            "SELECT COUNT(*) FROM canonical_runs WHERE parent_run_id = ?",
            (run_id,),
        )
        if children is not None and int(children[0]) > 0:
            raise RunIntegrityError(
                f"cannot delete Run {run_id!r} while {int(children[0])} child Run(s) reference "
                "it; delete the descendants first"
            )
        await self._conn.execute(
            """DELETE FROM canonical_attempts WHERE node_run_id IN
               (SELECT node_run_id FROM canonical_node_runs WHERE run_id = ?)""",
            (run_id,),
        )
        await self._conn.execute("DELETE FROM canonical_node_runs WHERE run_id = ?", (run_id,))
        await self._conn.execute("DELETE FROM canonical_runs WHERE run_id = ?", (run_id,))
        await self._conn.commit()
        return True

    async def has_runs_in_project(self, project_id: str) -> bool:
        """Whether any Run is filed in this Project.

        Consulted by `SqliteProjectScopeStore.delete()` so a Project cannot be
        deleted out from under its Run history.
        """
        row = await self._fetchone(
            "SELECT 1 FROM canonical_runs WHERE project_id = ? LIMIT 1",
            (project_id,),
        )
        return row is not None

    async def non_terminal_run_stats(self) -> tuple[int, datetime | None]:
        """How many Runs are non-terminal, and when the oldest one was created.

        The recovery tick's visibility (#462/#338). A status filter plus one
        payload timestamp — ISO-8601 strings in one format order the same way
        the datetimes do, so MIN needs no materialization.
        """
        placeholders = _placeholders(len(_TERMINAL_STATUS_VALUES))
        row = await self._fetchone(
            "SELECT COUNT(*), MIN(json_extract(payload, '$.created_at')) "
            f"FROM canonical_runs WHERE status NOT IN ({placeholders})",
            tuple(_TERMINAL_STATUS_VALUES),
        )
        assert row is not None  # nosec B101 - COUNT(*) always yields a row
        count = int(row[0])
        oldest = datetime.fromisoformat(row[1]) if row[1] else None
        return count, oldest

    async def _purge_candidates(self, limit: int) -> list[tuple[str, Run]]:
        """Terminal Runs carrying a deadline and descended from by nobody.

        Ordered by deadline, so the caller can stop at the first unexpired one
        rather than parsing the whole batch. `json_extract` is only used to
        *narrow* and *order*; the comparison against the cutoff happens in
        Python against a parsed datetime, because comparing ISO-8601 strings
        lexically is only correct while every one of them carries the same UTC
        offset — true today, and not something to make load-bearing.
        """
        sql = _PURGE_CANDIDATES_SQL.format(  # nosec B608 — `{}` takes only `?`s, never data
            statuses=_placeholders(len(_TERMINAL_STATUS_VALUES))
        )
        cursor = await self._conn.execute(sql, (*_TERMINAL_STATUS_VALUES, limit))
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
            marks = _placeholders(len(doomed))
            ids = tuple(doomed)
            # Same reasoning as `_purge_candidates`: the only interpolated text
            # is `marks`, and every run_id travels in the parameter tuple.
            await self._conn.execute(
                _DELETE_ATTEMPTS_SQL.format(runs=marks),
                ids,  # nosec B608
            )
            await self._conn.execute(
                _DELETE_NODE_RUNS_SQL.format(runs=marks),
                ids,  # nosec B608
            )
            await self._conn.execute(
                _DELETE_RUNS_SQL.format(runs=marks),
                ids,  # nosec B608
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
        async with self._write_lock:
            run = await self._require_run(run_id)
            check_completion_is_earned(target, await self._node_runs_of(run_id))
            updated = transition_run(run, target, at=at, result=result, error=error)
            settled: list[NodeRun] = []
            if target in TERMINAL_RUN_STATUSES:
                settled = [
                    settle_open_node_run(node_run, target, at=at)
                    for node_run in await self._open_node_runs(run_id)
                ]
            # One commit for the Run and every NodeRun it settles
            # (ADR-082426-a47f). `_update_payload` commits per call, so the
            # cascade writes through `_stage_payload` and commits once at the
            # end: a half-settled Run reads as deliberate, which is worse than
            # an unsettled one.
            self._stage_payload(
                "canonical_runs", "run_id", run_id, updated.status.value, json_of(updated)
            )
            for node_run in settled:
                self._stage_payload(
                    "canonical_node_runs",
                    "node_run_id",
                    node_run.node_run_id,
                    node_run.status.value,
                    json_of(node_run),
                )
            await self._flush()
            return updated

    async def _open_node_runs(self, run_id: str) -> list[NodeRun]:
        """Every non-terminal NodeRun under this Run, in ordinal order."""
        cursor = await self._conn.execute(
            "SELECT payload FROM canonical_node_runs WHERE run_id = ? "  # nosec B608
            f"AND status NOT IN ({_placeholders(len(_TERMINAL_STATUS_VALUES))}) ORDER BY ordinal",
            (run_id, *_TERMINAL_STATUS_VALUES),
        )
        rows = await cursor.fetchall()
        return [model_of_json(NodeRun, row[0]) for row in rows]

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
                    json_of(node_run),
                ),
            )
            await self._conn.commit()
            return node_run

    async def get_node_run(self, node_run_id: str) -> NodeRun | None:
        row = await self._fetchone(
            "SELECT payload FROM canonical_node_runs WHERE node_run_id = ?",
            (node_run_id,),
        )
        return model_of_json(NodeRun, row[0]) if row is not None else None

    async def _node_runs_of(self, run_id: str) -> list[NodeRun]:
        """Every NodeRun under a Run, without re-checking the Run exists.

        `list_node_runs` is the public read and calls `_require_run`; this runs
        inside `transition_run`, which has already required it.
        """
        cursor = await self._conn.execute(
            "SELECT payload FROM canonical_node_runs WHERE run_id = ?", (run_id,)
        )
        return [model_of_json(NodeRun, row[0]) for row in await cursor.fetchall()]

    async def list_node_runs(self, run_id: str) -> list[NodeRun]:
        await self._require_run(run_id)
        cursor = await self._conn.execute(
            "SELECT payload FROM canonical_node_runs WHERE run_id = ? ORDER BY ordinal",
            (run_id,),
        )
        rows = await cursor.fetchall()
        return [model_of_json(NodeRun, row[0]) for row in rows]

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
            await self._refuse_under_terminal_run(node_run)
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
                json_of(updated),
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
        lease_ttl: timedelta | None = None,
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
                    if lease_ttl is not None:
                        lease = renewed_lease(lease, at=lease.issued_at, ttl=lease_ttl)
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
                        json_of(attempt),
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

    async def renew_lease(
        self,
        attempt_id: str,
        *,
        fencing_token: str,
        ttl: timedelta,
        at: datetime | None = None,
    ) -> Attempt:
        """Prove the holder is still alive, and push its expiry out by ``ttl``."""
        async with self._write_lock:
            attempt = await self._require_attempt(attempt_id)
            renewed = renew_attempt_lease(attempt, fencing_token=fencing_token, ttl=ttl, at=at)
            await self._update_payload(
                "canonical_attempts",
                "attempt_id",
                attempt_id,
                renewed.status.value,
                json_of(renewed),
            )
            return renewed

    async def reclaim_expired_attempts(
        self,
        *,
        now: datetime | None = None,
        limit: int = DEFAULT_RECLAIM_BATCH,
    ) -> list[Attempt]:
        """Terminalize Attempts whose holder stopped renewing.

        Filters in Python rather than SQL: SQLite has no native timestamp type,
        so comparing the lease expiry lexically inside `json_extract` is only
        correct while every stored value carries the same UTC offset — true
        today, and not something to make load-bearing. The candidate set is
        already narrowed to non-terminal Attempts by the status predicate,
        which is the part that matters for cost.
        """
        moment = now if now is not None else datetime.now(UTC)
        cursor = await self._conn.execute(
            """SELECT payload FROM canonical_attempts
               WHERE status IN ('created', 'running')"""
        )
        candidates = [model_of_json(Attempt, row[0]) for row in await cursor.fetchall()]
        doomed = sorted(
            (a for a in candidates if lease_is_expired(a, moment)),
            key=lambda a: (a.execution_lease.expires_at, a.attempt_id),  # type: ignore[union-attr]
        )
        reclaimed: list[Attempt] = []
        async with self._write_lock:
            for attempt in doomed[:limit]:
                settled = reclaim_attempt(attempt, at=moment)
                await self._update_payload(
                    "canonical_attempts",
                    "attempt_id",
                    attempt.attempt_id,
                    settled.status.value,
                    json_of(settled),
                )
                reclaimed.append(settled)
        return reclaimed

    async def get_attempt(self, attempt_id: str) -> Attempt | None:
        row = await self._fetchone(
            "SELECT payload FROM canonical_attempts WHERE attempt_id = ?",
            (attempt_id,),
        )
        return model_of_json(Attempt, row[0]) if row is not None else None

    async def list_attempts(self, node_run_id: str) -> list[Attempt]:
        await self._require_node_run(node_run_id)
        cursor = await self._conn.execute(
            """SELECT payload FROM canonical_attempts
               WHERE node_run_id = ? ORDER BY ordinal""",
            (node_run_id,),
        )
        rows = await cursor.fetchall()
        return [model_of_json(Attempt, row[0]) for row in rows]

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
                json_of(updated),
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

    async def _refuse_under_terminal_run(self, node_run: NodeRun) -> None:
        """Refuse to move a NodeRun whose Run has already finished.

        `create_node_run` has always refused under a terminal Run; without the
        same rule here a reconciliation that lands late rewrites the history of
        a closed Run, and can undo the very cascade that settled it.
        """
        # A completed row without accepted evidence predates AcceptedNodeOutcome.
        # Let it reach transition_node_run's migration validator even after the
        # parent closed; that validator permits only a matching evidence install
        # and preserves all lifecycle fields.
        if node_run.status is RunStatus.COMPLETED and node_run.accepted_outcome is None:
            return
        row = await self._fetchone(
            "SELECT status FROM canonical_runs WHERE run_id = ?",
            (node_run.run_id,),
        )
        if row is None or row[0] not in _TERMINAL_STATUS_VALUES:
            return
        raise RunIntegrityError(
            f"cannot transition NodeRun {node_run.node_run_id!r}: "
            f"Run {node_run.run_id!r} is terminal ({row[0]})"
        )

    def _stage_payload(
        self,
        table: str,
        identity_column: str,
        identity: str,
        status: str,
        payload: str,
    ) -> None:
        """Queue one payload update for the next :meth:`_flush`."""
        self._pending.append((_checked_table(table, identity_column), identity, status, payload))

    async def _flush(self) -> None:
        """Apply every staged update and commit once."""
        pending, self._pending = self._pending, []
        for (table, identity_column), identity, status, payload in pending:
            await self._conn.execute(
                f"UPDATE {table} SET status = ?, payload = ? WHERE {identity_column} = ?",  # nosec B608
                (status, payload, identity),
            )
        await self._conn.commit()

    async def _update_payload(
        self,
        table: str,
        identity_column: str,
        identity: str,
        status: str,
        payload: str,
    ) -> None:
        self._stage_payload(table, identity_column, identity, status, payload)
        await self._flush()


__all__ = ["SqliteRunStore"]
