from __future__ import annotations

import pytest

from maistro.graph import Graph, Node
from maistro.projects.scope import Project
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import (
    ActiveAttemptExists,
    AttemptStatus,
    InMemoryRunStore,
    RunIntegrityError,
    RunStatus,
)


def _graph(*, workspace_id: str, project_id: str) -> Graph:
    return Graph(
        graph_id=f"graph-{workspace_id}-{project_id}",
        workspace_id=workspace_id,
        project_id=project_id,
        name="Pipeline",
        nodes=[
            Node(node_id="first", node_type="agent"),
            Node(node_id="second", node_type="transform"),
        ],
    )


async def _project(
    project_store: InMemoryProjectScopeStore,
    *,
    workspace_id: str,
    name: str = "Project",
) -> Project:
    try:
        root = await project_store.root_for_workspace(workspace_id)
    except KeyError:
        root = await project_store.create_root(workspace_id)
    return await project_store.create(
        workspace_id=workspace_id,
        parent_project_id=root.project_id,
        name=name,
    )


async def _store_with_project(
    *,
    workspace_id: str = "workspace-1",
) -> tuple[InMemoryRunStore, InMemoryProjectScopeStore, Project]:
    project_store = InMemoryProjectScopeStore()
    project = await _project(project_store, workspace_id=workspace_id)
    return InMemoryRunStore(project_store=project_store), project_store, project


@pytest.mark.asyncio
async def test_run_creation_requires_existing_canonical_project() -> None:
    project_store = InMemoryProjectScopeStore()
    await project_store.create_root("workspace-1")
    store = InMemoryRunStore(project_store=project_store)

    with pytest.raises(RunIntegrityError, match="does not exist"):
        await store.create_run(_graph(workspace_id="workspace-1", project_id="missing"))


@pytest.mark.asyncio
async def test_run_creation_rejects_project_from_different_workspace() -> None:
    store, _, project = await _store_with_project(workspace_id="workspace-1")

    with pytest.raises(RunIntegrityError, match="does not belong"):
        await store.create_run(
            _graph(workspace_id="workspace-2", project_id=project.project_id),
        )


@pytest.mark.asyncio
async def test_retry_creates_new_attempt_under_same_node_run_and_run() -> None:
    store, _, project = await _store_with_project()
    run = await store.create_run(
        _graph(workspace_id=project.workspace_id, project_id=project.project_id),
    )
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)

    node_run = await store.create_node_run(run.run_id, node_id="first")
    await store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
    await store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)

    first = await store.create_attempt(node_run.node_run_id, executor_id="agent")
    await store.transition_attempt(first.attempt_id, AttemptStatus.RUNNING)
    await store.transition_attempt(first.attempt_id, AttemptStatus.FAILED, error="transient")

    second = await store.create_attempt(node_run.node_run_id, executor_id="agent")

    assert second.node_run_id == node_run.node_run_id
    assert second.ordinal == 2
    stored = await store.get_run(run.run_id)
    assert stored is not None
    assert stored.run_id == run.run_id
    assert stored.project_id == project.project_id


@pytest.mark.asyncio
async def test_node_run_allows_repeated_execution_of_same_graph_node() -> None:
    store, _, project = await _store_with_project()
    run = await store.create_run(
        _graph(workspace_id=project.workspace_id, project_id=project.project_id),
    )

    first = await store.create_node_run(run.run_id, node_id="first")
    second = await store.create_node_run(run.run_id, node_id="first")

    assert first.node_run_id != second.node_run_id
    assert first.node_id == second.node_id == "first"
    assert (first.ordinal, second.ordinal) == (1, 2)


@pytest.mark.asyncio
async def test_node_run_must_reference_node_in_captured_graph() -> None:
    store, _, project = await _store_with_project()
    run = await store.create_run(
        _graph(workspace_id=project.workspace_id, project_id=project.project_id),
    )

    with pytest.raises(RunIntegrityError, match="not present"):
        await store.create_node_run(run.run_id, node_id="missing")


@pytest.mark.asyncio
async def test_only_one_active_attempt_per_node_run() -> None:
    store, _, project = await _store_with_project()
    run = await store.create_run(
        _graph(workspace_id=project.workspace_id, project_id=project.project_id),
    )
    node_run = await store.create_node_run(run.run_id, node_id="first")
    await store.create_attempt(node_run.node_run_id)

    with pytest.raises(ActiveAttemptExists):
        await store.create_attempt(node_run.node_run_id)


@pytest.mark.asyncio
async def test_child_run_same_project_keeps_parent_correlation() -> None:
    store, _, project = await _store_with_project()
    graph = _graph(workspace_id=project.workspace_id, project_id=project.project_id)
    parent = await store.create_run(graph)
    parent_node = await store.create_node_run(parent.run_id, node_id="first")

    child = await store.create_run(
        graph,
        parent_run_id=parent.run_id,
        parent_node_run_id=parent_node.node_run_id,
    )

    assert child.parent_run_id == parent.run_id
    assert child.parent_node_run_id == parent_node.node_run_id
    assert child.project_id == parent.project_id


@pytest.mark.asyncio
async def test_child_run_cross_project_is_explicit_but_same_workspace_only() -> None:
    store, project_store, parent_project = await _store_with_project()
    publishing = await _project(
        project_store,
        workspace_id=parent_project.workspace_id,
        name="Publishing",
    )
    parent = await store.create_run(
        _graph(workspace_id=parent_project.workspace_id, project_id=parent_project.project_id),
    )

    with pytest.raises(RunIntegrityError, match="implicitly cross Project"):
        await store.create_run(
            _graph(workspace_id=publishing.workspace_id, project_id=publishing.project_id),
            parent_run_id=parent.run_id,
        )

    child = await store.create_run(
        _graph(workspace_id=publishing.workspace_id, project_id=publishing.project_id),
        parent_run_id=parent.run_id,
        allow_cross_project=True,
    )
    assert child.workspace_id == parent.workspace_id
    assert child.project_id == publishing.project_id

    other_project = await _project(project_store, workspace_id="workspace-2", name="Other")
    with pytest.raises(RunIntegrityError, match="cross Workspace"):
        await store.create_run(
            _graph(
                workspace_id=other_project.workspace_id,
                project_id=other_project.project_id,
            ),
            parent_run_id=parent.run_id,
            allow_cross_project=True,
        )


@pytest.mark.asyncio
async def test_parent_node_run_must_belong_to_declared_parent_run() -> None:
    store, _, project = await _store_with_project()
    graph = _graph(workspace_id=project.workspace_id, project_id=project.project_id)
    first_parent = await store.create_run(graph)
    second_parent = await store.create_run(graph)
    second_parent_node = await store.create_node_run(second_parent.run_id, node_id="first")

    with pytest.raises(RunIntegrityError, match="does not belong"):
        await store.create_run(
            graph,
            parent_run_id=first_parent.run_id,
            parent_node_run_id=second_parent_node.node_run_id,
        )
