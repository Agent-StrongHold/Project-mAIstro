"""GoalService: Goals read and written through the Workspace authorization seam (#1572).

Built by `create_container()` on the backend each URL selects, so the service
tested here is the one production composes rather than a test-only assembly.
"""

from __future__ import annotations

import os

import pytest

from maistro.container import Container, create_container
from maistro.goals import GoalNotFound, GoalService, GoalState, GoalStore
from maistro.persistence import close_pool
from maistro.testing.postgres import postgres_dsn
from maistro.types import AgentConfig
from maistro.workspaces import WorkspaceAuthorizationDenied, WorkspaceAuthorizer, WorkspaceRole

_EXPECTED_STORE = {
    "memory": "InMemoryGoalStore",
    "sqlite": "SqliteGoalStore",
    "postgres": "PgGoalStore",
}


@pytest.fixture(params=sorted(_EXPECTED_STORE))
async def container(request, tmp_path):
    if request.param == "memory":
        url = "memory://"
    elif request.param == "sqlite":
        pytest.importorskip("aiosqlite")
        url = f"sqlite:///{tmp_path / 'goals.sqlite3'}"
    else:
        url = postgres_dsn()
        if not url:
            if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
                raise RuntimeError(
                    "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_PG_DSN is empty"
                )
            pytest.skip("set MAISTRO_TEST_PG_DSN to a migrated PostgreSQL database")
        await close_pool()
    made = await create_container(AgentConfig(router_api_key="test-key", database_url=url))
    try:
        assert type(made.goal_store).__name__ == _EXPECTED_STORE[request.param]
        yield made
    finally:
        await made.aclose()
        await close_pool()


def _service(container: Container) -> GoalService:
    """How a principal-carrying caller composes the service from the shipped Container."""
    return GoalService(container.goal_store, WorkspaceAuthorizer(container.workspace_store))


async def _workspace(container: Container, owner: str):
    workspace = await container.workspace_store.create(creator_user_id=owner, name=owner)
    root = await container.project_scope_store.root_for_workspace(workspace.workspace_id)
    return workspace, root


async def _goal(service: GoalService, principal: str, root, **overrides):
    kwargs = {
        "workspace_id": root.workspace_id,
        "project_id": root.project_id,
        "owner_agent_id": "agent-1",
        "desired_state": "done",
        "success_conditions": ("ok",),
        "stop_conditions": (),
    }
    kwargs.update(overrides)
    return await service.create(principal, **kwargs)


async def test_container_exposes_a_working_goal_store_and_service(container) -> None:
    assert isinstance(container.goal_store, GoalStore)
    _, root = await _workspace(container, "alice")

    goal, revision = await _goal(_service(container), "alice", root)

    assert await container.goal_store.get(goal.goal_id) == goal
    assert revision.author_principal_id == "alice"
    assert await _service(container).get("alice", goal.goal_id) == goal


async def test_foreign_goal_is_indistinguishable_from_a_missing_one(container) -> None:
    service = _service(container)
    _, alice_root = await _workspace(container, "alice")
    await _workspace(container, "bob")
    goal, _ = await _goal(service, "alice", alice_root)

    with pytest.raises(GoalNotFound) as foreign:
        await service.get("bob", goal.goal_id)
    with pytest.raises(GoalNotFound) as missing:
        await service.get("bob", "no-such-goal")

    assert type(foreign.value) is type(missing.value)
    assert foreign.value.args == (goal.goal_id,)
    assert missing.value.args == ("no-such-goal",)
    assert foreign.value.__cause__ is None and foreign.value.__context__ is None
    assert missing.value.__cause__ is None and missing.value.__context__ is None
    for attempt in (
        service.list_revisions("bob", goal.goal_id),
        service.get_revision("bob", goal.goal_id, 1),
        service.revise(
            "bob",
            goal.goal_id,
            expected_revision=1,
            desired_state="x",
            success_conditions=(),
            stop_conditions=(),
        ),
        service.transition(
            "bob",
            goal.goal_id,
            expected_state=GoalState.ACTIVE,
            expected_revision=1,
            to_state=GoalState.CANCELLED,
        ),
        service.reassign_owner("bob", goal.goal_id, expected_revision=1, owner_agent_id="a2"),
    ):
        with pytest.raises(GoalNotFound):
            await attempt
    current = await container.goal_store.get(goal.goal_id)
    assert current == goal


async def test_foreign_workspace_listing_and_creation_are_refused(container) -> None:
    service = _service(container)
    _, alice_root = await _workspace(container, "alice")
    await _workspace(container, "bob")
    await _goal(service, "alice", alice_root)

    with pytest.raises(WorkspaceAuthorizationDenied):
        await service.list_for_project("bob", alice_root.workspace_id, alice_root.project_id)
    with pytest.raises(WorkspaceAuthorizationDenied):
        await service.list_owned_by_agent("bob", alice_root.workspace_id, "agent-1")
    with pytest.raises(WorkspaceAuthorizationDenied):
        await _goal(service, "bob", alice_root)


async def test_a_member_can_read_but_not_mutate(container) -> None:
    service = _service(container)
    workspace, root = await _workspace(container, "alice")
    await container.workspace_store.set_membership(
        workspace.workspace_id, user_id="carol", role=WorkspaceRole.CONTRIBUTOR
    )
    goal, first = await _goal(service, "alice", root)

    assert await service.get("carol", goal.goal_id) == goal
    assert await service.list_revisions("carol", goal.goal_id) == [first]
    assert await service.get_revision("carol", goal.goal_id, 1) == first
    assert [
        g.goal_id
        for g in await service.list_for_project("carol", root.workspace_id, root.project_id)
    ] == [goal.goal_id]
    assert [
        g.goal_id for g in await service.list_owned_by_agent("carol", root.workspace_id, "agent-1")
    ] == [goal.goal_id]

    for attempt in (
        _goal(service, "carol", root),
        service.revise(
            "carol",
            goal.goal_id,
            expected_revision=1,
            desired_state="x",
            success_conditions=(),
            stop_conditions=(),
        ),
        service.transition(
            "carol",
            goal.goal_id,
            expected_state=GoalState.ACTIVE,
            expected_revision=1,
            to_state=GoalState.CANCELLED,
        ),
        service.reassign_owner("carol", goal.goal_id, expected_revision=1, owner_agent_id="a2"),
    ):
        with pytest.raises(WorkspaceAuthorizationDenied) as denied:
            await attempt
        assert denied.value.membership is not None
    assert await container.goal_store.get(goal.goal_id) == goal


async def test_an_administrator_mutates_with_their_identity_recorded(container) -> None:
    service = _service(container)
    _, root = await _workspace(container, "alice")
    goal, _ = await _goal(service, "alice", root)

    second = await service.revise(
        "alice",
        goal.goal_id,
        expected_revision=1,
        desired_state="done twice",
        success_conditions=(),
        stop_conditions=(),
    )
    third = await service.reassign_owner(
        "alice", goal.goal_id, expected_revision=2, owner_agent_id="agent-2"
    )
    finished = await service.transition(
        "alice",
        goal.goal_id,
        expected_state=GoalState.ACTIVE,
        expected_revision=3,
        to_state=GoalState.SATISFIED,
    )

    assert second.author_principal_id == "alice"
    assert third.owner_agent_id == "agent-2"
    assert finished.state is GoalState.SATISFIED
    assert finished.owner_agent_id == "agent-2"
