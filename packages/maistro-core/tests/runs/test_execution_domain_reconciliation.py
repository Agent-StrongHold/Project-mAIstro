from __future__ import annotations

from typing import Any

import pytest

from maistro.graph import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import AttemptExecutionService, AttemptStatus, InMemoryRunStore, RunStatus
from maistro.runtime import PythonExecutionRuntime


@pytest.mark.asyncio
async def test_domain_can_defer_logical_reconciliation_after_terminal_attempt() -> None:
    project_store = InMemoryProjectScopeStore()
    root = await project_store.create_root("ws-1")
    project = await project_store.create(
        workspace_id="ws-1",
        parent_project_id=root.project_id,
        name="Deferred reconciliation",
    )
    store = InMemoryRunStore(project_store=project_store)
    graph = Graph(
        workspace_id="ws-1",
        project_id=project.project_id,
        name="One node",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = await store.create_run(graph)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())

    async def executor(_work: Any, _context: Any) -> str:
        return "physical-result"

    terminal = await service.execute(
        node_run.node_run_id,
        None,
        None,
        executor=executor,
        reconcile_logical=False,
    )

    persisted_node_run = await store.get_node_run(node_run.node_run_id)
    persisted_run = await store.get_run(run.run_id)
    assert terminal.status is AttemptStatus.COMPLETED
    assert persisted_node_run is not None and persisted_node_run.status is RunStatus.RUNNING
    assert persisted_run is not None and persisted_run.status is RunStatus.RUNNING
