"""Canonical Workspace domain surface."""

from __future__ import annotations

from collections.abc import Mapping

from maistro.workspaces.model import (
    Workspace,
    WorkspaceAccessDenied,
    WorkspaceMember,
    WorkspaceMembership,
    WorkspaceNotFound,
    WorkspaceOwnershipError,
    WorkspaceRole,
)
from maistro.workspaces.pg_store import PgWorkspaceStore
from maistro.workspaces.store import InMemoryWorkspaceStore, WorkspaceStore


def _scope_value(value: object, field: str) -> object | None:
    if isinstance(value, Mapping):
        return value.get(field)
    return getattr(value, field, None)


def resolve_workspace_id(value: object) -> str:
    """Resolve canonical Workspace ownership from a Workspace or scoped object."""

    if isinstance(value, Workspace):
        return value.workspace_id
    workspace_id = _scope_value(value, "workspace_id")
    if not isinstance(workspace_id, str) or not workspace_id.strip():
        raise WorkspaceOwnershipError("durable object must declare a non-empty workspace_id")
    return workspace_id


__all__ = [
    "InMemoryWorkspaceStore",
    "PgWorkspaceStore",
    "Workspace",
    "WorkspaceAccessDenied",
    "WorkspaceMember",
    "WorkspaceMembership",
    "WorkspaceNotFound",
    "WorkspaceOwnershipError",
    "WorkspaceRole",
    "WorkspaceStore",
    "resolve_workspace_id",
]
