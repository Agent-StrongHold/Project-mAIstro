"""PostgreSQL persistence for the canonical Run -> NodeRun -> Attempt spine (#132).

The durable twin of `sqlite_store.py`, against the system of record
ADR-082226-5104 names. The spine is the one thing that must not be ephemeral: it
is what an audit, a recovery, a retry and a resumed HITL pause all read.

The SQL is a translation; the concurrency is not. SQLite serialises writers at
the database — `BEGIN IMMEDIATE` takes a whole-file write lock — so a
check-then-insert cannot race and the unique indexes never fire. PostgreSQL
admits concurrent writers, so the same shape *is* a race, and three questions
the SQLite store never had to answer become real:

  - **Two workers starting the same node.** Both pass an application-level
    "is there an active Attempt?" check. Only one passes the partial unique
    index on `(node_run_id) WHERE status IN ('created','running')`.
  - **Ordinal allocation.** `MAX(ordinal) + 1` read concurrently returns the
    same number twice. The parent row is locked `FOR UPDATE` first, which
    serialises allocation per NodeRun without serialising the whole store.
  - **Interleaved transitions.** Read-modify-write on a payload loses one
    writer's change. Every transition re-reads under `FOR UPDATE` inside the
    transaction that writes it.

The row lock is what makes the checks meaningful; the unique index is what
catches the case the lock cannot cover (a writer that got the lock, released it,
and raced another that did the same). Both, deliberately — either alone leaves a
window.

Payloads are JSONB and come back as dicts, because the pool registers a JSON
codec (`maistro.persistence._register_json_codecs`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from maistro.graph.definitions import Graph
from maistro.projects.scope_store import ProjectScopeStore
from maistro.runs.evidence_json import decode_evidence, decode_payload, json_of, model_of
from maistro.runs.lifecycle import (
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
from maistro.runs.store import (
    DEFAULT_PURGE_BATCH,
    ActiveAttemptExists,
    AttemptNotFound,
    NodeRunNotFound,
    RunIntegrityError,
    RunNotFound,
    StaleExecutionFence,
    admit_in_state,
    validate_accepted_outcome_against_attempt,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    import asyncpg

#: Attempt statuses that count as occupying a NodeRun. Mirrors the partial
#: unique index in migration 010 — if these two ever disagree, the index stops
#: enforcing what this store believes it enforces.
_ACTIVE_ATTEMPT_STATUSES = ("created", "running")

#: Terminal Run statuses as the database spells them. Derived from the model
#: rather than written out, so a new terminal status cannot silently become one
#: retention refuses to sweep.
_TERMINAL_RUN_STATUS_VALUES = sorted(status.value for status in TERMINAL_RUN_STATUSES)

#: Tables this store may write, and the column identifying a row in each.
#: `_update_payload` interpolates the table name, so the pair is checked against
#: this set rather than trusted.
_PAYLOAD_TABLES = {
    "canonical_runs": "run_id",
    "canonical_node_runs": "node_run_id",
    "canonical_attempts": "attempt_id",
}


#: Status values that mean a Run or NodeRun is finished, as stored.
_TERMINAL_STATUS_VALUES = tuple(sorted(status.value for status in TERMINAL_RUN_STATUSES))


class PgRunStore:
    """Durable store for canonical execution identity and lifecycle."""

    def __init__(self, pool: asyncpg.Pool, *, project_store: ProjectScopeStore) -> None:
        self._pool = pool
        self._project_store = project_store

    # ── Run ───────────────────────────────────────────────────────

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
        # Before the insert, not after it: one commit, so there is no window in
        # which a process death leaves a CREATED Run whose receipt was queued.
        run = admit_in_state(run, initial_status)
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO canonical_runs
                   (run_id, workspace_id, project_id, parent_run_id,
                    parent_node_run_id, status, payload, retention_expires_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7::text::jsonb, $8)""",
                run.run_id,
                run.workspace_id,
                run.project_id,
                run.parent_run_id,
                run.parent_node_run_id,
                run.status.value,
                json_of(run),
                # Duplicated out of the payload so the retention sweep can use
                # an index (migration 012). Written once at creation and never
                # transitioned, so the two cannot drift the way `status` could.
                run.retention_expires_at,
            )
        return run

    async def purge_expired_runs(
        self,
        *,
        now: datetime | None = None,
        limit: int = DEFAULT_PURGE_BATCH,
    ) -> int:
        """Delete up to ``limit`` expired terminal Runs. Returns how many went.

        One statement, in one transaction, in the order the foreign keys
        require: Attempts, then NodeRuns, then Runs. Every FK into the spine is
        `ON DELETE RESTRICT` by design, so retention must not be the thing that
        discovers that.

        `FOR UPDATE SKIP LOCKED` on the candidate select rather than plain
        `FOR UPDATE`: two processes sweeping concurrently should divide the
        work, not queue behind each other, and a Run another transaction is
        mid-transition on is one this sweep should leave alone anyway.
        """
        if limit <= 0:
            raise ValueError("limit must be positive")
        cutoff = now if now is not None else datetime.now(UTC)
        async with self._pool.acquire() as conn, conn.transaction():
            rows = await conn.fetch(
                """SELECT run_id FROM canonical_runs r
                    WHERE r.retention_expires_at IS NOT NULL
                      AND r.retention_expires_at <= $1
                      AND r.status = ANY($2::text[])
                      AND NOT EXISTS (
                          SELECT 1 FROM canonical_runs c WHERE c.parent_run_id = r.run_id
                      )
                      AND NOT EXISTS (
                          SELECT 1 FROM canonical_node_runs n
                          JOIN canonical_runs c2 ON c2.parent_node_run_id = n.node_run_id
                          WHERE n.run_id = r.run_id
                      )
                    ORDER BY r.retention_expires_at
                    LIMIT $3
                    FOR UPDATE SKIP LOCKED""",
                cutoff,
                _TERMINAL_RUN_STATUS_VALUES,
                limit,
            )
            run_ids = [row["run_id"] for row in rows]
            if not run_ids:
                return 0
            await conn.execute(
                """DELETE FROM canonical_attempts a
                   USING canonical_node_runs n
                   WHERE a.node_run_id = n.node_run_id AND n.run_id = ANY($1::text[])""",
                run_ids,
            )
            await conn.execute(
                "DELETE FROM canonical_node_runs WHERE run_id = ANY($1::text[])", run_ids
            )
            await conn.execute("DELETE FROM canonical_runs WHERE run_id = ANY($1::text[])", run_ids)
        return len(run_ids)

    async def delete_run(self, run_id: str, *, force: bool = False) -> bool:
        """Forget one terminal Run and everything hanging off it.

        The single-Run counterpart of `purge_expired_runs`, and it answers the
        same three questions the same way, because chat retention (#131) sweeps
        one Run at a time while this spine's deadline sweep takes a batch. Same
        delete order — Attempts, NodeRuns, Runs — because every foreign key into
        the spine is `ON DELETE RESTRICT` by design.

        A Run with child Runs is refused rather than deleted: those children
        hold `parent_run_id`/`parent_node_run_id` into exactly the rows this
        would remove. PostgreSQL would refuse the delete anyway; naming the rule
        is what turns a raw constraint error into something a caller can act on.

        `force` skips only the terminal check, and only for retention, which
        already decided the Run is past its deadline. It never skips the child
        check — an orphaned parent pointer is not a policy decision.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "SELECT status FROM canonical_runs WHERE run_id = $1 FOR UPDATE", run_id
            )
            if row is None:
                return False
            status = RunStatus(row["status"])
            if status not in TERMINAL_RUN_STATUSES and not force:
                raise RunIntegrityError(
                    f"cannot delete Run {run_id!r} in non-terminal status {status.value!r}"
                )
            children = await conn.fetchval(
                "SELECT COUNT(*) FROM canonical_runs WHERE parent_run_id = $1", run_id
            )
            if children:
                raise RunIntegrityError(
                    f"cannot delete Run {run_id!r} while {int(children)} child Run(s) reference "
                    "it; delete the descendants first"
                )
            await conn.execute(
                """DELETE FROM canonical_attempts a
                   USING canonical_node_runs n
                   WHERE a.node_run_id = n.node_run_id AND n.run_id = $1""",
                run_id,
            )
            await conn.execute("DELETE FROM canonical_node_runs WHERE run_id = $1", run_id)
            await conn.execute("DELETE FROM canonical_runs WHERE run_id = $1", run_id)
        return True

    async def get_run(self, run_id: str) -> Run | None:
        payload = await self._payload(
            "SELECT payload FROM canonical_runs WHERE run_id = $1", run_id
        )
        return Run.model_validate(payload) if payload is not None else None

    async def has_runs_in_project(self, project_id: str) -> bool:
        """Whether any Run is filed in this Project.

        Not what stops the deletion — the foreign key does — but what lets
        `PgProjectScopeStore.delete()` say *which* rule refused instead of
        surfacing a raw constraint name.
        """
        async with self._pool.acquire() as conn:
            found = await conn.fetchval(
                "SELECT 1 FROM canonical_runs WHERE project_id = $1 LIMIT 1", project_id
            )
        return found is not None

    async def transition_run(
        self,
        run_id: str,
        target: RunStatus,
        *,
        at: datetime | None = None,
        result: object | None = None,
        error: str | None = None,
    ) -> Run:
        async with self._pool.acquire() as conn, conn.transaction():
            run = Run.model_validate(await self._locked(conn, "canonical_runs", "run_id", run_id))
            updated = transition_run(run, target, at=at, result=result, error=error)
            # The cascade runs inside the Run's own transaction, with the Run
            # row already locked (ADR-082426-a47f). Lock order is Run then
            # NodeRun everywhere in this store — `create_node_run` and
            # `transition_node_run` take the same two in the same order — so a
            # concurrent transition on a sibling node cannot deadlock this one.
            if target in TERMINAL_RUN_STATUSES:
                for node_run in await self._locked_open_node_runs(conn, run_id):
                    await self._write(
                        conn,
                        "canonical_node_runs",
                        "node_run_id",
                        node_run.node_run_id,
                        settle_open_node_run(node_run, target, at=at),
                    )
            await self._write(conn, "canonical_runs", "run_id", run_id, updated)
        return updated

    async def _locked_open_node_runs(self, conn: Any, run_id: str) -> list[NodeRun]:
        """Lock and return every non-terminal NodeRun under this Run."""
        rows = await conn.fetch(
            """SELECT payload FROM canonical_node_runs
               WHERE run_id = $1 AND status <> ALL($2::text[])
               ORDER BY ordinal
               FOR UPDATE""",
            run_id,
            list(_TERMINAL_STATUS_VALUES),
        )
        return [
            NodeRun.model_validate(decode_evidence(decode_payload(row["payload"]))) for row in rows
        ]

    # ── NodeRun ───────────────────────────────────────────────────

    async def create_node_run(self, run_id: str, *, node_id: str) -> NodeRun:
        async with self._pool.acquire() as conn, conn.transaction():
            # The parent Run is locked before its ordinals are read, so two
            # concurrent creators under one Run cannot both allocate the same
            # ordinal. The UNIQUE (run_id, ordinal) constraint is the backstop.
            run = Run.model_validate(await self._locked(conn, "canonical_runs", "run_id", run_id))
            if run.status in TERMINAL_RUN_STATUSES:
                raise RunIntegrityError("cannot create NodeRun under a terminal Run")
            graph = run.graph.materialize()
            if not any(node.node_id == node_id for node in graph.nodes):
                raise RunIntegrityError(
                    f"node_id {node_id!r} is not present in the Run Graph snapshot",
                )
            ordinal = (
                await conn.fetchval(
                    "SELECT COALESCE(MAX(ordinal), 0) FROM canonical_node_runs WHERE run_id = $1",
                    run_id,
                )
            ) + 1
            node_run = NodeRun(run_id=run_id, node_id=node_id, ordinal=ordinal)
            await conn.execute(
                """INSERT INTO canonical_node_runs
                   (node_run_id, run_id, node_id, ordinal, status, payload)
                   VALUES ($1, $2, $3, $4, $5, $6::text::jsonb)""",
                node_run.node_run_id,
                node_run.run_id,
                node_run.node_id,
                node_run.ordinal,
                node_run.status.value,
                json_of(node_run),
            )
        return node_run

    async def get_node_run(self, node_run_id: str) -> NodeRun | None:
        payload = await self._payload(
            "SELECT payload FROM canonical_node_runs WHERE node_run_id = $1", node_run_id
        )
        return NodeRun.model_validate(payload) if payload is not None else None

    async def list_node_runs(self, run_id: str) -> list[NodeRun]:
        await self._require_run(run_id)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT payload FROM canonical_node_runs WHERE run_id = $1 ORDER BY ordinal",
                run_id,
            )
        return [model_of(NodeRun, row["payload"]) for row in rows]

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
        async with self._pool.acquire() as conn, conn.transaction():
            node_run = NodeRun.model_validate(await self._peek_node_run(conn, node_run_id))
            # Parent Run first, then the NodeRun row: the same order
            # `create_node_run` and `transition_run` take, which is what keeps
            # a cascade and a sibling transition from deadlocking each other.
            await self._refuse_under_terminal_run(conn, node_run)
            node_run = NodeRun.model_validate(
                await self._locked(conn, "canonical_node_runs", "node_run_id", node_run_id)
            )
            if accepted_outcome is not None:
                if accepted_outcome.node_run_id != node_run_id:
                    raise RunIntegrityError("accepted outcome belongs to a different NodeRun")
                attempt = await self._require_attempt(
                    accepted_outcome.attempt_result.attempt_id, conn=conn
                )
                validate_accepted_outcome_against_attempt(accepted_outcome, attempt)
            updated = transition_node_run(
                node_run,
                target,
                at=at,
                result=result,
                error=error,
                accepted_outcome=accepted_outcome,
            )
            await self._write(conn, "canonical_node_runs", "node_run_id", node_run_id, updated)
        return updated

    # ── Attempt ───────────────────────────────────────────────────

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
        """Start an Attempt, or refuse because one is already running.

        This is the method the retry model rests on. The NodeRun row is locked
        first so the active-Attempt check and the ordinal allocation see a
        consistent picture; the partial unique index catches whatever the lock
        does not.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            node_run = NodeRun.model_validate(
                await self._locked(conn, "canonical_node_runs", "node_run_id", node_run_id)
            )
            if node_run.status in TERMINAL_RUN_STATUSES:
                raise RunIntegrityError("cannot create Attempt under a terminal NodeRun")
            if await self._active_attempt_id(conn, node_run_id) is not None:
                raise ActiveAttemptExists(
                    f"NodeRun {node_run_id!r} already has an active Attempt",
                )
            ordinal = (
                await conn.fetchval(
                    """SELECT COALESCE(MAX(ordinal), 0) FROM canonical_attempts
                       WHERE node_run_id = $1""",
                    node_run_id,
                )
            ) + 1
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
            try:
                await conn.execute(
                    """INSERT INTO canonical_attempts
                       (attempt_id, node_run_id, ordinal, status, payload)
                       VALUES ($1, $2, $3, $4, $5::text::jsonb)""",
                    attempt.attempt_id,
                    attempt.node_run_id,
                    attempt.ordinal,
                    attempt.status.value,
                    json_of(attempt),
                )
            except _integrity_errors() as exc:
                raise _integrity_failure(exc, node_run_id) from exc
        return attempt

    async def get_attempt(self, attempt_id: str) -> Attempt | None:
        payload = await self._payload(
            "SELECT payload FROM canonical_attempts WHERE attempt_id = $1", attempt_id
        )
        return Attempt.model_validate(payload) if payload is not None else None

    async def list_attempts(self, node_run_id: str) -> list[Attempt]:
        await self._require_node_run(node_run_id)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT payload FROM canonical_attempts
                   WHERE node_run_id = $1 ORDER BY ordinal""",
                node_run_id,
            )
        return [model_of(Attempt, row["payload"]) for row in rows]

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
        async with self._pool.acquire() as conn, conn.transaction():
            attempt = Attempt.model_validate(
                await self._locked(conn, "canonical_attempts", "attempt_id", attempt_id)
            )
            # Fence checked inside the lock. Outside it, a stale worker could
            # read a lease that a newer one replaced a moment later and pass a
            # check that was true when it ran and false when it wrote.
            self._validate_fence(attempt, fencing_token)
            updated = transition_attempt(
                attempt, target, at=at, result=result, error=error, metrics=metrics
            )
            await self._write(conn, "canonical_attempts", "attempt_id", attempt_id, updated)
        return updated

    # ── internals ─────────────────────────────────────────────────

    @staticmethod
    def _validate_fence(attempt: Attempt, fencing_token: str | None) -> None:
        lease = attempt.execution_lease
        if lease is not None and fencing_token != lease.fencing_token:
            raise StaleExecutionFence(
                f"Attempt {attempt.attempt_id!r} update rejected by execution fence"
            )

    @staticmethod
    async def _active_attempt_id(conn: Any, node_run_id: str) -> str | None:
        attempt_id: Any = await conn.fetchval(
            """SELECT attempt_id FROM canonical_attempts
               WHERE node_run_id = $1 AND status = ANY($2::text[])
               LIMIT 1""",
            node_run_id,
            list(_ACTIVE_ATTEMPT_STATUSES),
        )
        return str(attempt_id) if attempt_id is not None else None

    async def _validate_graph_scope(self, graph: Graph) -> None:
        project = await self._project_store.get(graph.project_id)
        if project is None:
            raise RunIntegrityError(
                f"Graph Project {graph.project_id!r} does not exist in canonical Project scope",
            )
        if project.workspace_id != graph.workspace_id:
            raise RunIntegrityError("Graph Project does not belong to the Graph Workspace")

    @staticmethod
    async def _peek_node_run(conn: Any, node_run_id: str) -> Any:
        """Read a NodeRun payload without locking, to find its Run.

        Unlocked deliberately: the lock this method's caller needs is on the
        parent Run, and taking the NodeRun's first would invert the store's one
        lock order. The row is re-read under its own lock straight after.
        """
        payload = await conn.fetchval(
            "SELECT payload FROM canonical_node_runs WHERE node_run_id = $1",
            node_run_id,
        )
        if payload is None:
            raise NodeRunNotFound(node_run_id)
        return decode_evidence(decode_payload(payload))

    async def _refuse_under_terminal_run(self, conn: Any, node_run: NodeRun) -> None:
        """Refuse to move a NodeRun whose Run has already finished.

        `create_node_run` has always refused under a terminal Run; without the
        same rule here a reconciliation that lands late rewrites the history of
        a closed Run, and can undo the very cascade that settled it.
        """
        run = Run.model_validate(
            await self._locked(conn, "canonical_runs", "run_id", node_run.run_id)
        )
        if run.status in TERMINAL_RUN_STATUSES:
            raise RunIntegrityError(
                f"cannot transition NodeRun {node_run.node_run_id!r}: "
                f"Run {run.run_id!r} is terminal ({run.status.value})"
            )

    async def _locked(self, conn: Any, table: str, column: str, identity: str) -> Any:
        """Read a payload under a row lock, or raise the right not-found error."""
        if _PAYLOAD_TABLES.get(table) != column:
            raise ValueError("unsupported canonical execution table")
        payload = await conn.fetchval(
            f"SELECT payload FROM {table} WHERE {column} = $1 FOR UPDATE",  # nosec B608
            identity,
        )
        if payload is None:
            raise _NOT_FOUND[table](identity)
        return decode_evidence(decode_payload(payload))

    @staticmethod
    async def _write(conn: Any, table: str, column: str, identity: str, model: Any) -> None:
        if _PAYLOAD_TABLES.get(table) != column:
            raise ValueError("unsupported canonical execution table")
        await conn.execute(
            f"UPDATE {table} SET status = $1, payload = $2::text::jsonb WHERE {column} = $3",  # nosec B608
            model.status.value,
            json_of(model),
            identity,
        )

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

    async def _require_attempt(self, attempt_id: str, *, conn: Any = None) -> Attempt:
        """Load an Attempt, reusing an open connection when inside a transaction.

        Acquiring a second connection from the pool while holding one is how a
        pool deadlocks under load: the first is not released until the
        transaction ends, and the second may be waiting for a slot only the
        first can free.
        """
        if conn is None:
            attempt = await self.get_attempt(attempt_id)
        else:
            payload = await conn.fetchval(
                "SELECT payload FROM canonical_attempts WHERE attempt_id = $1", attempt_id
            )
            attempt = model_of(Attempt, payload) if payload is not None else None
        if attempt is None:
            raise AttemptNotFound(attempt_id)
        return attempt

    async def _payload(self, sql: str, *params: Any) -> Any | None:
        async with self._pool.acquire() as conn:
            payload = await conn.fetchval(sql, *params)
        return decode_evidence(decode_payload(payload)) if payload is not None else None


_NOT_FOUND: dict[str, type[Exception]] = {
    "canonical_runs": RunNotFound,
    "canonical_node_runs": NodeRunNotFound,
    "canonical_attempts": AttemptNotFound,
}


def _integrity_errors() -> tuple[type[Exception], ...]:
    """The asyncpg exceptions that mean a constraint refused this write.

    Catching bare `Exception` here swallowed command timeouts, connection
    resets and every other transient database failure into a generic
    `RunIntegrityError`, so a caller could not tell a retryable outage from a
    permanent domain refusal — while every other operation on this store let
    the driver error through. Narrow, and resolved lazily because asyncpg is an
    optional dependency of this package.
    """
    import asyncpg

    return (asyncpg.exceptions.IntegrityConstraintViolationError,)


def _integrity_failure(exc: Exception, node_run_id: str) -> Exception:
    """Translate a constraint violation into the domain error it means.

    Matched on the constraint name rather than the exception class: asyncpg
    raises `UniqueViolationError` for both "another Attempt is already active"
    and "two writers allocated the same ordinal", and those are different
    answers — the first is a legitimate refusal a caller handles, the second is
    a bug in this store.
    """
    constraint = str(getattr(exc, "constraint_name", "") or "")
    if constraint == "ix_canonical_attempts_one_active":
        return ActiveAttemptExists(f"NodeRun {node_run_id!r} already has an active Attempt")
    if constraint == "uq_canonical_attempts_node_run_ordinal":
        return RunIntegrityError(
            "two writers allocated the same Attempt ordinal; the NodeRun row lock did not hold"
        )
    return RunIntegrityError("Attempt persistence integrity failure")


__all__ = ["PgRunStore"]
