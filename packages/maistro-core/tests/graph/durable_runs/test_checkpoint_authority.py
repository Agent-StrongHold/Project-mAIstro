"""Recovery authority stays keyed to canonical Run identity (#729)."""

from __future__ import annotations

import pytest

from maistro.graph import Graph, Node
from maistro.graph.durable_runs import (
    CanonicalDurableRunStore,
    InMemoryGraphContinuationStore,
)
from maistro.graph.durable_runs.continuation import GraphContinuation
from maistro.graph.execution_state import GraphExecutionState
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore
from maistro.runs.model import RunStatus

pytestmark = [pytest.mark.contract("boundary")]


async def _canonical_run() -> tuple[InMemoryRunStore, str]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-checkpoint-authority")
    project = await projects.create(
        workspace_id="ws-checkpoint-authority",
        parent_project_id=root.project_id,
        name="Checkpoint authority",
    )
    graph = Graph(
        workspace_id="ws-checkpoint-authority",
        project_id=project.project_id,
        name="checkpoint authority",
        nodes=[Node(node_id="step", node_type="test.checkpoint-authority")],
    )
    run_store = InMemoryRunStore(project_store=projects)
    run = await run_store.create_run(graph, initial_status=RunStatus.QUEUED)
    return run_store, run.run_id


@pytest.mark.ac("ADR-082826-d9f5/AC-5")
async def test_task_private_checkpoint_key_cannot_restore_as_a_canonical_run() -> None:
    """Continuation evidence cannot substitute a task-private id for Run identity.

    A duplicate checkpoint store keyed by an arbitrary task/checkpoint id could
    otherwise become authoritative after restart merely because it has state.
    The canonical projection requires the same key to resolve in `RunStore`.
    """
    run_store, canonical_run_id = await _canonical_run()
    continuations = InMemoryGraphContinuationStore()
    store = CanonicalDurableRunStore(run_store, continuations)

    task_private_id = "task-private-checkpoint-1"
    await continuations.create(
        GraphContinuation(
            run_id=task_private_id,
            graph_state=GraphExecutionState(run_id=task_private_id),
        )
    )

    assert await store.get(task_private_id) is None
    assert await store.get(canonical_run_id) is None
