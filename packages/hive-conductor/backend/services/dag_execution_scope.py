"""Canonical request scope admission for Hive DAG execution.

A Workspace id supplied by a client is only a selection.  The canonical
``WorkspaceStore`` verifies the identity and membership, and its paired
``ProjectScopeStore`` supplies the Project that owns the execution.  The
returned immutable scope is the only scope shape accepted by the DAG runner.
"""

from __future__ import annotations

from dataclasses import dataclass

from maistro.projects.scope import Project
from maistro.workspaces.model import Workspace
from services import workspace_authority


class DagWorkspaceSelectionError(ValueError):
    """An explicit DAG Workspace selection is absent or not authorized."""


@dataclass(frozen=True, slots=True)
class DagExecutionScope:
    """The server-authorized identity carried to one DAG execution."""

    workspace_id: str
    project_id: str
    user_id: str

    def __post_init__(self) -> None:
        if not self.workspace_id.strip():
            raise ValueError("workspace_id must be non-empty")
        if not self.project_id.strip():
            raise ValueError("project_id must be non-empty")
        if not self.user_id.strip():
            raise ValueError("user_id must be non-empty")


async def authorize_hive_dag_workspace(*, workspace_id: str, user_id: str) -> Workspace:
    """Resolve a selected Workspace through the canonical authority.

    This intentionally returns the canonical model, not Hive's retired
    ``stores.workspaces`` projection.  Unknown, inactive, and non-member
    selections share one refusal so this boundary is not an existence oracle.
    """
    selected = workspace_id.strip()
    principal = user_id.strip()
    if not selected:
        raise DagWorkspaceSelectionError("Workspace selection is required")
    if not principal:
        raise DagWorkspaceSelectionError("authenticated user identity is required")

    store = await workspace_authority.canonical_workspace_store()
    workspace = await store.get(selected)
    membership = None
    if workspace is not None:
        membership = await store.get_membership(selected, user_id=principal)
    presentation = workspace_authority.presentation_store().get(selected)
    if (
        workspace is None
        or membership is None
        or (presentation is not None and presentation.active is False)
    ):
        raise DagWorkspaceSelectionError("Workspace not found")
    return workspace


async def authorize_hive_dag_scope(
    *, workspace_id: str, user_id: str, project_id: str | None = None
) -> DagExecutionScope:
    """Admit one DAG request and resolve its canonical Project.

    The optional Project id is an internal/server selection.  When omitted,
    the Workspace's existing Root Project is used; no Project id is minted or
    copied from legacy DAG data.
    """
    workspace = await authorize_hive_dag_workspace(workspace_id=workspace_id, user_id=user_id)
    store = await workspace_authority.canonical_workspace_store()
    project_store = store.project_store
    if project_id is None or not project_id.strip():
        project: Project = await project_store.root_for_workspace(workspace.workspace_id)
    else:
        candidate = await project_store.get(project_id.strip())
        if candidate is None or candidate.workspace_id != workspace.workspace_id:
            raise DagWorkspaceSelectionError("Project not found")
        project = candidate
    return DagExecutionScope(
        workspace_id=workspace.workspace_id,
        project_id=project.project_id,
        user_id=user_id.strip(),
    )


__all__ = [
    "DagExecutionScope",
    "DagWorkspaceSelectionError",
    "authorize_hive_dag_scope",
    "authorize_hive_dag_workspace",
]
