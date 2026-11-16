"""PG proof that the connection-owned Run insert shares the caller's transaction (#1883).

Issue #1883 asks for an internal connection-owned helper that performs, in
order, the root-admission advisory locks, the canonical_runs INSERT and the
root ceiling count on a connection the caller already holds — no pool
acquisition, no transaction of its own, no commit — with ``create_run`` calling
it inside its unchanged READ COMMITTED transaction.

Reconciliation with the landed tree: that seam already exists at this head as
:meth:`~maistro.runs.pg_store.PgRunStore.insert_prepared_run` (split out of
``create_run`` by the merged #1845 work, PR #1940), and it is the very callback
``create_run``, ``wire_execution_spine`` and
:class:`~maistro.tasks.pg_admission.PgRootAdmissionCoordinator` all share. The
issue's provisional name (``insert_run_on_connection``) and its baseline
(pre-#1940, where no split existed) predate that landing; a second name for the
one operation — or a rename rippling through the coordinator wiring — would be
exactly the duplication this file exists to refuse. These tests therefore pin
the issue's contract against the realized seam, unchanged.

The oracle is the issue's, on a real server: an outer-transaction rollback must
remove the inserted row (verified on a second, independent connection); every
lock/INSERT/count statement must flow through the one supplied connection with
no pool acquisition; and the public ``create_run`` must invoke the helper
exactly once and retain one durable Run. A refused root (ceiling full) must
leave no candidate row behind. Everything runs against a genuinely migrated
PostgreSQL with the production JSON codecs (the shared ``pg_pool`` fixture); a
skipped case is not durability proof, so the evidence run executes these nodes
with ``MAISTRO_TEST_PG_DSN`` set.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from maistro.projects.pg_scope_store import PgProjectScopeStore
from maistro.runs.admission import direct_work_graph
from maistro.runs.concurrency import RunConcurrencyExceeded, RunConcurrencyLimits
from maistro.runs.pg_store import (
    _PRINCIPAL_ADMISSION_LOCK,
    _WORKSPACE_ADMISSION_LOCK,
    PgRunStore,
    _admission_lock_key,
)

#: The explicit principal every positive case admits under. The issue's oracle
#: requires an explicitly authorized, scoped Run — never an anonymous one — so
#: the principal advisory lock and the principal ceiling are both really taken.
ACTOR = "principal-1883"

#: A registered node kind; the graph must be executable for admission to be
#: meaningful (an unexecutable Run would refuse before the seam under test).
NODE_TYPE = "llm.summarize"


class _InjectedFailure(Exception):
    """The crash the rollback test injects between insert and commit."""


class _RecordingConnection:
    """Delegates every call to the real connection, recording its statements.

    Nothing is faked: each recorded statement is handed to the genuine asyncpg
    connection the test acquired, so the server really executes it. The record
    exists only to identify *which* statements ran and that they all ran on
    this one connection — the issue's "instrument only the real connection
    boundary".
    """

    def __init__(self, conn: Any) -> None:
        self._conn = conn
        self.statements: list[tuple[str, str, tuple[Any, ...]]] = []
        # A helper-owned ``transaction()`` would only nest a savepoint inside
        # the caller's transaction: every statement still lands on this one
        # connection and the outer rollback still cleans up, so the statement
        # record alone cannot see it. The calls are therefore recorded and the
        # instrumented test asserts zero — the helper must run inside the
        # transaction the caller already holds, never one of its own.
        self.transactions: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    async def execute(self, query: str, *args: Any) -> Any:
        self.statements.append(("execute", query, args))
        return await self._conn.execute(query, *args)

    async def fetchrow(self, query: str, *args: Any) -> Any:
        self.statements.append(("fetchrow", query, args))
        return await self._conn.fetchrow(query, *args)

    def transaction(self, *args: Any, **kwargs: Any) -> Any:
        self.transactions.append((args, kwargs))
        return self._conn.transaction(*args, **kwargs)

    def is_in_transaction(self) -> bool:
        return bool(self._conn.is_in_transaction())

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


class _RecordingPool:
    """Counts pool acquisitions, delegating to the real pool.

    A helper that opened its own connection would have to come through here;
    the tests read ``acquired`` to prove it did not.
    """

    def __init__(self, pool: Any) -> None:
        self._pool = pool
        self.acquired = 0

    def acquire(self) -> Any:
        self.acquired += 1
        return self._pool.acquire()

    def release(self, conn: Any) -> Any:
        return self._pool.release(conn)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._pool, name)


async def _scoped(pg_pool: Any) -> tuple[str, str, PgProjectScopeStore]:
    """One fresh Workspace with a real Project row, the scope a Run needs."""
    workspace = f"issue-1883-{uuid4().hex}"
    projects = PgProjectScopeStore(pg_pool)
    root = await projects.create_root(workspace)
    project = await projects.create(
        workspace_id=workspace, parent_project_id=root.project_id, name="Connection-owned insert"
    )
    return workspace, project.project_id, projects


async def _run_count(pg_pool: Any, run_id: str) -> int:
    """Count one Run's rows on a second, independent connection."""
    conn: Any
    async with pg_pool.acquire() as conn:
        return int(
            await conn.fetchval("SELECT count(*) FROM canonical_runs WHERE run_id = $1", run_id)
        )


def _graph(workspace: str, project_id: str, name: str) -> Any:
    return direct_work_graph(
        workspace_id=workspace,
        project_id=project_id,
        node_type=NODE_TYPE,
        name=name,
        description=name,
    )


@pytest.mark.asyncio
async def test_outer_rollback_removes_inserted_run(pg_pool: Any) -> None:
    """An insert into the caller's open transaction dies with that transaction.

    The helper inserts a prepared root Run inside an outer transaction; an
    injected exception then unwinds it. A second, independent connection must
    find zero rows for that Run — the insert is the caller's, not the helper's
    own committed fact.
    """
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    workspace, project_id, projects = await _scoped(pg_pool)
    runs = PgRunStore(pg_pool, project_store=projects)
    run = await runs.prepare_run(
        _graph(workspace, project_id, "rolled-back"), actor_principal_id=ACTOR
    )

    conn: Any
    async with pg_pool.acquire() as conn:
        with pytest.raises(_InjectedFailure):
            async with conn.transaction():
                await runs.insert_prepared_run(conn, run)
                # The row is really there inside the caller's transaction — read
                # through the same connection, because no other can see an
                # uncommitted insert. Without this guard a helper that inserted
                # nothing at all would pass the post-rollback check vacuously.
                assert (
                    await conn.fetchval(
                        "SELECT count(*) FROM canonical_runs WHERE run_id = $1", run.run_id
                    )
                    == 1
                )
                raise _InjectedFailure("crash between insert and commit")

    assert await _run_count(pg_pool, run.run_id) == 0


@pytest.mark.asyncio
async def test_helper_counts_and_locks_on_supplied_connection(pg_pool: Any) -> None:
    """Every lock, the INSERT and the ceiling count share the one connection.

    The real connection boundary is instrumented: a recording wrapper around
    the genuine connection identifies each executed statement, and a counting
    wrapper around the real pool proves the helper opened no second one. Then,
    at a saturated ceiling, the helper refuses and the refused candidate row
    does not survive the caller's rollback.
    """
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    workspace, project_id, projects = await _scoped(pg_pool)
    recording_pool = _RecordingPool(pg_pool)
    runs = PgRunStore(recording_pool, project_store=projects)
    run = await runs.prepare_run(
        _graph(workspace, project_id, "instrumented"), actor_principal_id=ACTOR
    )

    conn: Any
    async with pg_pool.acquire() as raw_conn:
        recording = _RecordingConnection(raw_conn)
        async with raw_conn.transaction():
            await runs.insert_prepared_run(recording, run)

        kinds = [statement for statement, _, _ in recording.statements]
        sqls = [sql for _, sql, _ in recording.statements]
        args = [arguments for _, _, arguments in recording.statements]
        # Positional, not merely counted: the workspace lock, then the
        # principal lock, then the canonical INSERT, then the ceiling count —
        # exactly those, exactly there. Counting alone would stay green if a
        # regression moved the INSERT ahead of both locks or swapped the lock
        # namespaces, so each statement's index is pinned and the lock
        # arguments prove which namespace each lock actually took.
        assert kinds == ["execute", "execute", "execute", "fetchrow"]
        assert "pg_advisory_xact_lock" in sqls[0]
        assert args[0] == (_WORKSPACE_ADMISSION_LOCK, _admission_lock_key(workspace))
        assert "pg_advisory_xact_lock" in sqls[1]
        assert args[1] == (
            _PRINCIPAL_ADMISSION_LOCK,
            _admission_lock_key(run.actor_principal_id),
        )
        assert "INSERT INTO canonical_runs" in sqls[2]
        assert args[2][0] == run.run_id
        assert "COUNT(*) FILTER (WHERE workspace_id = $1)" in sqls[3]
        assert args[3] == (workspace, run.actor_principal_id)
        # ...and nowhere else: no acquisition through the pool while the
        # helper ran. (The test's own acquire above is the one this store
        # never sees; it is released before the measured window closes.)
        assert recording_pool.acquired == 0
        # ...and no transaction of its own: the helper must enter no
        # savepoint on the supplied connection — the caller's transaction is
        # the only one (see _RecordingConnection.transactions).
        assert recording.transactions == []

    assert await _run_count(pg_pool, run.run_id) == 1  # committed with the caller

    # At capacity the helper refuses — and the refusal leaves nothing behind.
    crowded = PgRunStore(
        pg_pool,
        project_store=projects,
        concurrency_limits=RunConcurrencyLimits(per_principal=1, per_workspace=1),
    )
    candidate = await crowded.prepare_run(
        _graph(workspace, project_id, "over-ceiling"), actor_principal_id=ACTOR
    )
    async with pg_pool.acquire() as conn:
        with pytest.raises(RunConcurrencyExceeded):
            async with conn.transaction():
                await crowded.insert_prepared_run(conn, candidate)
    assert await _run_count(pg_pool, candidate.run_id) == 0  # no candidate row survives
    assert await _run_count(pg_pool, run.run_id) == 1  # the slot holder is untouched


@pytest.mark.asyncio
async def test_create_run_uses_connection_helper(pg_pool: Any) -> None:
    """The public ``create_run`` path runs through the connection-owned helper.

    The helper is wrapped, not replaced: the spy counts invocations, notes that
    the call lands inside the caller's open transaction, and delegates to the
    real method. ``create_run`` must invoke it exactly once and leave exactly
    one durable Run behind.
    """
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    workspace, project_id, projects = await _scoped(pg_pool)
    runs = PgRunStore(pg_pool, project_store=projects)

    calls: list[tuple[Any, bool]] = []
    original = runs.insert_prepared_run

    async def spy(conn: Any, run: Any) -> None:
        calls.append((conn, conn.is_in_transaction()))
        await original(conn, run)

    runs.insert_prepared_run = spy
    run = await runs.create_run(_graph(workspace, project_id, "wired"), actor_principal_id=ACTOR)

    assert len(calls) == 1
    _helper_conn, inside_transaction = calls[0]
    assert inside_transaction  # the helper ran on the caller's open transaction
    assert await _run_count(pg_pool, run.run_id) == 1  # one durable Run retained
