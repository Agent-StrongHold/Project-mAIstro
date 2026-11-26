"""The scoped Goal seam accepts a caller-chosen identity (#1823).

`services.brief_commit` commits an interview as one logical pair across two
stores. To survive a crash it records the whole identity — `goal_id` included
— durably *before* its first write, then resumes the same identity after
process death. That needs `ScopedGoalStore.create_goal` to pass a caller-
chosen `goal_id` through to the store, which the raw stores already accept.
The seam is where the decision is authorized, so the passthrough lives there:
identity selection stays an application choice, never a way around the
ADMINISTER check, and every backend behind the seam behaves the same.
"""

from __future__ import annotations

import pytest

from maistro.goals import GoalNotVisible, GoalRevisionDraft, ScopedGoalStore
from maistro.workspaces.store import InMemoryWorkspaceStore

pytestmark = pytest.mark.contract("boundary")


async def _seam() -> tuple[object, ScopedGoalStore]:
    from maistro.goals.store import InMemoryGoalStore

    workspace_store = InMemoryWorkspaceStore()
    await workspace_store.create(creator_user_id="owner", name="Alpha", workspace_id="ws-1")
    store = InMemoryGoalStore()
    return store, ScopedGoalStore(store, workspace_store)


def _draft(desired: str = "the confirmed outcome") -> GoalRevisionDraft:
    return GoalRevisionDraft(desired_state=desired, author="agent-1")


async def test_the_seam_creates_the_goal_under_the_chosen_identity() -> None:
    _store, seam = await _seam()
    goal = await seam.create_goal(
        principal_id="owner",
        workspace_id="ws-1",
        project_id="prj-1",
        agent_id="agent-1",
        draft=_draft(),
        goal_id="planned-identity",
    )
    assert goal.goal_id == "planned-identity"
    assert goal.current_revision == 1
    read = await seam.get_goal("planned-identity", principal_id="owner")
    assert read.goal_id == "planned-identity"


async def test_without_an_identity_the_store_mints_one() -> None:
    _store, seam = await _seam()
    goal = await seam.create_goal(
        principal_id="owner",
        workspace_id="ws-1",
        project_id="prj-1",
        agent_id="agent-1",
        draft=_draft(),
    )
    assert goal.goal_id, "a minted identity is non-empty"


async def test_a_chosen_identity_is_no_authorization_bypass() -> None:
    _store, seam = await _seam()
    with pytest.raises(GoalNotVisible):
        await seam.create_goal(
            principal_id="stranger",
            workspace_id="ws-1",
            project_id="prj-1",
            agent_id="agent-1",
            draft=_draft(),
            goal_id="smuggled-identity",
        )
    with pytest.raises(GoalNotVisible):
        await seam.get_goal("smuggled-identity", principal_id="stranger")
