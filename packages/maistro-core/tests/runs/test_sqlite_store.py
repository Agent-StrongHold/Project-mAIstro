from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import aiosqlite
import pytest

from maistro.graph import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import (
    ActiveAttemptExists,
    Attempt,
    AttemptExecutionService,
    AttemptStatus,
    RunIntegrityError,
    RunStatus,
    SqliteRunStore,
)
from maistro.runtime import PythonExecutionRuntime


async def _project_store() -> tuple[InMemoryProjectScopeStore, str]:
    project_store = InMemoryProjectScopeStore()
    root = await project_store.create_root("workspace-1")
    project = await project_store.create(
        workspace_id="workspace-1",
        parent_project_id=root.project_id,
        name="Durable execution",
    )
    return project_store, project.project_id


def _graph(project_id: str) -> Graph:
    return Graph(
        graph_id="durable-graph",
        workspace_id="workspace-1",
        project_id=project_id,
        name="Durable graph",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )


@pytest.mark.asyncio
async def test_run_node_run_and_attempt_reload_with_identical_relationships(
    tmp_path: Path,
) -> None:
    project_store, project_id = await _project_store()
    db_path = tmp_path / "runs.db"

    first_conn = await aiosqlite.connect(db_path)
    first_store = SqliteRunStore(first_conn, project_store=project_store)
    await first_store.ensure_schema()
    run = await first_store.create_run(
        _graph(project_id),
        provenance={"source": "durability-test"},
    )
    node_run = await first_store.create_node_run(run.run_id, node_id="node-1")
    service = AttemptExecutionService(
        store=first_store,
        runtime=PythonExecutionRuntime(),
    )

    async def fail(_work: Any, _context: Any) -> None:
        raise RuntimeError("transient")

    with pytest.raises(RuntimeError, match="transient"):
        await service.execute(
            node_run.node_run_id,
            None,
            None,
            executor=fail,
            executor_id="agent",
        )

    first_attempts = await first_store.list_attempts(node_run.node_run_id)
    attempt_id = first_attempts[-1].attempt_id
    graph_hash = run.graph.content_hash
    await first_conn.close()

    second_conn = await aiosqlite.connect(db_path)
    second_store = SqliteRunStore(second_conn, project_store=project_store)
    await second_store.ensure_schema()

    reloaded_run = await second_store.get_run(run.run_id)
    reloaded_node_run = await second_store.get_node_run(node_run.node_run_id)
    reloaded_attempt = await second_store.get_attempt(attempt_id)
    reloaded_attempts = await second_store.list_attempts(node_run.node_run_id)

    assert reloaded_run is not None
    assert reloaded_run.run_id == run.run_id
    assert reloaded_run.project_id == project_id
    assert reloaded_run.graph.content_hash == graph_hash
    assert reloaded_run.provenance == {"source": "durability-test"}
    assert reloaded_run.status is RunStatus.WAITING

    assert reloaded_node_run is not None
    assert reloaded_node_run.run_id == run.run_id
    assert reloaded_node_run.node_run_id == node_run.node_run_id
    assert reloaded_node_run.status is RunStatus.WAITING

    assert reloaded_attempt is not None
    assert reloaded_attempt.node_run_id == node_run.node_run_id
    assert reloaded_attempt.status is AttemptStatus.FAILED
    assert reloaded_attempt.error == "transient"
    assert [item.attempt_id for item in reloaded_attempts] == [attempt_id]
    await second_conn.close()


@pytest.mark.asyncio
async def test_active_attempt_exclusivity_survives_store_restart(tmp_path: Path) -> None:
    project_store, project_id = await _project_store()
    db_path = tmp_path / "runs.db"

    first_conn = await aiosqlite.connect(db_path)
    first_store = SqliteRunStore(first_conn, project_store=project_store)
    await first_store.ensure_schema()
    run = await first_store.create_run(_graph(project_id))
    node_run = await first_store.create_node_run(run.run_id, node_id="node-1")
    first_attempt = await first_store.create_attempt(node_run.node_run_id)
    await first_conn.close()

    second_conn = await aiosqlite.connect(db_path)
    second_store = SqliteRunStore(second_conn, project_store=project_store)
    await second_store.ensure_schema()

    persisted = await second_store.get_attempt(first_attempt.attempt_id)
    assert persisted is not None
    assert persisted.status is AttemptStatus.CREATED
    with pytest.raises(ActiveAttemptExists):
        await second_store.create_attempt(node_run.node_run_id)
    await second_conn.close()


@pytest.mark.asyncio
async def test_parent_child_run_correlation_reloads(tmp_path: Path) -> None:
    project_store, project_id = await _project_store()
    db_path = tmp_path / "runs.db"

    first_conn = await aiosqlite.connect(db_path)
    first_store = SqliteRunStore(first_conn, project_store=project_store)
    await first_store.ensure_schema()
    graph = _graph(project_id)
    parent = await first_store.create_run(graph)
    parent_node = await first_store.create_node_run(parent.run_id, node_id="node-1")
    child = await first_store.create_run(
        graph,
        parent_run_id=parent.run_id,
        parent_node_run_id=parent_node.node_run_id,
    )
    await first_conn.close()

    second_conn = await aiosqlite.connect(db_path)
    second_store = SqliteRunStore(second_conn, project_store=project_store)
    await second_store.ensure_schema()
    reloaded = await second_store.get_run(child.run_id)

    assert reloaded is not None
    assert reloaded.parent_run_id == parent.run_id
    assert reloaded.parent_node_run_id == parent_node.node_run_id
    await second_conn.close()


# --- concurrency (#143 review) ---------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_attempt_creation_does_not_collide(tmp_path: Path) -> None:
    """One connection, several workers.

    `create_attempt` opens an explicit BEGIN IMMEDIATE. Two of those
    interleaving on one aiosqlite connection raises "cannot start a transaction
    within a transaction", and a third caller's commit lands inside somebody
    else's transaction. The task runner drives four workers against this store,
    so the store serializes its own mutations.
    """
    import asyncio

    project_store, project_id = await _project_store()
    conn = await aiosqlite.connect(tmp_path / "runs.db")
    store = SqliteRunStore(conn, project_store=project_store)
    await store.ensure_schema()

    node_run_ids = []
    for _ in range(8):
        run = await store.create_run(_graph(project_id))
        await store.transition_run(run.run_id, RunStatus.QUEUED)
        await store.transition_run(run.run_id, RunStatus.RUNNING)
        node_run = await store.create_node_run(run.run_id, node_id="node-1")
        node_run_ids.append(node_run.node_run_id)

    attempts = await asyncio.gather(
        *(store.create_attempt(node_run_id) for node_run_id in node_run_ids)
    )

    assert len({a.attempt_id for a in attempts}) == 8
    assert all(a.ordinal == 1 for a in attempts)
    for node_run_id in node_run_ids:
        assert len(await store.list_attempts(node_run_id)) == 1


@pytest.mark.asyncio
async def test_concurrent_transitions_do_not_interleave(tmp_path: Path) -> None:
    """Each transition is a read-then-write; two must not split each other."""
    import asyncio

    project_store, project_id = await _project_store()
    conn = await aiosqlite.connect(tmp_path / "runs.db")
    store = SqliteRunStore(conn, project_store=project_store)
    await store.ensure_schema()
    runs = [await store.create_run(_graph(project_id)) for _ in range(8)]

    await asyncio.gather(*(store.transition_run(r.run_id, RunStatus.QUEUED) for r in runs))

    for run in runs:
        reloaded = await store.get_run(run.run_id)
        assert reloaded is not None
        assert reloaded.status is RunStatus.QUEUED


# --- integrity refusals ----------------------------------------------------


async def _store(tmp_path: Path) -> tuple[SqliteRunStore, str, aiosqlite.Connection]:
    project_store, project_id = await _project_store()
    conn = await aiosqlite.connect(tmp_path / "runs.db")
    store = SqliteRunStore(conn, project_store=project_store)
    await store.ensure_schema()
    return store, project_id, conn


@pytest.mark.asyncio
async def test_a_parent_node_run_without_a_parent_run_is_refused(tmp_path: Path) -> None:
    store, project_id, conn = await _store(tmp_path)

    with pytest.raises(RunIntegrityError, match="requires parent_run_id"):
        await store.create_run(_graph(project_id), parent_node_run_id="node-run-1")
    await conn.close()


@pytest.mark.asyncio
async def test_a_parent_node_run_from_another_run_is_refused(tmp_path: Path) -> None:
    """Both halves of the correlation exist; they just do not belong together.

    Accepting it would hang a child Run off a node of some *other* Run, which
    reads as real provenance and is not.
    """
    store, project_id, conn = await _store(tmp_path)
    graph = _graph(project_id)
    parent = await store.create_run(graph)
    elsewhere = await store.create_run(graph)
    node_run = await store.create_node_run(elsewhere.run_id, node_id="node-1")

    with pytest.raises(RunIntegrityError, match="does not belong to parent_run_id"):
        await store.create_run(
            graph,
            parent_run_id=parent.run_id,
            parent_node_run_id=node_run.node_run_id,
        )
    await conn.close()


@pytest.mark.asyncio
async def test_a_node_run_under_a_terminal_run_is_refused(tmp_path: Path) -> None:
    store, project_id, conn = await _store(tmp_path)
    run = await store.create_run(_graph(project_id))
    await store.transition_run(run.run_id, RunStatus.CANCELLED)

    with pytest.raises(RunIntegrityError, match="terminal Run"):
        await store.create_node_run(run.run_id, node_id="node-1")
    await conn.close()


@pytest.mark.asyncio
async def test_a_node_run_for_a_node_outside_the_snapshot_is_refused(tmp_path: Path) -> None:
    """The Graph the Run was admitted over is the whole world it may execute.

    The live Graph can gain nodes after admission; a NodeRun naming one of them
    would be work the Run never agreed to.
    """
    store, project_id, conn = await _store(tmp_path)
    run = await store.create_run(_graph(project_id))

    with pytest.raises(RunIntegrityError, match="not present in the Run Graph snapshot"):
        await store.create_node_run(run.run_id, node_id="node-added-later")
    await conn.close()


@pytest.mark.asyncio
async def test_an_accepted_outcome_for_another_node_run_is_refused(tmp_path: Path) -> None:
    project_store, project_id = await _project_store()
    conn = await aiosqlite.connect(tmp_path / "runs.db")
    store = SqliteRunStore(conn, project_store=project_store)
    await store.ensure_schema()
    graph = Graph(
        graph_id="two-node",
        workspace_id="workspace-1",
        project_id=project_id,
        name="Two nodes",
        nodes=[
            Node(node_id="node-1", node_type="agent"),
            Node(node_id="node-2", node_type="agent"),
        ],
    )
    run = await store.create_run(graph)
    executed = await store.create_node_run(run.run_id, node_id="node-1")
    other = await store.create_node_run(run.run_id, node_id="node-2")
    service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())

    async def _ok(_work: Any, _context: Any) -> dict[str, bool]:
        return {"ok": True}

    await service.execute(executed.node_run_id, None, None, executor=_ok, executor_id="agent")
    persisted = await store.get_node_run(executed.node_run_id)
    assert persisted is not None and persisted.accepted_outcome is not None

    with pytest.raises(RunIntegrityError, match="different NodeRun"):
        await store.transition_node_run(
            other.node_run_id,
            RunStatus.COMPLETED,
            accepted_outcome=persisted.accepted_outcome,
        )
    await conn.close()


@pytest.mark.asyncio
async def test_an_attempt_under_a_terminal_node_run_is_refused(tmp_path: Path) -> None:
    store, project_id, conn = await _store(tmp_path)
    run = await store.create_run(_graph(project_id))
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    await store.transition_node_run(node_run.node_run_id, RunStatus.CANCELLED)

    with pytest.raises(RunIntegrityError, match="terminal NodeRun"):
        await store.create_attempt(node_run.node_run_id)
    await conn.close()


# --- losing the write race -------------------------------------------------


class _RaceLosingConnection:
    """A connection whose Attempt INSERT is rejected the way a lost race is.

    `create_attempt` asks "is there an active Attempt?" and then writes. Those
    are two looks at the same state, so the answer can go stale in between, and
    the partial unique index — not the read — is what actually enforces one
    active Attempt per NodeRun.

    That rejection cannot be staged with a second live connection: `BEGIN
    IMMEDIATE` holds a RESERVED lock, so a competing writer is refused entry
    rather than admitted mid-transaction, and by the time it can write our
    SELECT would already have seen it. This stands in for the writer that got
    there first, and lets it commit once our rollback drops the lock — which is
    the state the recovery branch reads to tell "somebody beat me" from "the
    row will never be accepted".
    """

    def __init__(self, conn, *, error, after_rollback=None) -> None:
        self._conn = conn
        self._error = error
        self._after_rollback = after_rollback

    def __getattr__(self, name):
        return getattr(self._conn, name)

    async def execute(self, sql, parameters=()):
        if "INSERT INTO canonical_attempts" in sql:
            raise self._error
        return await self._conn.execute(sql, parameters)

    async def rollback(self) -> None:
        await self._conn.rollback()
        if self._after_rollback is not None:
            hook, self._after_rollback = self._after_rollback, None
            await hook()


async def _node_run_on(conn, project_store, project_id: str):
    store = SqliteRunStore(conn, project_store=project_store)
    await store.ensure_schema()
    run = await store.create_run(_graph(project_id))
    return store, await store.create_node_run(run.run_id, node_id="node-1")


@pytest.mark.asyncio
async def test_a_rejected_insert_with_a_winner_committed_reports_the_winner(
    tmp_path: Path,
) -> None:
    project_store, project_id = await _project_store()
    db_path = tmp_path / "runs.db"
    conn = await aiosqlite.connect(db_path)
    _setup, node_run = await _node_run_on(conn, project_store, project_id)

    async def _winner_commits() -> None:
        winner = Attempt(
            node_run_id=node_run.node_run_id,
            ordinal=1,
            runtime_id="python",
            executor_id="the-other-worker",
        )
        other = await aiosqlite.connect(db_path)
        await other.execute(
            """INSERT INTO canonical_attempts
               (attempt_id, node_run_id, ordinal, status, payload)
               VALUES (?, ?, ?, ?, ?)""",
            (
                winner.attempt_id,
                winner.node_run_id,
                winner.ordinal,
                winner.status.value,
                winner.model_dump_json(),
            ),
        )
        await other.commit()
        await other.close()

    racing = SqliteRunStore(
        _RaceLosingConnection(
            conn,
            error=sqlite3.IntegrityError(
                "UNIQUE constraint failed: index 'idx_canonical_attempts_one_active'"
            ),
            after_rollback=_winner_commits,
        ),
        project_store=project_store,
    )

    with pytest.raises(ActiveAttemptExists):
        await racing.create_attempt(node_run.node_run_id)
    assert conn.in_transaction is False
    await conn.close()


@pytest.mark.asyncio
async def test_a_rejected_insert_with_no_winner_is_an_integrity_failure(
    tmp_path: Path,
) -> None:
    """No active Attempt to point at, so the row itself is the problem.

    Reporting `ActiveAttemptExists` here would name a conflicting Attempt that
    does not exist and send a caller into a retry that can only fail again.
    """
    project_store, project_id = await _project_store()
    conn = await aiosqlite.connect(tmp_path / "runs.db")
    _setup, node_run = await _node_run_on(conn, project_store, project_id)
    racing = SqliteRunStore(
        _RaceLosingConnection(
            conn,
            error=sqlite3.IntegrityError("UNIQUE constraint failed: canonical_attempts.ordinal"),
        ),
        project_store=project_store,
    )

    with pytest.raises(RunIntegrityError, match="Attempt persistence integrity failure"):
        await racing.create_attempt(node_run.node_run_id)
    assert conn.in_transaction is False
    await conn.close()


@pytest.mark.asyncio
async def test_an_unexpected_failure_leaves_no_open_transaction(tmp_path: Path) -> None:
    """`BEGIN IMMEDIATE` is explicit, so every exit from it has to be too.

    A failure that is not an integrity violation still has to release the write
    lock: leaving the transaction open would make the *next* caller's BEGIN
    raise "cannot start a transaction within a transaction" on a connection
    that is otherwise healthy.
    """
    project_store, project_id = await _project_store()
    conn = await aiosqlite.connect(tmp_path / "runs.db")
    _setup, node_run = await _node_run_on(conn, project_store, project_id)
    racing = SqliteRunStore(
        _RaceLosingConnection(conn, error=sqlite3.OperationalError("disk I/O error")),
        project_store=project_store,
    )

    with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
        await racing.create_attempt(node_run.node_run_id)

    assert conn.in_transaction is False
    healthy = SqliteRunStore(conn, project_store=project_store)
    attempt = await healthy.create_attempt(node_run.node_run_id)
    assert attempt.ordinal == 1
    await conn.close()


# --- deletion (#131) -------------------------------------------------------
#
# Retention needs a way to forget, and this schema grants no cascade: the three
# tables are joined by ON DELETE RESTRICT, so a delete that only removed the Run
# would either fail or orphan its children depending on how the FK is enforced.


async def _durable_store(tmp_path: Path) -> tuple[SqliteRunStore, str]:
    project_store, project_id = await _project_store()
    conn = await aiosqlite.connect(tmp_path / "runs.db")
    store = SqliteRunStore(conn, project_store=project_store)
    await store.ensure_schema()
    return store, project_id


@pytest.mark.asyncio
async def test_delete_run_removes_its_node_runs_and_attempts(tmp_path: Path) -> None:
    store, project_id = await _durable_store(tmp_path)
    run = await store.create_run(_graph(project_id))
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    attempt = await store.create_attempt(node_run.node_run_id)
    await store.transition_attempt(attempt.attempt_id, AttemptStatus.CANCELLED)
    await store.transition_run(run.run_id, RunStatus.CANCELLED)

    assert await store.delete_run(run.run_id) is True

    assert await store.get_run(run.run_id) is None
    assert await store.get_node_run(node_run.node_run_id) is None
    assert await store.get_attempt(attempt.attempt_id) is None


@pytest.mark.asyncio
async def test_delete_run_refuses_a_live_run(tmp_path: Path) -> None:
    store, project_id = await _durable_store(tmp_path)
    run = await store.create_run(_graph(project_id))
    await store.transition_run(run.run_id, RunStatus.QUEUED)

    with pytest.raises(RunIntegrityError):
        await store.delete_run(run.run_id)

    assert await store.get_run(run.run_id) is not None


@pytest.mark.asyncio
async def test_delete_run_for_an_unknown_run_is_false(tmp_path: Path) -> None:
    store, _project_id = await _durable_store(tmp_path)

    assert await store.delete_run("no-such-run") is False
