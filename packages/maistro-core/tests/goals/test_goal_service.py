"""GoalService: Workspace-membership-scoped access to the canonical Goal store (#1150, #1572).

Mirrors `test_scoped_reads.py`, the Run equivalent (#1152): two principals, two
Workspaces, a Goal in each. A member may act within their own Workspace;
everyone else, and every missing id, gets one `GoalNotVisible`.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from maistro.goals.service import GoalNotVisible, GoalService
from maistro.goals.store import InMemoryGoalStore
from maistro.goals.types import Goal, GoalRevision, GoalState
from maistro.workspaces import InMemoryWorkspaceStore, WorkspaceRole


@dataclass
class _World:
    service: GoalService
    a: Goal
    b: Goal


def _goal(*, workspace_id: str, author: str) -> tuple[Goal, GoalRevision]:
    goal = Goal(
        workspace_id=workspace_id,
        project_id="proj-1",
        owner_agent_id="workspace-agent:1",
        current_revision=1,
    )
    revision = GoalRevision(
        goal_id=goal.goal_id,
        goal_revision=1,
        desired_state="ship the thing",
        author_id=author,
    )
    return goal, revision


@pytest.fixture
async def world() -> _World:
    workspaces = InMemoryWorkspaceStore()
    store = InMemoryGoalStore()
    service = GoalService(store, workspaces)
    ws_a = await workspaces.create(creator_user_id="alice", name="A")
    ws_b = await workspaces.create(creator_user_id="bob", name="B")
    await workspaces.set_membership(ws_a.workspace_id, user_id="carol", role=WorkspaceRole.MEMBER)

    goal_a, revision_a = _goal(workspace_id=ws_a.workspace_id, author="alice")
    goal_b, revision_b = _goal(workspace_id=ws_b.workspace_id, author="bob")
    created_a = await service.create(goal_a, revision_a, principal_id="alice")
    created_b = await service.create(goal_b, revision_b, principal_id="bob")
    return _World(service=service, a=created_a, b=created_b)


@pytest.mark.parametrize("reader", ["alice", "carol"])
async def test_a_member_reads_the_goal(world: _World, reader: str) -> None:
    got = await world.service.get(world.a.workspace_id, world.a.goal_id, principal_id=reader)
    assert got.goal_id == world.a.goal_id
    revisions = await world.service.revisions(
        world.a.workspace_id, world.a.goal_id, principal_id=reader
    )
    assert [r.goal_revision for r in revisions] == [1]


async def test_a_member_cannot_administer_without_the_role(world: _World) -> None:
    with pytest.raises(GoalNotVisible):
        await world.service.transition(
            world.a.workspace_id,
            world.a.goal_id,
            expected_state=GoalState.ACTIVE,
            state=GoalState.SATISFIED,
            principal_id="carol",
        )


async def _denials(service: GoalService, goal: Goal, principal: str) -> list[GoalNotVisible]:
    calls = [
        service.get(goal.workspace_id, goal.goal_id, principal_id=principal),
        service.revisions(goal.workspace_id, goal.goal_id, principal_id=principal),
        service.children(goal.workspace_id, goal.goal_id, principal_id=principal),
        service.active_for_agent(goal.workspace_id, goal.owner_agent_id, principal_id=principal),
    ]
    denied = []
    for call in calls:
        with pytest.raises(GoalNotVisible) as caught:
            await call
        denied.append(caught.value)
    return denied


def _shape(error: GoalNotVisible) -> tuple[type, str, bool]:
    return type(error), str(error), error.__context__ is None and error.__cause__ is None


async def test_a_non_member_is_denied_like_a_missing_goal(world: _World) -> None:
    foreign = await _denials(world.service, world.b, "alice")
    missing = await _denials(
        world.service, world.a.model_copy(update={"goal_id": "missing-goal"}), "bob"
    )

    assert [_shape(error) for error in foreign] == [_shape(error) for error in missing]
    assert {_shape(error) for error in foreign} == {(GoalNotVisible, "Goal not found", True)}


@pytest.mark.parametrize("principal", ["", "   "])
async def test_a_blank_principal_is_denied(world: _World, principal: str) -> None:
    await _denials(world.service, world.a, principal)


async def test_a_member_with_no_membership_still_gets_goalnotvisible_for_a_missing_id(
    world: _World,
) -> None:
    """A member in good standing, but the id itself does not exist."""
    with pytest.raises(GoalNotVisible):
        await world.service.get(world.a.workspace_id, "missing-goal", principal_id="alice")


async def test_an_administrator_can_revise_transition_and_reassign(world: _World) -> None:
    goal = world.a
    revised = await world.service.revise(
        goal.workspace_id,
        goal.goal_id,
        expected_revision=1,
        revision=GoalRevision(
            goal_id=goal.goal_id,
            goal_revision=2,
            desired_state="ship the revised thing",
            author_id="alice",
        ),
        principal_id="alice",
    )
    assert revised.current_revision == 2

    transitioned = await world.service.transition(
        goal.workspace_id,
        goal.goal_id,
        expected_state=GoalState.ACTIVE,
        state=GoalState.SATISFIED,
        principal_id="alice",
    )
    assert transitioned.state is GoalState.SATISFIED

    other = world.b
    reassigned = await world.service.reassign(
        other.workspace_id,
        other.goal_id,
        expected_agent_id=other.owner_agent_id,
        owner_agent_id="workspace-agent:2",
        principal_id="bob",
    )
    assert reassigned.owner_agent_id == "workspace-agent:2"


async def test_revision_resolves_one_historical_revision_or_says_not_visible(
    world: _World,
) -> None:
    found = await world.service.revision(
        world.a.workspace_id, world.a.goal_id, 1, principal_id="alice"
    )
    assert found.goal_revision == 1

    with pytest.raises(GoalNotVisible):
        await world.service.revision(world.a.workspace_id, world.a.goal_id, 99, principal_id="alice")


async def test_active_for_agent_and_children_resolve_for_a_member(world: _World) -> None:
    active = await world.service.active_for_agent(
        world.a.workspace_id, world.a.owner_agent_id, principal_id="carol"
    )
    assert [g.goal_id for g in active] == [world.a.goal_id]

    children = await world.service.children(
        world.a.workspace_id, world.a.goal_id, principal_id="carol"
    )
    assert children == []
