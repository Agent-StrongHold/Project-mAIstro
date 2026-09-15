"""Canonical Workspace/Project authorization for the HITL door.

Authentication middleware establishes the requesting principal, but it does not
establish which canonical execution scopes that principal may inspect or settle.
This module resolves that decision from the same WorkspaceStore and
ProjectScopeStore owned by the embedded maistro Container (or the canonical
fallback store in standalone mode). It deliberately owns no Run state.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, cast

from maistro.auth.resources import (
    AuthorizationResolver,
    MembershipStatus,
)
from maistro.auth.resources import (
    ProjectMembership as AuthProjectMembership,
)
from maistro.auth.resources import (
    WorkspaceMembership as AuthWorkspaceMembership,
)
from maistro.projects.scope import ProjectNotFound
from maistro.projects.scope_store import ProjectScopeStore
from maistro.workspaces import WorkspaceMembership, WorkspaceRole

HITL_INSPECT = "hitl.inspect"
HITL_ANSWER = "hitl.answer"
HITL_CANCEL = "hitl.cancel"
HITL_PERMISSIONS = frozenset({HITL_INSPECT, HITL_ANSWER, HITL_CANCEL})


class HitlAuthorizationDenied(PermissionError):
    """The principal is not authorized for the requested canonical scope."""


async def _workspace_store() -> Any:
    from services.workspace_authority import canonical_store_for_tests

    return canonical_store_for_tests()


async def _project_store() -> ProjectScopeStore | None:
    """Return the Project store paired with the canonical Workspace store."""
    try:
        from services.engine import get_engine

        engine = get_engine()
        container = getattr(getattr(engine, "_agent_port", None), "container", None)
        project_store = getattr(container, "project_scope_store", None)
        if project_store is not None:
            return cast(ProjectScopeStore, project_store)
    except RuntimeError:
        pass

    workspace_store = await _workspace_store()
    project_store = getattr(workspace_store, "project_store", None)
    return cast(ProjectScopeStore, project_store) if project_store is not None else None


def _workspace_auth_membership(membership: WorkspaceMembership) -> AuthWorkspaceMembership:
    """Map the canonical Workspace role to HITL's structural permissions.

    Workspace membership permits inspection, while settling human work requires
    either the Workspace owner or an explicit Project grant. This keeps a
    contributor's generic workspace access from becoming approval authority.
    """
    grants = {HITL_INSPECT}
    if membership.role is WorkspaceRole.OWNER:
        grants.update(HITL_PERMISSIONS)
    return AuthWorkspaceMembership(
        workspace_id=membership.workspace_id,
        principal_id=membership.user_id,
        grants=frozenset(grants),
        status=MembershipStatus.ACTIVE,
    )


async def _project_memberships(
    project_store: ProjectScopeStore,
    *,
    project_path: Iterable[Any],
    principal_id: str,
    workspace_id: str,
) -> list[AuthProjectMembership]:
    memberships: list[AuthProjectMembership] = []
    for project in project_path:
        for membership in await project_store.memberships_for(
            project.project_id, principal_id=principal_id
        ):
            if membership.workspace_id != workspace_id:
                continue
            memberships.append(
                AuthProjectMembership(
                    workspace_id=membership.workspace_id,
                    project_id=membership.project_id,
                    principal_id=membership.principal_id,
                    grants=frozenset(membership.grants),
                    denies=frozenset(membership.denies),
                    status=MembershipStatus.ACTIVE,
                )
            )
    return memberships


async def authorize_project(
    *,
    principal_id: str,
    workspace_id: str,
    project_id: str,
    permission: str,
) -> None:
    """Authorize one HITL operation against the Run's exact Project.

    Caller-provided ids are only selectors. The Project and its lineage are
    loaded from canonical persistence, and the Run's Workspace must match the
    Project's Workspace before any permission is considered.
    """
    if permission not in HITL_PERMISSIONS:
        raise ValueError(f"unknown HITL permission {permission!r}")

    workspaces = await _workspace_store()
    membership = await workspaces.get_membership(workspace_id, user_id=principal_id)
    project_store = await _project_store()
    if membership is None or project_store is None:
        raise HitlAuthorizationDenied("canonical HITL scope is unavailable")

    try:
        project = await project_store.get(project_id)
        if project is None or project.workspace_id != workspace_id:
            raise HitlAuthorizationDenied("Project is outside the Run Workspace")
        lineage = await project_store.lineage(project_id)
    except (KeyError, ProjectNotFound, ValueError) as exc:
        raise HitlAuthorizationDenied("Project is not a canonical scope") from exc

    auth_workspace = _workspace_auth_membership(membership)
    auth_projects = await _project_memberships(
        project_store,
        project_path=lineage,
        principal_id=principal_id,
        workspace_id=workspace_id,
    )
    decision = AuthorizationResolver().resolve(
        permission=permission,
        workspace_membership=auth_workspace,
        project_path=(item.project_id for item in lineage),
        project_memberships=auth_projects,
    )
    if not decision.allowed:
        raise HitlAuthorizationDenied(decision.reason)


async def authorized_project_ids(
    *, principal_id: str, workspace_id: str, project_id: str | None = None
) -> list[str]:
    """Resolve the inspectable Projects before querying paused Run payloads."""
    project_store = await _project_store()
    if project_store is None:
        return []

    if project_id is not None:
        try:
            await authorize_project(
                principal_id=principal_id,
                workspace_id=workspace_id,
                project_id=project_id,
                permission=HITL_INSPECT,
            )
        except HitlAuthorizationDenied:
            return []
        return [project_id]

    try:
        root = await project_store.root_for_workspace(workspace_id)
    except (KeyError, ProjectNotFound):
        return []

    projects: list[Any] = []
    pending = [root]
    while pending:
        project = pending.pop()
        projects.append(project)
        pending.extend(await project_store.list_children(project.project_id))

    authorized: list[str] = []
    for project in projects:
        try:
            await authorize_project(
                principal_id=principal_id,
                workspace_id=workspace_id,
                project_id=project.project_id,
                permission=HITL_INSPECT,
            )
        except HitlAuthorizationDenied:
            continue
        authorized.append(project.project_id)
    return authorized


__all__ = [
    "HITL_ANSWER",
    "HITL_CANCEL",
    "HITL_INSPECT",
    "HitlAuthorizationDenied",
    "authorize_project",
    "authorized_project_ids",
]
