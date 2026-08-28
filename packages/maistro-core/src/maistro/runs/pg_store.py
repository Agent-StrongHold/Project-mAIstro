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

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from maistro.archive.protocols import ArchiveStore
from maistro.archive.types import ArchiveKey
from maistro.graph.definitions import Graph
from maistro.projects.scope_store import ProjectScopeStore
from maistro.runs.evidence_json import decode_evidence, decode_payload, json_of, model_of
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
    DEFAULT_ARCHIVE_AFTER,
    DEFAULT_PURGE_BATCH,
    DEFAULT_RECLAIM_BATCH,
    ActiveAttemptExists,
    ArchivedPayloadUnavailable,
    AttemptNotFound,
    DuplicateOccurrence,
    NodeRunNotFound,
    RunIntegrityError,
    RunNotFound,
    StaleExecutionFence,
    admit_in_state,
    validate_accepted_outcome_against_attempt,
    validate_child_scope,
)

#: The unique index migration 015 creates. Compared against
#: `UniqueViolationError.constraint_name` so a violation on any *other*
#: constraint keeps its own identity instead of being reported as a duplicate
#: firing.
OCCURRENCE_INDEX = "ix_canonical_runs_occurrence"

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

    def __init__(
        self,
        pool: asyncpg.Pool,
        *,
        project_store: ProjectScopeStore,
        archive_store: ArchiveStore | None = None,
    ) -> None:
        self._pool = pool
        self._project_store = project_store
        # None means the tier is off (f436 decision 9). A store with archived
        # rows and no archive configured still reads correctly for everything
        # resident and raises `ArchivedPayloadUnavailable` -- never an empty
        # result -- for what moved.
        self._archive_store = archive_store

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
            # The shared check, not a second copy of its two conditions. Its own
            # docstring says duplicating them at a call site is "the smaller diff
            # and the worse one", and this store was that duplicate.
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
        # Before the insert, not after it: one commit, so there is no window in
        # which a process death leaves a CREATED Run whose receipt was queued.
        run = admit_in_state(run, initial_status)
        async with self._pool.acquire() as conn:
            try:
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
            except _integrity_errors() as exc:
                conflict = _occurrence_conflict(exc, run)
                if conflict is None:
                    raise
                raise conflict from exc
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

    async def archive_cold_runs(
        self,
        *,
        now: datetime | None = None,
        archive_after: timedelta = DEFAULT_ARCHIVE_AFTER,
        limit: int = DEFAULT_PURGE_BATCH,
    ) -> int:
        """Move up to ``limit`` cold Run payloads to the archive. Returns how many.

        The counterpart of :meth:`purge_expired_runs` and deliberately not part
        of it. The predicate here is `retention_expires_at IS NULL` and the one
        there is `IS NOT NULL`, so the two select disjoint populations by
        construction (f436 decision 10): a Run somebody chose a deletion date
        for is purged and never archived, and one kept indefinitely is archived
        and never purged. Sharing a sweep between them is how archiving would
        quietly become a way to avoid deciding which a record deserves.

        **Order is the durability argument.** The bytes reach the archive
        first, and only then does the row give up its payload. A crash between
        the two leaves an object nothing references -- content-addressed, so
        the next sweep writes the same key and adopts it -- while the reverse
        order would leave a row whose payload is gone and whose archive never
        received it. One is waste; the other is data loss.

        `FOR UPDATE SKIP LOCKED`, like the retention sweep, so two processes
        divide the backlog instead of queuing. Candidates are terminal by
        definition, so no concurrent transition can be racing the payload this
        reads -- the lock is what keeps two *sweepers* from both paying for the
        same upload.
        """
        if limit <= 0:
            raise ValueError("limit must be positive")
        if self._archive_store is None:
            return 0
        cutoff = (now if now is not None else datetime.now(UTC)) - archive_after
        async with self._pool.acquire() as conn, conn.transaction():
            rows = await conn.fetch(
                """SELECT run_id, project_id, payload FROM canonical_runs
                    WHERE archive_key IS NULL
                      AND retention_expires_at IS NULL
                      AND finished_at IS NOT NULL
                      AND finished_at <= $1
                      AND status = ANY($2::text[])
                    ORDER BY finished_at
                    LIMIT $3
                    FOR UPDATE SKIP LOCKED""",
                cutoff,
                _TERMINAL_RUN_STATUS_VALUES,
                limit,
            )
            for row in rows:
                await self._archive_tree(conn, row["run_id"], scope=row["project_id"])
                # Re-serialised through `json_of` rather than shipping the raw
                # column text: that is the encoder the payload was written with,
                # so the archived bytes are byte-identical to what a read would
                # have produced and non-finite evidence survives the move.
                run = model_of(Run, row["payload"])
                await self._move_payload(
                    conn,
                    "canonical_runs",
                    "run_id",
                    row["run_id"],
                    json_of(run).encode("utf-8"),
                    scope=row["project_id"],
                )
        return len(rows)

    async def _archive_tree(self, conn: Any, run_id: str, *, scope: str) -> None:
        """Move the NodeRun and Attempt payloads under one Run.

        The Attempt evidence is the reason the tier exists. A Run's own payload
        is a graph snapshot and a result; the rows underneath are one per
        physical try, each carrying whatever the executor returned, and on a
        Run that retried they are most of the bytes. Archiving the Run alone
        would move the index and leave the book.

        Children before the parent. Both orders are safe -- every individual
        move puts before it nulls -- but this one keeps the entry point
        readable throughout: a crash mid-tree leaves a Run whose payload is
        still resident and whose children read through, rather than the
        reverse.

        Scoped by the *Run's* Project, which the child rows do not carry. That
        is deliberate rather than incidental: scope is how the archive is
        listed and how a Project's cold bytes are found, and a NodeRun belongs
        to exactly the Project its Run does.
        """
        node_runs = await conn.fetch(
            """SELECT node_run_id, payload FROM canonical_node_runs
                WHERE run_id = $1 AND archive_key IS NULL
                FOR UPDATE""",
            run_id,
        )
        attempts = await conn.fetch(
            """SELECT a.attempt_id, a.payload FROM canonical_attempts a
                 JOIN canonical_node_runs n ON a.node_run_id = n.node_run_id
                WHERE n.run_id = $1 AND a.archive_key IS NULL
                FOR UPDATE OF a""",
            run_id,
        )
        for attempt in attempts:
            await self._move_payload(
                conn,
                "canonical_attempts",
                "attempt_id",
                attempt["attempt_id"],
                json_of(model_of(Attempt, attempt["payload"])).encode("utf-8"),
                scope=scope,
            )
        for node_run in node_runs:
            await self._move_payload(
                conn,
                "canonical_node_runs",
                "node_run_id",
                node_run["node_run_id"],
                json_of(model_of(NodeRun, node_run["payload"])).encode("utf-8"),
                scope=scope,
            )

    async def _move_payload(
        self,
        conn: Any,
        table: str,
        column: str,
        identity: str,
        payload: bytes,
        *,
        scope: str,
    ) -> None:
        """Put the bytes, then drop the column. Never the other way round.

        A crash between the two leaves an object nothing references --
        content-addressed, so the next sweep writes the same key and adopts it.
        The reverse order would leave a row whose payload is gone and whose
        archive never received it. One is waste; the other is data loss.
        """
        if _PAYLOAD_TABLES.get(table) != column:
            raise ValueError("unsupported canonical execution table")
        assert self._archive_store is not None  # nosec B101 - caller checked
        key = await self._archive_store.put(payload, scope=scope)
        await conn.execute(
            f"UPDATE {table} SET payload = NULL, archive_key = $1 WHERE {column} = $2",  # nosec B608
            str(key),
            identity,
        )

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
            "SELECT run_id, payload, archive_key FROM canonical_runs WHERE run_id = $1", run_id
        )
        return Run.model_validate(payload) if payload is not None else None

    async def list_by_status(
        self,
        status: RunStatus,
        *,
        limit: int = 100,
        project_id: str | None = None,
    ) -> list[Run]:
        """Runs currently in ``status``, oldest first (#251).

        Mirrored from `DurableRunStore.list_by_status` so the two stores stop
        diverging on query surface; oldest-first so a bounded consumer tick
        drains a backlog fairly. Non-terminal payloads are never offloaded to
        the archive, so the rows read back whole.
        """
        if limit <= 0:
            raise ValueError("limit must be positive")
        sql = "SELECT payload FROM canonical_runs WHERE status = $1 AND payload IS NOT NULL"
        params: list[object] = [status.value]
        if project_id is not None:
            sql += " AND project_id = $2"
            params.append(project_id)
        sql += f" ORDER BY payload->>'created_at', run_id LIMIT ${len(params) + 1}"
        params.append(limit)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [Run.model_validate(decode_payload(row["payload"])) for row in rows]

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
            # Read inside the Run's transaction, with its row already locked:
            # checking against NodeRuns fetched on another connection would be
            # checking a snapshot a concurrent writer may already have moved.
            rows = await conn.fetch(
                "SELECT payload FROM canonical_node_runs WHERE run_id = $1", run_id
            )
            check_completion_is_earned(target, [model_of(NodeRun, row["payload"]) for row in rows])
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
            "SELECT node_run_id, payload, archive_key FROM canonical_node_runs WHERE node_run_id = $1",
            node_run_id,
        )
        return NodeRun.model_validate(payload) if payload is not None else None

    async def list_node_runs(self, run_id: str) -> list[NodeRun]:
        await self._require_run(run_id)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT node_run_id, payload, archive_key FROM canonical_node_runs
                    WHERE run_id = $1 ORDER BY ordinal""",
                run_id,
            )
        # Read-through, because this is how an audit reads down from a Run and
        # the whole tree goes cold together. A list that silently dropped the
        # archived rows would report a Run as having had fewer nodes than it did.
        return [NodeRun.model_validate(await self._hydrate(row)) for row in rows]

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
        lease_ttl: timedelta | None = None,
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
                if lease_ttl is not None:
                    lease = renewed_lease(lease, at=lease.issued_at, ttl=lease_ttl)
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
            "SELECT attempt_id, payload, archive_key FROM canonical_attempts WHERE attempt_id = $1",
            attempt_id,
        )
        return Attempt.model_validate(payload) if payload is not None else None

    async def list_attempts(self, node_run_id: str) -> list[Attempt]:
        await self._require_node_run(node_run_id)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT attempt_id, payload, archive_key FROM canonical_attempts
                   WHERE node_run_id = $1 ORDER BY ordinal""",
                node_run_id,
            )
        # The Attempt evidence is the bulk of what the tier moves, so this is
        # the read that most often comes back from the archive.
        return [Attempt.model_validate(await self._hydrate(row)) for row in rows]

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
        # A completed row without accepted evidence predates AcceptedNodeOutcome.
        # Let it reach transition_node_run's migration validator even after the
        # parent closed; that validator permits only a matching evidence install
        # and preserves all lifecycle fields.
        if node_run.status is RunStatus.COMPLETED and node_run.accepted_outcome is None:
            return
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
        row = await conn.fetchrow(
            f"SELECT {column}, payload, archive_key FROM {table} "  # nosec B608
            f"WHERE {column} = $1 FOR UPDATE",
            identity,
        )
        if row is None:
            raise _NOT_FOUND[table](identity)
        return await self._hydrate(row)

    @staticmethod
    async def _write(conn: Any, table: str, column: str, identity: str, model: Any) -> None:
        """Write one model back, keeping the promoted columns in step.

        `canonical_runs.finished_at` is a duplicate of the payload field, and
        migration 017 promoted it for the same reason 013 promoted
        `retention_expires_at`: the archive sweep filters on it, and
        `(payload->>'finished_at')::timestamptz` is STABLE, so PostgreSQL will
        not index it. A promoted column that only the migration's backfill ever
        wrote would be correct for historical rows and silently empty for every
        Run terminalised afterwards -- so the sweep would archive the old and
        never the new, which is worse than not having the column.

        `archive_key` is deliberately *not* cleared here. Writing a payload to
        an archived row would leave both present and trip migration 017's CHECK,
        and that is the outcome worth having: an archived Run is terminal and
        cannot legally transition, so a write reaching one is a bug that should
        surface as a constraint violation rather than as a silently orphaned
        object in the bucket.
        """
        if _PAYLOAD_TABLES.get(table) != column:
            raise ValueError("unsupported canonical execution table")
        if table == "canonical_runs":
            await conn.execute(
                """UPDATE canonical_runs
                      SET status = $1, payload = $2::text::jsonb, finished_at = $4
                    WHERE run_id = $3""",
                model.status.value,
                json_of(model),
                identity,
                model.finished_at,
            )
            return
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

    async def renew_lease(
        self,
        attempt_id: str,
        *,
        fencing_token: str,
        ttl: timedelta,
        at: datetime | None = None,
    ) -> Attempt:
        """Prove the holder is still alive, and push its expiry out by ``ttl``.

        Row-locked for the same reason `transition_attempt` is: a renewal that
        read a snapshot could extend a lease a concurrent sweep has already
        reclaimed, resurrecting an Attempt recovery had settled.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            attempt = Attempt.model_validate(
                await self._locked(conn, "canonical_attempts", "attempt_id", attempt_id)
            )
            renewed = renew_attempt_lease(attempt, fencing_token=fencing_token, ttl=ttl, at=at)
            await self._write(conn, "canonical_attempts", "attempt_id", attempt_id, renewed)
        return renewed

    async def reclaim_expired_attempts(
        self,
        *,
        now: datetime | None = None,
        limit: int = DEFAULT_RECLAIM_BATCH,
    ) -> list[Attempt]:
        """Terminalize Attempts whose holder stopped renewing.

        The expiry predicate runs in SQL, cast to `timestamptz` rather than
        compared as text: `expires_at` is stored as an ISO-8601 string inside
        the payload, and a lexical comparison is only correct while every
        stored value carries the same offset — true today, and not something to
        make load-bearing.

        **No dedicated index, deliberately.** The obvious one — an expression
        index on the cast expiry — is impossible: `text::timestamptz` depends on
        the session `TimeZone` and PostgreSQL refuses to index a non-IMMUTABLE
        expression. It is also unnecessary. `ix_canonical_attempts_one_active`
        (migration 012) is unique and partial on the same `status IN
        ('created','running')` predicate, so at most one Attempt per NodeRun is
        ever a candidate, and the candidate set is bounded by **worker
        concurrency rather than by history**. A sweep scans the Attempts that
        are running now, not every Attempt ever run.

        `FOR UPDATE SKIP LOCKED` so two concurrent sweepers divide the work
        instead of blocking on each other — the same rule the schedule
        occurrence admission uses.
        """
        moment = now if now is not None else datetime.now(UTC)
        reclaimed: list[Attempt] = []
        async with self._pool.acquire() as conn, conn.transaction():
            rows = await conn.fetch(
                """SELECT payload FROM canonical_attempts
                   WHERE status IN ('created', 'running')
                     AND payload->'execution_lease'->>'expires_at' IS NOT NULL
                     AND (payload->'execution_lease'->>'expires_at')::timestamptz <= $1
                   ORDER BY (payload->'execution_lease'->>'expires_at')::timestamptz
                   LIMIT $2
                   FOR UPDATE SKIP LOCKED""",
                moment,
                limit,
            )
            for row in rows:
                attempt = model_of(Attempt, row["payload"])
                if not lease_is_expired(attempt, moment):  # pragma: no cover - SQL already filtered
                    continue
                settled = reclaim_attempt(attempt, at=moment)
                await self._write(
                    conn, "canonical_attempts", "attempt_id", attempt.attempt_id, settled
                )
                reclaimed.append(settled)
        return reclaimed

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
            row = await conn.fetchrow(
                "SELECT attempt_id, payload, archive_key FROM canonical_attempts "
                "WHERE attempt_id = $1",
                attempt_id,
            )
            attempt = Attempt.model_validate(await self._hydrate(row)) if row is not None else None
        if attempt is None:
            raise AttemptNotFound(attempt_id)
        return attempt

    async def _payload(self, sql: str, *params: Any) -> Any | None:
        """One row's payload, from the column or from the archive behind it.

        Every caller passes SQL selecting `payload, archive_key` so the read
        path is the same whichever tier the bytes are in. That is decision 6
        made structural: a caller cannot accidentally get `None` for an
        archived record, because the only way to read a payload here already
        looks at the tombstone beside it.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql, *params)
        if row is None:
            return None
        return await self._hydrate(row)

    async def _hydrate(self, row: Any) -> Any:
        """A payload row as a Python object, reading through to the archive.

        Migration 017's CHECK constrains exactly one of `payload` and
        `archive_key` to be present, so the `else` below is unreachable while
        the constraint holds -- and is written anyway, because "neither" is the
        one state that would silently lose a record and a store should say so
        rather than return something shaped like an answer.
        """
        raw = row["payload"]
        if raw is not None:
            return decode_evidence(decode_payload(raw))
        key = row["archive_key"]
        identity = next((row[name] for name in _PAYLOAD_TABLES.values() if name in row), "?")
        if key is None:  # pragma: no cover - the CHECK constraint forbids it
            raise RunIntegrityError(
                f"canonical record {identity!r} has neither a payload nor an archive key"
            )
        if self._archive_store is None:
            raise ArchivedPayloadUnavailable(str(identity), key)
        return decode_evidence(decode_payload(await self._archive_store.get(ArchiveKey.parse(key))))


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


def _occurrence_conflict(exc: Exception, run: Run) -> DuplicateOccurrence | None:
    """The duplicate-firing this violation means, or None if it means something else.

    The occurrence claim (migration 015). Two tickers evaluating the same due
    window both reach the insert; the index refuses the second, and the caller's
    correct response is to treat that firing as already fired rather than to
    retry it or abandon the batch (#220).

    Matched on the constraint name, the way `_integrity_failure` below already
    is: asyncpg raises one class for every unique index, so another constraint
    refusing the insert means something else entirely — and reporting it as a
    duplicate firing would tell the schedule admitter to carry its cursor past a
    firing that never happened.

    The `run.provenance` check is not redundant with the name. A Run carrying no
    `(schedule_id, scheduled_for)` cannot have violated this index, so calling
    its failure a duplicate would be inventing a firing.
    """
    occurrence = occurrence_key(run.provenance)
    if occurrence is None:
        return None
    if str(getattr(exc, "constraint_name", "") or "") != OCCURRENCE_INDEX:
        return None
    return DuplicateOccurrence(*occurrence)


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
