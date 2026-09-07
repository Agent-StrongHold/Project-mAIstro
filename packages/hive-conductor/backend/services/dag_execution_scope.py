"""Request-bound Workspace selection for Hive DAG execution.

This is intentionally the transition seam, not a second canonical Workspace
store. Hive's visible tabs still come from ``stores.workspaces`` until #37
retires that duplicate authority. A DAG execution may therefore validate an
explicit product Workspace here, but it must not manufacture a canonical Root
Project from that id. #766 extends this seam to canonical Workspace/Project
resolution once the product authority converges.
"""

from __future__ import annotations

import stores
from models.workspace import Workspace


class DagWorkspaceSelectionError(ValueError):
    """An explicit DAG Workspace selection is absent or not authorized."""


def authorize_hive_dag_workspace(*, workspace_id: str, user_id: str) -> Workspace:
    """Return the selected Hive Workspace only when ``user_id`` is a member.

    The client-supplied id is a selection, never proof of authority. Unknown
    and non-member Workspaces intentionally have the same error so this
    boundary does not disclose which Workspace ids exist.

    This function stops at the current Hive authority. It does *not* call
    ``ProjectScopeStore.create_root``: until #37 converges Hive's Workspace
    identity onto the canonical store, doing that would create canonical scope
    for an id whose canonical Workspace does not exist.
    """
    selected = workspace_id.strip()
    principal = user_id.strip()
    if not selected:
        raise DagWorkspaceSelectionError("Workspace selection is required")
    if not principal:
        raise DagWorkspaceSelectionError("authenticated user identity is required")

    workspace = stores.workspaces.get(selected)
    if workspace is None or not any(member.user_id == principal for member in workspace.members):
        raise DagWorkspaceSelectionError("Workspace not found")
    if workspace.active is False:
        raise DagWorkspaceSelectionError("Workspace not found")
    return workspace


__all__ = ["DagWorkspaceSelectionError", "authorize_hive_dag_workspace"]
