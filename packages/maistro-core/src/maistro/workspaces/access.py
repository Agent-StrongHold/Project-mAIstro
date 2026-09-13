"""The canonical authorized Workspace/Project service boundary.

Low-level stores intentionally know persistence and tree invariants, but not the
acting principal. Product and background consumers must receive this service,
which resolves Workspace membership and Project grants before touching either
store. A caller-provided id is therefore only a lookup selection; it never
becomes an authorization scope by itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from maistro.projects.authorization import EffectiveAuthorization, resolve_project_authorization
from maistro.projects.scope import Project, ProjectMembership
from maistro.projects.scope_store import ProjectScopeStore
from maistro.security.sentinel.authz_types import Principal
from maistro.workspaces.model import (
    Workspace,
    WorkspaceMembership,
    WorkspaceNotFound,
    WorkspaceRole,
)
from maistro.workspaces.store import WorkspaceStore


@dataclass(frozen=True, slots=True)
class AuthorizationRequest:
    """An authorization decision's immutable actor, action, and scope."""

    principal: Principal
    action: str
    workspace_id: str
    project_id: str | None = None


class WorkspaceProjectAccessDenied(PermissionError):
    """A principal is not authorized for a Workspace/Project operation."""

    def __init__(self, message: str, *, conceal: bool) -> None:
        super().__init__(message)
        self.conceal = conceal


class AuthorizedWorkspaceProjectService:
    """Authorize every canonical Workspace/Project product operation.

    This is deliberately a service over the low-level stores, not another
    store or scheduler. ``principal`` is required on every operation that has
    an existing Workspace or Project scope.
    """

    def __init__(self, workspace_store: WorkspaceStore, project_store: ProjectScopeStore) -> None:
        if workspace_store.project_store is not project_store:
            # A Workspace and its Root Project must be composed from the same
            # persistence selection. Otherwise an id can be authorized in one
            # backend and mutated in another.
            raise ValueError("Workspace and Project stores must be one composed pair")
        self._workspace_store = workspace_store
        self._project_store = project_store

    async def authorize(self, request: AuthorizationRequest) -> EffectiveAuthorization:
        """Resolve canonical membership/grants for one action and scope."""
        self._validate_principal(request.principal)
        membership = await self._workspace_membership(
            request.workspace_id, request.principal.id, conceal=True
        )
        workspace_grants = self._workspace_grants(membership.role, request.action)
        if request.project_id is None:
            effective = EffectiveAuthorization(
                grants=frozenset(workspace_grants),
                denies=frozenset(),
                delegable_grants=frozenset(workspace_grants),
            )
        else:
            project = await self._project_for_scope(
                request.workspace_id, request.project_id, conceal=True
            )
            effective = await resolve_project_authorization(
                self._project_store,
                project_id=project.project_id,
                principal_id=request.principal.id,
                workspace_grants=workspace_grants,
                workspace_delegable_grants=workspace_grants,
            )
        if not effective.allows(request.action):
            raise WorkspaceProjectAccessDenied(
                f"principal {request.principal.id!r} is not authorized for "
                f"{request.action!r} in Workspace {request.workspace_id!r}"
                + (f" / Project {request.project_id!r}" if request.project_id else ""),
                conceal=request.action.endswith(".read") or request.action.endswith(".list"),
            )
        return effective

    async def create_workspace(
        self, principal: Principal, *, name: str, description: str = ""
    ) -> Workspace:
        """Create a new Workspace; the creator becomes its owner."""
        self._validate_principal(principal)
        return await self._workspace_store.create(
            creator_user_id=principal.id,
            name=name,
            description=description,
        )

    async def list_workspaces(self, principal: Principal) -> list[Workspace]:
        """List only Workspaces whose canonical roster names the principal."""
        self._validate_principal(principal)
        return await self._workspace_store.list_for_user(principal.id)

    async def get_workspace(self, principal: Principal, workspace_id: str) -> Workspace:
        await self.authorize(AuthorizationRequest(principal, "workspace.read", workspace_id))
        workspace = await self._workspace_store.get(workspace_id)
        if workspace is None:  # The membership lookup normally catches this.
            raise WorkspaceProjectAccessDenied("Workspace not found", conceal=True)
        return workspace

    async def update_workspace(
        self,
        principal: Principal,
        workspace_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> Workspace:
        await self.authorize(AuthorizationRequest(principal, "workspace.update", workspace_id))
        workspace = await self.get_workspace(principal, workspace_id)
        updates: dict[str, object] = {}
        if name is not None:
            updates["name"] = name
        if description is not None:
            updates["description"] = description
        return await self._workspace_store.update(workspace.model_copy(update=updates))

    async def delete_workspace(self, principal: Principal, workspace_id: str) -> None:
        await self.authorize(AuthorizationRequest(principal, "workspace.delete", workspace_id))
        await self._workspace_store.delete(workspace_id)

    async def list_workspace_members(
        self, principal: Principal, workspace_id: str
    ) -> list[WorkspaceMembership]:
        await self.authorize(
            AuthorizationRequest(principal, "workspace.memberships.read", workspace_id)
        )
        return await self._workspace_store.list_memberships(workspace_id)

    async def set_workspace_membership(
        self,
        principal: Principal,
        workspace_id: str,
        *,
        user_id: str,
        role: WorkspaceRole,
    ) -> WorkspaceMembership:
        await self.authorize(
            AuthorizationRequest(principal, "workspace.memberships.write", workspace_id)
        )
        return await self._workspace_store.set_membership(workspace_id, user_id=user_id, role=role)

    async def remove_workspace_membership(
        self, principal: Principal, workspace_id: str, *, user_id: str
    ) -> None:
        action = (
            "workspace.memberships.remove"
            if user_id == principal.id
            else "workspace.memberships.write"
        )
        await self.authorize(AuthorizationRequest(principal, action, workspace_id))
        await self._workspace_store.remove_membership(workspace_id, user_id=user_id)

    async def get_root_project(self, principal: Principal, workspace_id: str) -> Project:
        await self.authorize(AuthorizationRequest(principal, "project.read", workspace_id))
        return await self._project_store.root_for_workspace(workspace_id)

    async def get_project(
        self, principal: Principal, workspace_id: str, project_id: str
    ) -> Project:
        await self.authorize(
            AuthorizationRequest(principal, "project.read", workspace_id, project_id)
        )
        return await self._project_store.get(project_id)  # type: ignore[return-value]

    async def list_project_children(
        self, principal: Principal, workspace_id: str, project_id: str
    ) -> list[Project]:
        await self.authorize(
            AuthorizationRequest(principal, "project.read", workspace_id, project_id)
        )
        return await self._project_store.list_children(project_id)

    async def create_project(
        self,
        principal: Principal,
        workspace_id: str,
        *,
        parent_project_id: str,
        name: str,
        defaults: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Project:
        await self.authorize(
            AuthorizationRequest(principal, "project.mutate", workspace_id, parent_project_id)
        )
        return await self._project_store.create(
            workspace_id=workspace_id,
            parent_project_id=parent_project_id,
            name=name,
            defaults=defaults,
            metadata=metadata,
        )

    async def move_project(
        self,
        principal: Principal,
        workspace_id: str,
        project_id: str,
        *,
        parent_project_id: str,
    ) -> Project:
        await self.authorize(
            AuthorizationRequest(principal, "project.mutate", workspace_id, project_id)
        )
        await self.authorize(
            AuthorizationRequest(principal, "project.mutate", workspace_id, parent_project_id)
        )
        return await self._project_store.move_project(
            project_id, parent_project_id=parent_project_id
        )

    async def update_project_defaults(
        self,
        principal: Principal,
        workspace_id: str,
        project_id: str,
        *,
        defaults: dict[str, Any],
    ) -> Project:
        await self.authorize(
            AuthorizationRequest(principal, "project.mutate", workspace_id, project_id)
        )
        return await self._project_store.update_defaults(project_id, defaults=defaults)

    async def delete_project(
        self, principal: Principal, workspace_id: str, project_id: str
    ) -> None:
        await self.authorize(
            AuthorizationRequest(principal, "project.mutate", workspace_id, project_id)
        )
        await self._project_store.delete(project_id)

    async def list_project_memberships(
        self, principal: Principal, workspace_id: str, project_id: str
    ) -> list[ProjectMembership]:
        await self.authorize(
            AuthorizationRequest(principal, "project.memberships.read", workspace_id, project_id)
        )
        return await self._project_store.memberships_for(project_id)

    async def add_project_membership(
        self,
        principal: Principal,
        workspace_id: str,
        project_id: str,
        membership: ProjectMembership,
    ) -> ProjectMembership:
        await self._project_for_scope(workspace_id, project_id, conceal=True)
        actor_membership = await self._workspace_membership(
            workspace_id, principal.id, conceal=True
        )
        if membership.workspace_id != workspace_id or membership.project_id != project_id:
            raise WorkspaceProjectAccessDenied(
                "membership scope does not match request", conceal=False
            )
        if actor_membership.role is not WorkspaceRole.OWNER:
            if membership.denies:
                raise WorkspaceProjectAccessDenied(
                    "only a Workspace owner may issue Project denies", conceal=False
                )
            existing = await self._project_store.memberships_for(
                project_id, principal_id=membership.principal_id
            )
            if existing:
                # A delegated update cannot launder away an owner-issued deny.
                membership = membership.model_copy(update={"denies": existing[0].denies})

        if not membership.grants:
            await self.authorize(
                AuthorizationRequest(
                    principal, "project.memberships.write", workspace_id, project_id
                )
            )
        else:
            # Delegation is checked with the same EffectiveAuthorization resolver
            # as ordinary reads/mutations; holding an action is not enough.
            for action in sorted(membership.grants):
                effective = await self._effective(principal, workspace_id, project_id, action)
                if not effective.can_delegate(action):
                    raise WorkspaceProjectAccessDenied(
                        f"principal {principal.id!r} cannot delegate {action!r}",
                        conceal=False,
                    )
        return await self._project_store.set_membership(membership)

    async def remove_project_membership(
        self, principal: Principal, workspace_id: str, project_id: str, *, principal_id: str
    ) -> None:
        await self.authorize(
            AuthorizationRequest(principal, "project.memberships.write", workspace_id, project_id)
        )
        await self._project_store.remove_membership(project_id, principal_id=principal_id)

    async def _effective(
        self, principal: Principal, workspace_id: str, project_id: str, action: str
    ) -> EffectiveAuthorization:
        membership = await self._workspace_membership(workspace_id, principal.id, conceal=True)
        project = await self._project_for_scope(workspace_id, project_id, conceal=True)
        return await resolve_project_authorization(
            self._project_store,
            project_id=project.project_id,
            principal_id=principal.id,
            workspace_grants=self._workspace_grants(membership.role, action),
            workspace_delegable_grants=self._workspace_grants(membership.role, action),
        )

    async def _workspace_membership(
        self, workspace_id: str, principal_id: str, *, conceal: bool
    ) -> WorkspaceMembership:
        try:
            membership = await self._workspace_store.get_membership(
                workspace_id, user_id=principal_id
            )
        except WorkspaceNotFound as exc:
            raise WorkspaceProjectAccessDenied("Workspace not found", conceal=conceal) from exc
        if membership is None:
            raise WorkspaceProjectAccessDenied("Workspace not found", conceal=conceal)
        return membership

    async def _project_for_scope(
        self, workspace_id: str, project_id: str, *, conceal: bool
    ) -> Project:
        project = await self._project_store.get(project_id)
        if project is None or project.workspace_id != workspace_id:
            raise WorkspaceProjectAccessDenied("Project not found", conceal=conceal)
        return project

    @staticmethod
    def _workspace_grants(role: WorkspaceRole, action: str) -> set[str]:
        if role is WorkspaceRole.OWNER:
            return {action}
        if action in {"workspace.read", "workspace.memberships.read", "project.read"}:
            return {action}
        if action == "workspace.memberships.remove":
            return {action}
        return set()

    @staticmethod
    def _validate_principal(principal: Principal) -> None:
        if not principal.id.strip():
            raise ValueError("principal id must be a non-empty string")


# Short alias for composition roots that prefer the less verbose service name.
WorkspaceProjectService = AuthorizedWorkspaceProjectService


__all__ = [
    "AuthorizationRequest",
    "AuthorizedWorkspaceProjectService",
    "WorkspaceProjectAccessDenied",
    "WorkspaceProjectService",
]
