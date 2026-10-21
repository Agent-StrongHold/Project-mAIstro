"""Principal-carrying Workspace access decisions (#1150).

HTTP routes and background consumers ask the same question -- may this
principal act on this Workspace? -- so the answer lives here, not in either.
"""

from __future__ import annotations

from contextlib import suppress
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
        super().__init__(
            "Workspace not found" if membership is None else "Workspace action not permitted"
        )
        self.membership = membership


def _is_blank(principal_id: object) -> bool:
    return not isinstance(principal_id, str) or not principal_id.strip()


class WorkspaceAuthorizer:
    def __init__(self, store: WorkspaceStore) -> None:
        self._store = store

    async def require(
        self,
        principal_id: str,
        workspace_id: str,
        action: WorkspaceAction,
    ) -> WorkspaceMembership:
        if _is_blank(principal_id):
            raise WorkspaceAuthorizationDenied
        if action not in WorkspaceAction.__members__.values():
            raise WorkspaceAuthorizationDenied
        wanted = WorkspaceAction(action)
        membership: WorkspaceMembership | None = None
        # Denied below, outside the suppressed lookup, so no __context__ tells
        # a missing Workspace apart from a foreign one.
        with suppress(WorkspaceNotFound):
            membership = await self._store.get_membership(workspace_id, user_id=principal_id)
        if membership is None:
            raise WorkspaceAuthorizationDenied
        if wanted is WorkspaceAction.VIEW or membership.can_administer:
            return membership
        raise WorkspaceAuthorizationDenied(membership)


__all__ = ["WorkspaceAction", "WorkspaceAuthorizationDenied", "WorkspaceAuthorizer"]
