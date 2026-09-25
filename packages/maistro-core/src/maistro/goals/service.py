"""Goals read and written by a principal, through the Workspace authorization seam (#1572).

VIEW on the Goal's Workspace reads it; ADMINISTER mutates it. A Goal in a
Workspace the principal cannot view raises exactly what a missing Goal
raises, with no cause or context attached, so a denial never discloses that
the Goal exists. A member who can view but not administer gets the
authorizer's own denial, which carries their membership: they may already
see the Goal, so there is nothing left to hide.
"""

from __future__ import annotations

from maistro.goals.store import GoalStore
from maistro.goals.types import Goal, GoalNotFound, GoalRevision, GoalState
from maistro.workspaces.authorization import (
    WorkspaceAction,
    WorkspaceAuthorizationDenied,
    WorkspaceAuthorizer,
)


class GoalService:
    def __init__(self, store: GoalStore, authorizer: WorkspaceAuthorizer) -> None:
        self._store = store
        self._authorizer = authorizer

    async def create(
        self,
        principal_id: str,
        *,
        workspace_id: str,
        project_id: str,
        owner_agent_id: str,
        desired_state: str,
        success_conditions: tuple[str, ...],
        stop_conditions: tuple[str, ...],
        parent_goal_id: str | None = None,
    ) -> tuple[Goal, GoalRevision]:
        await self._authorizer.require(principal_id, workspace_id, WorkspaceAction.ADMINISTER)
        return await self._store.create(
            workspace_id=workspace_id,
            project_id=project_id,
            owner_agent_id=owner_agent_id,
            desired_state=desired_state,
            success_conditions=success_conditions,
            stop_conditions=stop_conditions,
            author_principal_id=principal_id,
            parent_goal_id=parent_goal_id,
        )

    async def get(self, principal_id: str, goal_id: str) -> Goal:
        return await self._visible(principal_id, goal_id)

    async def list_for_project(
        self, principal_id: str, workspace_id: str, project_id: str
    ) -> list[Goal]:
        await self._authorizer.require(principal_id, workspace_id, WorkspaceAction.VIEW)
        return await self._store.list_for_project(workspace_id, project_id)

    async def list_owned_by_agent(
        self, principal_id: str, workspace_id: str, agent_id: str
    ) -> list[Goal]:
        await self._authorizer.require(principal_id, workspace_id, WorkspaceAction.VIEW)
        return await self._store.list_owned_by_agent(workspace_id, agent_id)

    async def get_revision(
        self, principal_id: str, goal_id: str, revision: int
    ) -> GoalRevision | None:
        await self._visible(principal_id, goal_id)
        return await self._store.get_revision(goal_id, revision)

    async def list_revisions(self, principal_id: str, goal_id: str) -> list[GoalRevision]:
        await self._visible(principal_id, goal_id)
        return await self._store.list_revisions(goal_id)

    async def revise(
        self,
        principal_id: str,
        goal_id: str,
        *,
        expected_revision: int,
        desired_state: str,
        success_conditions: tuple[str, ...],
        stop_conditions: tuple[str, ...],
    ) -> GoalRevision:
        await self._administrable(principal_id, goal_id)
        return await self._store.revise(
            goal_id,
            expected_revision=expected_revision,
            desired_state=desired_state,
            success_conditions=success_conditions,
            stop_conditions=stop_conditions,
            author_principal_id=principal_id,
        )

    async def transition(
        self,
        principal_id: str,
        goal_id: str,
        *,
        expected_state: GoalState,
        expected_revision: int,
        to_state: GoalState,
    ) -> Goal:
        await self._administrable(principal_id, goal_id)
        return await self._store.transition(
            goal_id,
            expected_state=expected_state,
            expected_revision=expected_revision,
            to_state=to_state,
        )

    async def reassign_owner(
        self,
        principal_id: str,
        goal_id: str,
        *,
        expected_revision: int,
        owner_agent_id: str,
    ) -> GoalRevision:
        await self._administrable(principal_id, goal_id)
        return await self._store.reassign_owner(
            goal_id,
            expected_revision=expected_revision,
            owner_agent_id=owner_agent_id,
            author_principal_id=principal_id,
        )

    async def _visible(self, principal_id: str, goal_id: str) -> Goal:
        goal = await self._store.get(goal_id)
        allowed = goal is not None and await self._may(principal_id, goal.workspace_id)
        if goal is None or not allowed:
            # Raised here, outside any except block, so no __context__ tells a
            # foreign Goal apart from a missing one.
            raise GoalNotFound(goal_id)
        return goal

    async def _may(self, principal_id: str, workspace_id: str) -> bool:
        try:
            await self._authorizer.require(principal_id, workspace_id, WorkspaceAction.VIEW)
        except WorkspaceAuthorizationDenied:
            return False
        return True

    async def _administrable(self, principal_id: str, goal_id: str) -> Goal:
        goal = await self._visible(principal_id, goal_id)
        await self._authorizer.require(principal_id, goal.workspace_id, WorkspaceAction.ADMINISTER)
        return goal


__all__ = ["GoalService"]
