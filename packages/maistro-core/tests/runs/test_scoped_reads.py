"""ScopedRunReader: Workspace-membership-scoped canonical Run reads (#1152).

Two principals, two Workspaces, a Run in each with a NodeRun and an Attempt.
A member reads the Run tree whoever initiated it; everyone else, and every
missing or mismatched id, gets one `RunNotVisible`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import aiosqlite
import pytest

from maistro.graph import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore, ProjectScopeStore
from maistro.runs.model import Attempt, NodeRun, Run
from maistro.runs.scoped_reads import RunNotVisible, ScopedRunReader
from maistro.runs.store import InMemoryRunStore, RunStore
from maistro.workspaces import InMemoryWorkspaceStore, WorkspaceRole


@pytest.fixture(params=["memory", "sqlite"])
async def stores(request: pytest.FixtureRequest) -> Any:
    if request.param == "memory":
        projects = InMemoryProjectScopeStore()
        yield (
            InMemoryRunStore(project_store=projects),
            InMemoryWorkspaceStore(project_store=projects),
            projects,
        )
        return

    from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore
    from maistro.runs.sqlite_store import SqliteRunStore
    from maistro.workspaces.sqlite_store import SqliteWorkspaceStore

    conn = await aiosqlite.connect(":memory:")
    try:
        sqlite_projects = SqliteProjectScopeStore(conn)
        await sqlite_projects.ensure_schema()
        workspaces = SqliteWorkspaceStore(conn, project_store=sqlite_projects)
        await workspaces.ensure_schema()
        runs = SqliteRunStore(conn, project_store=sqlite_projects)
        await runs.ensure_schema()
        yield runs, workspaces, sqlite_projects
    finally:
        await conn.close()


@dataclass
class _Tree:
    run: Run
    node_run: NodeRun
    attempt: Attempt


@dataclass
class _World:
    reader: ScopedRunReader
    runs: RunStore
    a: _Tree
    b: _Tree


async def _tree(
    runs: RunStore, projects: ProjectScopeStore, workspace_id: str, actor: str
) -> _Tree:
    root = await projects.root_for_workspace(workspace_id)
    project = await projects.create(
        workspace_id=workspace_id, parent_project_id=root.project_id, name="Work"
    )
    graph = Graph(
        workspace_id=workspace_id,
        project_id=project.project_id,
        name="scoped",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = await runs.create_run(graph, actor_principal_id=actor)
    node_run = await runs.create_node_run(run.run_id, node_id="node-1")
    attempt = await runs.create_attempt(node_run.node_run_id)
    return _Tree(run, node_run, attempt)


@pytest.fixture
async def world(stores: Any) -> _World:
    runs, workspaces, projects = stores
    ws_a = await workspaces.create(creator_user_id="alice", name="A")
    ws_b = await workspaces.create(creator_user_id="bob", name="B")
    await workspaces.set_membership(ws_a.workspace_id, user_id="carol", role=WorkspaceRole.MEMBER)
    return _World(
        reader=ScopedRunReader(runs, workspaces, projects),
        runs=runs,
        a=await _tree(runs, projects, ws_a.workspace_id, "alice"),
        b=await _tree(runs, projects, ws_b.workspace_id, "bob"),
    )


@pytest.mark.parametrize("reader", ["alice", "carol"])
async def test_a_member_reads_the_whole_run_tree_whoever_initiated_it(
    world: _World, reader: str
) -> None:
    a = world.a
    got = world.reader

    assert (await got.get_run(a.run.run_id, principal_id=reader)).run_id == a.run.run_id
    assert [n.node_run_id for n in await got.list_node_runs(a.run.run_id, principal_id=reader)] == [
        a.node_run.node_run_id
    ]
    node_run = await got.get_node_run(a.run.run_id, a.node_run.node_run_id, principal_id=reader)
    assert node_run.node_run_id == a.node_run.node_run_id
    attempt = await got.get_attempt(a.run.run_id, a.attempt.attempt_id, principal_id=reader)
    assert attempt.attempt_id == a.attempt.attempt_id
    attempts = await got.list_attempts(a.run.run_id, a.node_run.node_run_id, principal_id=reader)
    assert [item.attempt_id for item in attempts] == [a.attempt.attempt_id]


async def _denials(reader: ScopedRunReader, tree: _Tree, principal: str) -> list[RunNotVisible]:
    run_id = tree.run.run_id
    calls = [
        reader.get_run(run_id, principal_id=principal),
        reader.list_node_runs(run_id, principal_id=principal),
        reader.get_node_run(run_id, tree.node_run.node_run_id, principal_id=principal),
        reader.get_attempt(run_id, tree.attempt.attempt_id, principal_id=principal),
        reader.list_attempts(run_id, tree.node_run.node_run_id, principal_id=principal),
    ]
    denied = []
    for call in calls:
        with pytest.raises(RunNotVisible) as caught:
            await call
        denied.append(caught.value)
    return denied


def _shape(error: RunNotVisible) -> tuple[type, str, bool]:
    return type(error), str(error), error.__context__ is None and error.__cause__ is None


async def test_a_non_member_is_denied_every_read_like_a_missing_id(world: _World) -> None:
    foreign = await _denials(world.reader, world.b, "alice")
    missing_tree = _Tree(
        world.a.run.model_copy(update={"run_id": "missing-run"}),
        world.a.node_run.model_copy(update={"node_run_id": "missing-node-run"}),
        world.a.attempt.model_copy(update={"attempt_id": "missing-attempt"}),
    )
    missing = await _denials(world.reader, missing_tree, "bob")

    assert [_shape(error) for error in foreign] == [_shape(error) for error in missing]
    assert {_shape(error) for error in foreign} == {(RunNotVisible, "Run not found", True)}


@pytest.mark.parametrize("principal", ["", "   "])
async def test_a_blank_principal_is_denied(world: _World, principal: str) -> None:
    await _denials(world.reader, world.a, principal)


async def test_child_ids_from_another_run_are_denied_under_a_visible_run(world: _World) -> None:
    a, b = world.a, world.b
    reader = world.reader

    with pytest.raises(RunNotVisible):
        await reader.get_node_run(a.run.run_id, b.node_run.node_run_id, principal_id="alice")
    with pytest.raises(RunNotVisible):
        await reader.get_attempt(a.run.run_id, b.attempt.attempt_id, principal_id="alice")
    with pytest.raises(RunNotVisible):
        await reader.list_attempts(a.run.run_id, b.node_run.node_run_id, principal_id="alice")
    with pytest.raises(RunNotVisible):
        await reader.get_node_run(a.run.run_id, "missing-node-run", principal_id="alice")
    with pytest.raises(RunNotVisible):
        await reader.get_attempt(a.run.run_id, "missing-attempt", principal_id="alice")


async def test_a_run_whose_project_is_not_in_its_workspace_is_denied(
    world: _World, stores: Any
) -> None:
    _runs, workspaces, _projects = stores
    elsewhere = ScopedRunReader(world.runs, workspaces, InMemoryProjectScopeStore())

    with pytest.raises(RunNotVisible):
        await elsewhere.get_run(world.a.run.run_id, principal_id="alice")


async def test_the_container_reader_scopes_the_containers_own_stores() -> None:
    from maistro.container import create_container
    from maistro.types import AgentConfig

    container = await create_container(AgentConfig(router_api_key="test-key"))
    reader = container.run_reader
    assert reader.run_store is container.run_store
    assert reader.workspace_store is container.workspace_store
    assert reader.project_store is container.project_scope_store

    workspace = await container.workspace_store.create(creator_user_id="alice", name="A")
    tree = await _tree(
        container.run_store, container.project_scope_store, workspace.workspace_id, "alice"
    )
    assert (await reader.get_run(tree.run.run_id, principal_id="alice")).run_id == tree.run.run_id
    with pytest.raises(RunNotVisible):
        await reader.get_run(tree.run.run_id, principal_id="bob")
