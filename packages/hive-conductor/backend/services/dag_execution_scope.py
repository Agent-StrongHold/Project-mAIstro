"""Request-bound Workspace selection for Hive DAG execution.

This is an adapter over the canonical Workspace authority. Hive's presentation
model remains the response shape, but identity, membership, and active state
are resolved through ``workspace_authority`` rather than the legacy product
store. The DAG path must not manufacture a canonical Root Project from an id.
"""

from __future__ import annotations

from models.workspace import Workspace

from services.workspace_authority import visible_view


class DagWorkspaceSelectionError(ValueError):
    """An explicit DAG Workspace selection is absent or not authorized."""


async def authorize_hive_dag_workspace(*, workspace_id: str, user_id: str) -> Workspace:
    """Return the selected product view when canonical membership permits it.

    The client-supplied id is a selection, never proof of authority. Unknown,
    non-member, and inactive Workspaces intentionally have the same error so
    this boundary does not disclose which Workspace ids exist.
    """
    selected = workspace_id.strip()
    principal = user_id.strip()
    if not selected:
        raise DagWorkspaceSelectionError("Workspace selection is required")
    if not principal:
        raise DagWorkspaceSelectionError("authenticated user identity is required")

    workspace = await visible_view(principal, selected)
    if workspace is None or workspace.active is False:
        raise DagWorkspaceSelectionError("Workspace not found")
    return workspace


__all__ = ["DagWorkspaceSelectionError", "authorize_hive_dag_workspace"]
