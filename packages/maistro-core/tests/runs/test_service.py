from __future__ import annotations

from typing import Any

import pytest

from maistro.graph import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import (
    AttemptStatus,
    InMemoryRunStore,
    RunExecutionService,
    RunStatus,
)
from maistro.runtime import PythonExecutionRuntime


async def _service() -> tuple[RunExecutionService, InMemoryRunStore, Graph]:
    project_store = InMemoryProjectScopeStore()
    root = await project_store.create_root("workspace-1")
    project = await project_store.create(
        workspace_id="workspace-1",
        parent_project_id=root.project_id,
        name="Execution",
    )
    store = InMemoryRunStore(project_store=project_store)
    service = RunExecutionService(store=store, runtime=PythonExecutionRuntime())
    graph = Graph(
        graph_id="graph-1",
        workspace_id="workspace-1",
        project_id=project.project_id,
        name="Single node",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    return service, store, graph


@pytest.mark.asyncio
async def test_graph_to_run_to_node_run_to_attempt_to_runtime() -> None:
    service, store, graph = await _service()
    run = await service.create_run(graph, provenance={"entry": "test"})

    async def executor(work_item: Any, context: Any) -> dict[str, Any]:
        return {"work": work_item, "context": context}

    node_run, attempt = await service.execute_node(
        run.run_id,
        "node-1",
        "payload",
        {"run_id": run.run_id},
        executor=executor,
        executor_id="agent",
    )

    assert node_run.run_id == run.run_id
    assert node_run.node_id == "node-1"
    assert node_run.status is RunStatus.COMPLETED
    assert attempt.node_run_id == node_run.node_run_id
    assert attempt.status is AttemptStatus.COMPLETED
    assert attempt.result == {
        "work": "payload",
        "context": {"run_id": run.run_id},
    }

    stored_run = await store.get_run(run.run_id)
    assert stored_run is not None
    assert stored_run.status is RunStatus.RUNNING
    assert stored_run.graph.content_hash == graph.content_hash


@pytest.mark.asyncio
async def test_retry_reuses_node_run_and_creates_new_attempt() -> None:
    service, store, graph = await _service()
    run = await service.create_run(graph)

    async def fail(_work: Any, _context: Any) -> None:
        raise RuntimeError("transient")

    with pytest.raises(RuntimeError, match="transient"):
        await service.execute_node(
            run.run_id,
            "node-1",
            None,
            None,
            executor=fail,
        )

    node_runs = await store.list_node_runs(run.run_id)
    assert len(node_runs) == 1
    node_run = node_runs[0]
    assert node_run.status is RunStatus.WAITING

    async def succeed(_work: Any, _context: Any) -> str:
        return "ok"

    retry = await service.retry_node(
        node_run.node_run_id,
        None,
        None,
        executor=succeed,
    )

    attempts = await store.list_attempts(node_run.node_run_id)
    assert [attempt.ordinal for attempt in attempts] == [1, 2]
    assert attempts[0].status is AttemptStatus.FAILED
    assert retry.status is AttemptStatus.COMPLETED
    assert retry.node_run_id == node_run.node_run_id
