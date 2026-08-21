from __future__ import annotations

from typing import Any

import aiosqlite
import pytest

from maistro.graph import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import (
    AttemptExecutionService,
    AttemptStatus,
    InMemoryRunStore,
    RunStatus,
    SqliteRunStore,
    StaleExecutionFence,
)
from maistro.runtime import PythonExecutionRuntime


async def _scope() -> tuple[InMemoryProjectScopeStore, Graph]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-1")
    project = await projects.create(
        workspace_id="ws-1",
        parent_project_id=root.project_id,
        name="Fencing",
    )
    return projects, Graph(
        workspace_id="ws-1",
        project_id=project.project_id,
        name="One node",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )


@pytest.mark.asyncio
async def test_raw_attempt_fixture_remains_unfenced() -> None:
    projects, graph = await _scope()
    store = InMemoryRunStore(project_store=projects)
    run = await store.create_run(graph)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    attempt = await store.create_attempt(node_run.node_run_id)

    assert attempt.execution_lease is None
    running = await store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
    assert running.status is AttemptStatus.RUNNING


@pytest.mark.asyncio
async def test_leased_attempt_rejects_missing_and_wrong_fence() -> None:
    projects, graph = await _scope()
    store = InMemoryRunStore(project_store=projects)
    run = await store.create_run(graph)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    attempt = await store.create_attempt(node_run.node_run_id, lease_holder="worker-a")

    assert attempt.execution_lease is not None
    with pytest.raises(StaleExecutionFence):
        await store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
    with pytest.raises(StaleExecutionFence):
        await store.transition_attempt(
            attempt.attempt_id,
            AttemptStatus.RUNNING,
            fencing_token="wrong",
        )

    running = await store.transition_attempt(
        attempt.attempt_id,
        AttemptStatus.RUNNING,
        fencing_token=attempt.execution_lease.fencing_token,
    )
    assert running.status is AttemptStatus.RUNNING


@pytest.mark.asyncio
async def test_retry_uses_new_epoch_and_old_fence_cannot_update_new_attempt() -> None:
    projects, graph = await _scope()
    store = InMemoryRunStore(project_store=projects)
    run = await store.create_run(graph)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")

    first = await store.create_attempt(node_run.node_run_id, lease_holder="worker-a")
    assert first.execution_lease is not None
    first = await store.transition_attempt(
        first.attempt_id,
        AttemptStatus.RUNNING,
        fencing_token=first.execution_lease.fencing_token,
    )
    first = await store.transition_attempt(
        first.attempt_id,
        AttemptStatus.FAILED,
        error="lost worker",
        fencing_token=first.execution_lease.fencing_token,
    )
    assert first.status is AttemptStatus.FAILED

    second = await store.create_attempt(node_run.node_run_id, lease_holder="worker-b")
    assert second.execution_lease is not None
    assert second.execution_lease.lease_epoch == first.execution_lease.lease_epoch + 1
    assert second.execution_lease.fencing_token != first.execution_lease.fencing_token

    with pytest.raises(StaleExecutionFence):
        await store.transition_attempt(
            second.attempt_id,
            AttemptStatus.RUNNING,
            fencing_token=first.execution_lease.fencing_token,
        )


@pytest.mark.asyncio
async def test_attempt_execution_service_uses_fence_transparently() -> None:
    projects, graph = await _scope()
    store = InMemoryRunStore(project_store=projects)
    run = await store.create_run(graph)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())

    async def executor(work_item: Any, _context: Any) -> Any:
        return work_item

    terminal = await service.execute(
        node_run.node_run_id,
        "ok",
        None,
        executor=executor,
        executor_id="agent-worker",
    )

    assert terminal.status is AttemptStatus.COMPLETED
    assert terminal.execution_lease is not None
    assert terminal.execution_lease.holder == "agent-worker"
    logical = await store.get_node_run(node_run.node_run_id)
    assert logical is not None and logical.status is RunStatus.COMPLETED


@pytest.mark.asyncio
async def test_sqlite_enforces_same_fence_contract() -> None:
    projects, graph = await _scope()
    async with aiosqlite.connect(":memory:") as conn:
        store = SqliteRunStore(conn, project_store=projects)
        await store.ensure_schema()
        run = await store.create_run(graph)
        node_run = await store.create_node_run(run.run_id, node_id="node-1")
        attempt = await store.create_attempt(node_run.node_run_id, lease_holder="worker-a")
        assert attempt.execution_lease is not None

        with pytest.raises(StaleExecutionFence):
            await store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)

        running = await store.transition_attempt(
            attempt.attempt_id,
            AttemptStatus.RUNNING,
            fencing_token=attempt.execution_lease.fencing_token,
        )
        assert running.status is AttemptStatus.RUNNING
