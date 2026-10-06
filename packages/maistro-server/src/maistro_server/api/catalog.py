"""Private organizational extension catalog API (#979).

Read-only discovery and inspection routes over the organization's private
catalog: list with search/filter, per-extension version history, and
per-version detail including the inspected manifest snapshot's requested
permissions, entry points, and artifact digests.

Every route is authenticated — reads included, because a private catalog's
publisher relationships and permission surfaces are exactly what an
anonymous caller must not enumerate. Org-level authorization is not checked
here: org-only scopes are authenticated-principal-only until the B1/Stronghold
tenancy substrate provides an org authority to check against — the same
deliberate, stated limitation as the extensions router. Authorization to
*run* anything is never granted by these routes; the governed install
lifecycle (#953) remains the canonical host authority.
"""

from __future__ import annotations

from typing import Annotated, cast

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
    return cast(CatalogService, container.ensure_catalog_service())


@router.get("/{org_id}/extensions", response_model=list[dict[str, object]])
async def list_catalog_extensions(
    org_id: str,
    auth: RequireAuth,
    service: Annotated[CatalogService, Depends(get_catalog_service)],
    search: Annotated[
        str | None, Query(description="Case-insensitive match on extension name or publisher")
    ] = None,
    publisher_id: Annotated[
        str | None, Query(description="Exact-match filter on publisher ID")
    ] = None,
) -> list[dict[str, object]]:
    """List extensions in the organization's catalog, newest-compatible view.

    ``auth`` carries no role in the body: its dependency is what enforces
    authentication on this read, per the module docstring's authorization
    model.
    """
    return list(await service.list_extensions(org_id, search=search, publisher_id=publisher_id))


@router.get("/{org_id}/extensions/{extension_name}", response_model=list[dict[str, object]])
async def list_extension_versions(
    org_id: str,
    extension_name: str,
    auth: RequireAuth,
    service: Annotated[CatalogService, Depends(get_catalog_service)],
) -> list[dict[str, object]]:
    """Every published version of one extension, newest first."""
    return list(await service.get_extension_versions(org_id, extension_name))


@router.get("/{org_id}/extensions/{extension_name}/versions/{version}")
async def get_extension_version(
    org_id: str,
    extension_name: str,
    version: str,
    auth: RequireAuth,
    service: Annotated[CatalogService, Depends(get_catalog_service)],
) -> dict[str, object]:
    """Inspect one published version's metadata before any download."""
    entry = await service.get_extension_version(org_id, extension_name, version)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Extension {extension_name} version {version} not found in "
                f"catalog for organization {org_id}"
            ),
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
