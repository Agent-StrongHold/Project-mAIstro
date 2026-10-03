"""Principal-scoped access to the canonical Goal store (#1150, #1572).

`GoalStore` answers whoever holds a `workspace_id`. This is the product
authorization seam: a principal may read a Goal only as a member of its
Workspace (`WorkspaceAction.VIEW`), and may create, revise, transition or
reassign one only as a Workspace administrator (`WorkspaceAction.ADMINISTER`).
Mirrors `runs.scoped_reads.ScopedRunReader`, the same seam #1152 built for Runs.

Every refusal is one `GoalNotVisible` -- missing, foreign, or unauthorized --
so no answer confirms a Goal exists before the principal is admitted to look.
"""

from __future__ import annotations

from contextlib import suppress

from maistro.goals.store import GoalStore
from maistro.goals.types import Goal, GoalRevision, GoalState
from maistro.workspaces.authorization import (
    WorkspaceAction,
    WorkspaceAuthorizationDenied,
    WorkspaceAuthorizer,
)
from maistro.workspaces.store import WorkspaceStore


class GoalNotVisible(LookupError):
    """The Goal does not exist for this principal: missing, foreign, or denied."""

    def __init__(self) -> None:
        super().__init__("Goal not found")


class GoalService:
    def __init__(self, goal_store: GoalStore, workspace_store: WorkspaceStore) -> None:
        self.goal_store = goal_store
        self.workspace_store = workspace_store
        self._authorizer = WorkspaceAuthorizer(workspace_store)

    async def _require(self, principal_id: str, workspace_id: str, action: WorkspaceAction) -> None:
        # Raised outside the suppressed lookup, like `ScopedRunReader._admits`:
        # a denial here and a missing Goal below it must be the same shape, or
        # the exception chain itself would be the leak #1150 forbids.
        membership = None
        with suppress(WorkspaceAuthorizationDenied):
            membership = await self._authorizer.require(principal_id, workspace_id, action)
        if membership is None:
            raise GoalNotVisible

    async def get(self, workspace_id: str, goal_id: str, *, principal_id: str) -> Goal:
        await self._require(principal_id, workspace_id, WorkspaceAction.VIEW)
        goal = await self.goal_store.get(workspace_id, goal_id)
        if goal is None:
            raise GoalNotVisible
        return goal

    async def create(self, goal: Goal, revision: GoalRevision, *, principal_id: str) -> Goal:
        await self._require(principal_id, goal.workspace_id, WorkspaceAction.ADMINISTER)
        return await self.goal_store.create(goal, revision)

    async def revise(
        self,
        workspace_id: str,
        goal_id: str,
        *,
        expected_revision: int,
        revision: GoalRevision,
        principal_id: str,
    ) -> Goal:
        await self._require(principal_id, workspace_id, WorkspaceAction.ADMINISTER)
        return await self.goal_store.revise(
            workspace_id, goal_id, expected_revision=expected_revision, revision=revision
        )

    async def transition(
        self,
        workspace_id: str,
        goal_id: str,
        *,
        expected_state: GoalState,
        state: GoalState,
        principal_id: str,
    ) -> Goal:
        await self._require(principal_id, workspace_id, WorkspaceAction.ADMINISTER)
        return await self.goal_store.transition(
            workspace_id, goal_id, expected_state=expected_state, state=state
        )

    async def reassign(
        self,
        workspace_id: str,
        goal_id: str,
        *,
        expected_agent_id: str,
        owner_agent_id: str,
        principal_id: str,
    ) -> Goal:
        await self._require(principal_id, workspace_id, WorkspaceAction.ADMINISTER)
        return await self.goal_store.reassign(
            workspace_id,
            goal_id,
            expected_agent_id=expected_agent_id,
            owner_agent_id=owner_agent_id,
        )

    async def revisions(
        self, workspace_id: str, goal_id: str, *, principal_id: str
    ) -> list[GoalRevision]:
        await self._require(principal_id, workspace_id, WorkspaceAction.VIEW)
        await self.get(workspace_id, goal_id, principal_id=principal_id)
        return await self.goal_store.revisions(workspace_id, goal_id)

    async def revision(
        self, workspace_id: str, goal_id: str, goal_revision: int, *, principal_id: str
    ) -> GoalRevision:
        await self.get(workspace_id, goal_id, principal_id=principal_id)
        found = await self.goal_store.revision(workspace_id, goal_id, goal_revision)
        if found is None:
            raise GoalNotVisible
        return found

    async def active_for_agent(
        self, workspace_id: str, agent_id: str, *, principal_id: str
    ) -> list[Goal]:
        await self._require(principal_id, workspace_id, WorkspaceAction.VIEW)
        return await self.goal_store.active_for_agent(workspace_id, agent_id)

    async def children(self, workspace_id: str, goal_id: str, *, principal_id: str) -> list[Goal]:
        await self.get(workspace_id, goal_id, principal_id=principal_id)
        return await self.goal_store.children(workspace_id, goal_id)


__all__ = ["GoalNotVisible", "GoalService"]
