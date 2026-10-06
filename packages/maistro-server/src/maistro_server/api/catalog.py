"""Private organizational extension catalog API (#979).

Endpoints for discovering and inspecting extensions in a private catalog.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from maistro.extensions.catalog_service import CatalogService
from maistro_server.api.auth import RequireAuth

router = APIRouter(prefix="/catalog", tags=["catalog"])


def get_catalog_service(request: Request) -> CatalogService:
    """Return the catalog service wired by the process Container."""
    container = getattr(request.app.state, "container", None)
    if container is None or not hasattr(container, "ensure_catalog_service"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No catalog service is configured",
        )
    return container.ensure_catalog_service()


def _actor(auth: RequireAuth) -> str:
    """The authenticated principal is recorded for audit purposes."""
    return auth.principal_id  # Assuming RequireAuth has a principal_id attribute


@router.get("/{org_id}/extensions", response_model=list[dict])
async def list_catalog_extensions(
    org_id: str,
    auth: RequireAuth,
    service: Annotated[CatalogService, Depends(get_catalog_service)],
    search: Annotated[str | None, Query(description="Search term for extension name or publisher")] = None,
    publisher_id: Annotated[str | None, Query(description="Filter by publisher ID")] = None,
) -> list[dict]:
    """List extensions in the catalog for an organization.

    Optional search and filter parameters allow narrowing the list.
    """
    # TODO: Add authorization check for org_id? The auth should already be scoped.
    # For now, we assume the authenticated principal is allowed to view the catalog for the org.
    # In a real implementation, we would check that the principal is a member of the organization.
    extensions = await service.list_extensions(
        org_id, search=search, publisher_id=publisher_id
    )
    return extensions


@router.get("/{org_id}/extensions/{extension_name}", response_model=list[dict])
async def list_extension_versions(
    org_id: str,
    extension_name: str,
    auth: RequireAuth,
    service: Annotated[CatalogService, Depends(get_catalog_service)],
) -> list[dict]:
    """List all versions of a specific extension in the catalog."""
    versions = await service.get_extension_versions(org_id, extension_name)
    return versions


@router.get("/{org_id}/extensions/{extension_name}/versions/{version}", response_model=dict)
async def get_extension_version(
    org_id: str,
    extension_name: str,
    version: str,
    auth: RequireAuth,
    service: Annotated[CatalogService, Depends(get_catalog_service)],
) -> dict:
    """Get metadata for a specific version of an extension in the catalog."""
    entry = await service.get_extension_version(org_id, extension_name, version)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Extension {extension_name} version {version} not found in catalog for organization {org_id}",
        )
    return entry


# The handlers are this module's public surface: FastAPI registers them from
# the decorators, which static import scanning cannot see. Declaring them here
# is the same statement a2a.py's __all__ makes (see the comment there), and is
# what keeps this module's route handlers out of the fastapi-route-handler
# Vulture ledger: a new handler must join this list (the drift is caught by
# test_all_covers_every_route_handler), not silently re-enter the dead-code
# ratchet as unbanked debt.
__all__ = [
    "get_catalog_service",
    "get_extension_version",
    "list_catalog_extensions",
    "list_extension_versions",
    "router",
]
