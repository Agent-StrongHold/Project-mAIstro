from __future__ import annotations

from pathlib import Path
from typing import Any

import aiosqlite
import pytest

from maistro.graph import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import (
    ActiveAttemptExists,
    AttemptExecutionService,
    AttemptStatus,
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
