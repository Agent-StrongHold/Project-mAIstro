from __future__ import annotations

import pytest

from maistro.graph import Graph, Node
from maistro.projects.scope import ProjectMembership
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import RunAccessContext, RunAuthorization, RunStatus
from maistro.runs.store import InMemoryRunStore
from maistro.security.sentinel.authz_types import Principal


async def _project(projects: InMemoryProjectScopeStore, workspace_id: str, name: str):
    try:
        root = await projects.root_for_workspace(workspace_id)
    except KeyError:
        root = await projects.create_root(workspace_id)
    return await projects.create(
        workspace_id=workspace_id,
        parent_project_id=root.project_id,
        name=name,
    )


def _graph(workspace_id: str, project_id: str) -> Graph:
    return Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name="inspection",
        nodes=[Node(node_id="node", node_type="agent")],
    )


async def _grant_read(
    projects: InMemoryProjectScopeStore, *, workspace_id: str, project_id: str, principal_id: str
) -> None:
    await projects.set_membership(
        ProjectMembership(
            workspace_id=workspace_id,
            project_id=project_id,
            principal_id=principal_id,
            grants={"runs:read"},
        )
    )


@pytest.mark.asyncio
async def test_scoped_reads_hide_foreign_run_children_and_attempt_lists() -> None:
    projects = InMemoryProjectScopeStore()
    first = await _project(projects, "workspace-a", "first")
    second = await _project(projects, "workspace-b", "second")
    await _grant_read(
        projects, workspace_id="workspace-a", project_id=first.project_id, principal_id="alice"
    )
    await _grant_read(
        projects, workspace_id="workspace-b", project_id=second.project_id, principal_id="bob"
    )
    store = InMemoryRunStore(project_store=projects)

    mine = await store.create_run(_graph(first.workspace_id, first.project_id))
    foreign = await store.create_run(_graph(second.workspace_id, second.project_id))
    node = await store.create_node_run(foreign.run_id, node_id="node")
    attempt = await store.create_attempt(node.node_run_id)

    alice = store.scoped(
        RunAccessContext(
            workspace_id=first.workspace_id,
            project_id=first.project_id,
            principal=Principal(id="alice", kind="human"),
        )
    )
    assert await alice.get_run(mine.run_id) == mine
    assert await alice.get_run(foreign.run_id) is None
    assert await alice.get_node_run(node.node_run_id) is None
    assert await alice.get_attempt(attempt.attempt_id) is None
    assert await alice.list_node_runs(foreign.run_id) == []
    assert await alice.list_attempts(node.node_run_id) == []


@pytest.mark.asyncio
async def test_scoped_list_by_status_is_project_and_principal_bound() -> None:
    projects = InMemoryProjectScopeStore()
    first = await _project(projects, "workspace-a", "first")
    second = await _project(projects, "workspace-a", "second")
    await _grant_read(
        projects, workspace_id="workspace-a", project_id=first.project_id, principal_id="alice"
    )
    await _grant_read(
        projects, workspace_id="workspace-a", project_id=second.project_id, principal_id="bob"
    )
    store = InMemoryRunStore(project_store=projects)
    mine = await store.create_run(_graph("workspace-a", first.project_id))
    await store.create_run(_graph("workspace-a", second.project_id))

    alice = store.scoped(
        RunAccessContext("workspace-a", first.project_id, Principal("alice", "human"))
    )
    assert [run.run_id for run in await alice.list_by_status(RunStatus.CREATED)] == [mine.run_id]

    no_membership = store.scoped(
        RunAccessContext("workspace-a", first.project_id, Principal("carol", "human"))
    )
    assert await no_membership.get_run(mine.run_id) is None
    assert await no_membership.list_by_status(RunStatus.CREATED) == []


@pytest.mark.asyncio
async def test_admission_binds_accounting_to_authenticated_and_acting_principals() -> None:
    projects = InMemoryProjectScopeStore()
    project = await _project(projects, "workspace-a", "first")
    store = InMemoryRunStore(project_store=projects)
    authorization = RunAuthorization(
        workspace_id=project.workspace_id,
        project_id=project.project_id,
        authenticated_principal=Principal(id="operator", kind="human"),
        acting_principal=Principal(id="agent", kind="agent", owner="operator"),
    )

    run = await store.create_run(
        _graph(project.workspace_id, project.project_id),
        authorization=authorization,
        actor_principal_id="agent",
        provenance={"user_id": "forged-metadata"},
    )

    assert run.initiating_principal_id == "operator"
    assert run.acting_principal_id == "agent"
    assert run.actor_principal_id == "agent"
    assert run.accounting_principal_id == "agent"
    assert run.provenance["user_id"] == "forged-metadata"
    with pytest.raises(ValueError, match="does not match"):
        await store.create_run(
            _graph(project.workspace_id, project.project_id),
            authorization=authorization,
            actor_principal_id="forged",
        )


@pytest.mark.asyncio
async def test_delegation_requires_owned_acting_principal() -> None:
    projects = InMemoryProjectScopeStore()
    project = await _project(projects, "workspace-a", "first")
    store = InMemoryRunStore(project_store=projects)

    with pytest.raises(ValueError, match="authenticated or owned"):
        await store.create_run(
            _graph(project.workspace_id, project.project_id),
            authorization=RunAuthorization(
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                authenticated_principal=Principal(id="operator", kind="human"),
                acting_principal=Principal(id="other", kind="human"),
            ),
        )
