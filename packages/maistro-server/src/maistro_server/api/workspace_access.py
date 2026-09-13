"""Shared Workspace access checks for canonical Workspace-scoped APIs."""

from __future__ import annotations

from fastapi import HTTPException, Request, status

from maistro.security.sentinel.authz_types import Principal
from maistro.workspaces import (
    AuthorizedWorkspaceProjectService,
    WorkspaceMembership,
    WorkspaceNotFound,
    WorkspaceProjectAccessDenied,
    WorkspaceStore,
)
from maistro_server.api.principal import AuthenticatedPrincipal

_workspace_store: WorkspaceStore | None = None
_workspace_project_service: AuthorizedWorkspaceProjectService | None = None


def configure_workspace_store(store: WorkspaceStore | None) -> None:
    """Install the canonical Workspace store served by Workspace-scoped routes."""
    global _workspace_store, _workspace_project_service
    _workspace_store = store
    # Reconfiguration must not retain a service over a new store pair.
    _workspace_project_service = None


def configure_workspace_project_service(
    service: AuthorizedWorkspaceProjectService | None,
) -> None:
    """Install the Container-composed authorization seam for the server."""
    global _workspace_project_service
    _workspace_project_service = service


def get_workspace_project_service(request: Request) -> AuthorizedWorkspaceProjectService:
    """Return the Container's one authorized Workspace/Project boundary.

    The fallback exists for small API harnesses that configure stores directly;
    production composition always supplies the pre-built service on Container.
    """
    container = getattr(request.app.state, "container", None)
    service = getattr(container, "workspace_project_service", None) or _workspace_project_service
    if service is not None:
        return service
    project_store = getattr(container, "project_scope_store", None)
    store = get_workspace_store()
    if project_store is None:
        project_store = getattr(store, "project_store", None)
    if project_store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No Project scope store is configured",
        )
    return AuthorizedWorkspaceProjectService(store, project_store)


def get_project_service(request: Request) -> AuthorizedWorkspaceProjectService:
    """Return the authorized service when the app has a Project store."""
    container = getattr(request.app.state, "container", None)
    service = getattr(container, "workspace_project_service", None) or _workspace_project_service
    if service is not None:
        return service
    project_store = getattr(container, "project_scope_store", None)
    if project_store is not None:
        return AuthorizedWorkspaceProjectService(get_workspace_store(), project_store)
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="No authorized Workspace/Project service is configured",
    )


def principal(auth: AuthenticatedPrincipal | None) -> Principal:
    """Adapt HTTP identity to the core Principal used by the service seam."""
    return Principal(
        id=user_id(auth),
        kind="human",
        roles=tuple(sorted(auth.roles)) if auth is not None else (),
    )


def access_http_error(exc: WorkspaceProjectAccessDenied) -> HTTPException:
    """Map the core denial without making FastAPI part of the core contract."""
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND if exc.conceal else status.HTTP_403_FORBIDDEN,
        detail=str(exc),
    )


def get_workspace_store() -> WorkspaceStore:
    if _workspace_store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No Workspace store is configured",
        )
    return _workspace_store


def user_id(auth: AuthenticatedPrincipal | None) -> str:
    """Return the authenticated user id, including the auth-disabled dev identity."""
    return auth.user_id if auth is not None else "dev"


async def require_workspace_membership(
    store: WorkspaceStore,
    workspace_id: str,
    requester_user_id: str,
) -> WorkspaceMembership:
    """Require membership without disclosing Workspace existence to outsiders."""
    try:
        membership = await store.get_membership(workspace_id, user_id=requester_user_id)
    except WorkspaceNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        ) from exc
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    return membership


async def require_workspace_owner(
    store: WorkspaceStore,
    workspace_id: str,
    requester_user_id: str,
) -> WorkspaceMembership:
    """Require the canonical Workspace OWNER role."""
    membership = await require_workspace_membership(store, workspace_id, requester_user_id)
    if not membership.can_administer:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Workspace owner permission required",
        )
    return membership


__all__ = [
    "access_http_error",
    "configure_workspace_project_service",
    "configure_workspace_store",
    "get_project_service",
    "get_workspace_project_service",
    "get_workspace_store",
    "principal",
    "require_workspace_membership",
    "require_workspace_owner",
    "user_id",
]
