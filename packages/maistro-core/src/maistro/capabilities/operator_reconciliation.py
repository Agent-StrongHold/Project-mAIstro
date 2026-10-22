"""Scoped operator access to the existing Invocation reconciliation authority.

This service grants no permissions and never dispatches or resumes execution.
Project grants decide who may inspect or submit evidence; Invocation owns the
disposition, audit record, revision fence and subsequent effect admission.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import ValidationError

from maistro.capabilities.effect_context import CapabilityEffectContext
from maistro.capabilities.invocation import Invocation
from maistro.projects.authorization import resolve_project_authorization
from maistro.projects.scope import ProjectNotFound
from maistro.projects.scope_store import ProjectScopeStore
from maistro.workspaces.authorization import (
    WorkspaceAction,
    WorkspaceAuthorizationDenied,
    WorkspaceAuthorizer,
)
from maistro.workspaces.store import WorkspaceStore

INVOCATIONS_INSPECT = "invocations.inspect"
INVOCATIONS_RECONCILE = "invocations.reconcile"

__all__ = [
    "INVOCATIONS_INSPECT",
    "INVOCATIONS_RECONCILE",
    "InvocationNotVisible",
    "OperatorInvocationReconciliation",
]


class InvocationNotVisible(LookupError):
    """Missing, foreign and unauthorized records have the same public answer."""

    def __init__(self) -> None:
        super().__init__("Invocation not found")


class OperatorInvocationReconciliation:
    def __init__(
        self,
        effects: CapabilityEffectContext,
        workspaces: WorkspaceStore,
        projects: ProjectScopeStore,
    ) -> None:
        self.effects = effects
        self._workspaces = WorkspaceAuthorizer(workspaces)
        self._projects = projects

    async def authorize(
        self, *, principal_id: str, workspace_id: str, project_id: str, permission: str
    ) -> None:
        """Resolve explicit Project authority; membership/owner role alone is insufficient."""
        if permission not in {INVOCATIONS_INSPECT, INVOCATIONS_RECONCILE}:
            raise ValueError("unknown Invocation permission")
        try:
            await self._workspaces.require(principal_id, workspace_id, WorkspaceAction.VIEW)
            project = await self._projects.get(project_id)
            if project is None or project.workspace_id != workspace_id:
                raise InvocationNotVisible
            authority = await resolve_project_authorization(
                self._projects, project_id=project_id, principal_id=principal_id
            )
        except (WorkspaceAuthorizationDenied, ProjectNotFound) as exc:
            raise InvocationNotVisible from exc
        if not authority.allows(permission):
            raise InvocationNotVisible

    async def discover(
        self,
        *,
        principal_id: str,
        workspace_id: str,
        project_id: str,
        stale_before: datetime,
        limit: int = 100,
        after: tuple[datetime, str] | None = None,
    ) -> list[Invocation]:
        await self.authorize(
            principal_id=principal_id,
            workspace_id=workspace_id,
            project_id=project_id,
            permission=INVOCATIONS_INSPECT,
        )
        return await self.effects.invocations.discover_ambiguous_page(
            workspace_id=workspace_id,
            project_id=project_id,
            stale_before=stale_before,
            limit=limit,
            after=after,
        )

    async def get(
        self,
        invocation_id: str,
        *,
        principal_id: str,
        workspace_id: str,
        project_id: str,
        permission: str = INVOCATIONS_INSPECT,
    ) -> Invocation:
        await self.authorize(
            principal_id=principal_id,
            workspace_id=workspace_id,
            project_id=project_id,
            permission=permission,
        )
        try:
            item = await self.effects.invocation_store.get(invocation_id)
        except ValidationError as exc:
            # An unreadable row cannot establish ownership or disclose existence.
            raise InvocationNotVisible from exc
        if item is None or (item.workspace_id, item.project_id) != (workspace_id, project_id):
            raise InvocationNotVisible
        return item
