from __future__ import annotations

from typing import Any

import aiosqlite
import pytest

from maistro.graph import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import AttemptExecutionService, SqliteRunStore
from maistro.runtime import PythonExecutionRuntime


@pytest.mark.asyncio
async def test_sqlite_round_trips_accepted_attempt_result() -> None:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-1")
    project = await projects.create(
        workspace_id="ws-1",
        parent_project_id=root.project_id,
        name="SQLite outcome",
    )
    graph = Graph(
        workspace_id="ws-1",
        project_id=project.project_id,
        name="One node",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )

    async with aiosqlite.connect(":memory:") as conn:
        store = SqliteRunStore(conn, project_store=projects)
        await store.ensure_schema()
        run = await store.create_run(graph)
        node_run = await store.create_node_run(run.run_id, node_id="node-1")
        service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())

        async def executor(_work_item: Any, _context: Any) -> dict[str, bool]:
            return {"ok": True}

        terminal = await service.execute(node_run.node_run_id, None, None, executor=executor)
        persisted = await store.get_node_run(node_run.node_run_id)

        assert persisted is not None and persisted.accepted_outcome is not None
        assert persisted.accepted_outcome.attempt_result.attempt_id == terminal.attempt_id
        assert persisted.result == {"ok": True}
