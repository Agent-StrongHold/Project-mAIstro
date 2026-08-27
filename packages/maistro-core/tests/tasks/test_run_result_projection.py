"""Task success keeps physical evidence and product Run results distinct (#237)."""

from __future__ import annotations

from maistro.agents.types import CodeOutput, ConductorOutput
from maistro.graph import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.store import InMemoryRunStore
from maistro.tasks.execution import TaskAttemptExecutor
from maistro.tasks.models import TaskCreate


async def test_task_success_projects_product_result_without_rewriting_attempt_evidence() -> None:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("workspace-1")
    store = InMemoryRunStore(project_store=projects)
    graph = Graph(
        workspace_id="workspace-1",
        project_id=root.project_id,
        name="Task",
        nodes=[Node(node_id="task-node", node_type="agent")],
    )
    run = await store.create_run(graph)
    output = ConductorOutput(
        success=True,
        final_answer="done",
        code=CodeOutput(description="generated", files_changed=["a.py"]),
    )

    async def executor(_request: TaskCreate) -> ConductorOutput:
        return output

    returned = await TaskAttemptExecutor(store).execute(
        run.run_id,
        TaskCreate(description="Change a.py"),
        executor,
    )

    node_run = (await store.list_node_runs(run.run_id))[0]
    attempt = (await store.list_attempts(node_run.node_run_id))[0]
    settled = await store.get_run(run.run_id)

    assert returned is output
    assert attempt.status is AttemptStatus.COMPLETED
    assert attempt.result == {
        "success": True,
        "final_answer": "done",
        "files_changed": ["a.py"],
    }
    assert node_run.status is RunStatus.COMPLETED
    assert node_run.result == {"files_changed": ["a.py"]}
    assert settled is not None
    assert settled.status is RunStatus.COMPLETED
    assert settled.result == {"files_changed": ["a.py"]}
