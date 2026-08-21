from __future__ import annotations

from typing import Any

import pytest

from maistro.graph import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import (
    AttemptExecutionService,
    AttemptLifecycleReconciler,
    InMemoryRunStore,
    RunStatus,
)
from maistro.runtime import PythonExecutionRuntime


async def _completed_execution() -> tuple[InMemoryRunStore, str, object]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-1")
    project = await projects.create(
        workspace_id="ws-1",
        parent_project_id=root.project_id,
        name="Idempotence",
    )
    store = InMemoryRunStore(project_store=projects)
    graph = Graph(
        workspace_id="ws-1",
        project_id=project.project_id,
        name="One node",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = await store.create_run(graph)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())

    async def executor(_work_item: Any, _context: Any) -> str:
        return "ok"

    terminal = await service.execute(node_run.node_run_id, None, None, executor=executor)
    return store, node_run.node_run_id, terminal


@pytest.mark.asyncio
async def test_reconciling_same_completed_attempt_preserves_original_acceptance() -> None:
    store, node_run_id, terminal = await _completed_execution()
    first = await store.get_node_run(node_run_id)
    assert first is not None and first.accepted_outcome is not None

    reconciled = await AttemptLifecycleReconciler(store).reconcile(terminal)

    assert reconciled.accepted_outcome == first.accepted_outcome


@pytest.mark.asyncio
async def test_replay_backfills_pre_upgrade_completed_node_run() -> None:
    store, node_run_id, terminal = await _completed_execution()
    current = await store.get_node_run(node_run_id)
    assert current is not None and current.status is RunStatus.COMPLETED
    assert current.accepted_outcome is not None

    # Simulate a row persisted before AcceptedNodeOutcome existed. The legacy
    # row already contains the projected result and terminal lifecycle facts.
    # Reconciliation adds accepted evidence without rewriting that history.
    legacy = current.model_copy(update={"accepted_outcome": None})
    store._node_runs[node_run_id] = legacy

    reconciled = await AttemptLifecycleReconciler(store).reconcile(terminal)

    assert reconciled.status is RunStatus.COMPLETED
    assert reconciled.accepted_outcome is not None
    assert reconciled.accepted_outcome.attempt_result.attempt_id == terminal.attempt_id
    assert reconciled.finished_at == current.finished_at
