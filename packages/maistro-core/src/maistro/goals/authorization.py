"""Principal-carrying Goal access through the Workspace authorization seam.

`GoalStore` answers whoever holds an id — the same raw shape `RunStore` has.
This is the seam products use: a principal may read a Goal, its revisions and
its recorded transitions when they can *view* the Goal's Workspace, and may
mutate one when they can *administer* it, both decided by the canonical
`WorkspaceAuthorizer` (`maistro.workspaces.authorization`, #1150). No second
authorization path is defined here — only the one question that seam already
answers, asked per Goal.

Every refusal is one :class:`GoalNotVisible`, raised for a missing goal, a
foreign goal, and a blank principal alike. The decision is made before any
mutation reaches the store, so a principal in another Workspace cannot read
*or* change a Goal — and cannot even learn that the id exists.
"""

from __future__ import annotations

from datetime import datetime

from maistro.goals.model import (
    Goal,
    GoalRevision,
    GoalRevisionDraft,
    GoalStatus,
    GoalTransitionRecord,
)
from maistro.goals.store import GoalStore
from maistro.workspaces.authorization import (
    WorkspaceAction,
    WorkspaceAuthorizationDenied,
    WorkspaceAuthorizer,
)
from maistro.workspaces.store import WorkspaceStore


class GoalNotVisible(LookupError):
    """The Goal does not exist for this principal — missing, foreign, or a
    blank principal id. One refusal for all three, deliberately."""

    def __init__(self) -> None:
        super().__init__("Goal not found")


class ScopedGoalStore:
    """The authorized Goal seam. Wraps one :class:`GoalStore`; every method
    carries the ``principal_id`` the decision is about."""

    def __init__(self, goal_store: GoalStore, workspace_store: WorkspaceStore) -> None:
        self.goal_store = goal_store
        self.workspace_store = workspace_store
        self._authorizer = WorkspaceAuthorizer(workspace_store)

    async def create_goal(
        self,
        *,
        principal_id: str,
        workspace_id: str,
        project_id: str,
        agent_id: str,
        draft: GoalRevisionDraft,
        parent_goal_id: str | None = None,
    ) -> Goal:
        await self._require(principal_id, workspace_id, WorkspaceAction.ADMINISTER)
        return await self.goal_store.create_goal(
            workspace_id=workspace_id,
            project_id=project_id,
            agent_id=agent_id,
            draft=draft,
            parent_goal_id=parent_goal_id,
        )

    async def get_goal(self, goal_id: str, *, principal_id: str) -> Goal:
        """The Goal when this principal may view it; :class:`GoalNotVisible`
        for a missing id, a foreign id, or a blank principal — the same
        answer for all three, so no caller learns that an id exists."""
        return await self._visible_goal(goal_id, principal_id)

    async def append_revision(
        self,
        goal_id: str,
        draft: GoalRevisionDraft,
        *,
        principal_id: str,
        expected_revision: int,
    ) -> Goal:
        await self._visible_goal(goal_id, principal_id, WorkspaceAction.ADMINISTER)
        return await self.goal_store.append_revision(
            goal_id,
            draft,
            expected_revision=expected_revision,
        )

    async def transition_goal(
        self,
        goal_id: str,
        to_status: GoalStatus,
        *,
        principal_id: str,
        expected_revision: int,
        actor: str,
        at: datetime | None = None,
    ) -> Goal:
        await self._visible_goal(goal_id, principal_id, WorkspaceAction.ADMINISTER)
        return await self.goal_store.transition_goal(
            goal_id,
            to_status,
            expected_revision=expected_revision,
            actor=actor,
            at=at,
        )

    async def reassign_agent(
        self,
        goal_id: str,
        agent_id: str,
        *,
        principal_id: str,
        expected_revision: int,
        actor: str,
        at: datetime | None = None,
    ) -> Goal:
        await self._visible_goal(goal_id, principal_id, WorkspaceAction.ADMINISTER)
        return await self.goal_store.reassign_agent(
            goal_id,
            agent_id,
            expected_revision=expected_revision,
            actor=actor,
            at=at,
        )

    async def list_goal_revisions(self, goal_id: str, *, principal_id: str) -> list[GoalRevision]:
        goal = await self._visible_goal(goal_id, principal_id)
        return await self.goal_store.list_goal_revisions(goal.goal_id)

    async def list_goal_transitions(
        self, goal_id: str, *, principal_id: str
    ) -> list[GoalTransitionRecord]:
        goal = await self._visible_goal(goal_id, principal_id)
        return await self.goal_store.list_goal_transitions(goal.goal_id)

    async def _visible_goal(
        self,
        goal_id: str,
        principal_id: str,
        action: WorkspaceAction = WorkspaceAction.VIEW,
    ) -> Goal:
        """The Goal when this principal may ``action`` it, else one refusal.

        A missing goal and a foreign goal raise the same exception with the
        same message: neither answer confirms that an id exists.
        """
        try:
            goal = await self.goal_store.get_goal(goal_id)
        except LookupError:
            raise GoalNotVisible from None
        if goal is None:
            raise GoalNotVisible
        try:
            await self._authorizer.require(principal_id, goal.workspace_id, action)
        except WorkspaceAuthorizationDenied:
            raise GoalNotVisible from None
        return goal

    async def _require(self, principal_id: str, workspace_id: str, action: WorkspaceAction) -> None:
        try:
            await self._authorizer.require(principal_id, workspace_id, action)
        except WorkspaceAuthorizationDenied:
            raise GoalNotVisible from None


__all__ = ["GoalNotVisible", "ScopedGoalStore"]
