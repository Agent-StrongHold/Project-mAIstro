"""Principal-carrying Workspace access decisions (#1150).

HTTP routes and background consumers ask the same question -- may this
principal act on this Workspace? -- so the answer lives here, not in either.
"""

from __future__ import annotations

from enum import StrEnum

from maistro.workspaces.model import WorkspaceMembership, WorkspaceNotFound
from maistro.workspaces.store import WorkspaceStore


class WorkspaceAction(StrEnum):
    VIEW = "view"
    ADMINISTER = "administer"


class WorkspaceAuthorizationDenied(LookupError):
    """The principal may not perform the action on the Workspace.

    One error for a missing Workspace, a foreign Workspace and a blank
    principal, so a denial never discloses whether the Workspace exists.
    `membership` is set only when the principal is a member who lacks the
    action, which they may already learn by viewing the Workspace.

    Deliberately not `WorkspaceAccessDenied`: that name is the store's
    last-owner refusal, which routes map to a conflict.
    """

    def __init__(self, membership: WorkspaceMembership | None = None) -> None:
        super().__init__("Workspace not found")
        self.membership = membership


class WorkspaceAuthorizer:
    def __init__(self, store: WorkspaceStore) -> None:
        self._store = store

    async def require(
        self,
        principal_id: str,
        workspace_id: str,
        action: WorkspaceAction,
    ) -> WorkspaceMembership:
        if not principal_id.strip():
            raise WorkspaceAuthorizationDenied
        try:
            membership = await self._store.get_membership(workspace_id, user_id=principal_id)
        except WorkspaceNotFound as exc:
            raise WorkspaceAuthorizationDenied from exc
        if membership is None:
            raise WorkspaceAuthorizationDenied
        if action is WorkspaceAction.ADMINISTER and not membership.can_administer:
            raise WorkspaceAuthorizationDenied(membership)
        return membership

    async def visible_workspace_ids(self, principal_id: str) -> frozenset[str]:
        if not principal_id.strip():
            return frozenset()
        workspaces = await self._store.list_for_user(principal_id)
        return frozenset(workspace.workspace_id for workspace in workspaces)


__all__ = ["WorkspaceAction", "WorkspaceAuthorizationDenied", "WorkspaceAuthorizer"]
