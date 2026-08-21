"""Workspace ownership boundary tests alongside the legacy Project domain."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from maistro.projects import Project, ProjectMemberRole
from maistro.workspaces import (
    InMemoryWorkspaceStore,
    Workspace,
    WorkspaceMembership,
    WorkspaceOwnershipError,
    WorkspaceRole,
    WorkspaceStore,
    resolve_workspace_id,
)


@dataclass(frozen=True)
class _CanonicalChild:
    workspace_id: str


@dataclass(frozen=True)
class _LegacyProjectChild:
    project_id: str


def test_workspace_is_distinct_from_project_scope() -> None:
    workspace = Workspace(workspace_id="ws-1", name="Alpha")

    assert Workspace is not Project
    assert not isinstance(workspace, Project)
    assert workspace.workspace_id == "ws-1"
    assert "owner_user_id" not in workspace.model_dump()


def test_workspace_store_implements_the_canonical_store_protocol() -> None:
    store = InMemoryWorkspaceStore()

    assert isinstance(store, WorkspaceStore)


@pytest.mark.asyncio
async def test_workspace_store_preserves_durable_identity() -> None:
    store = InMemoryWorkspaceStore()
    workspace = await store.create(creator_user_id="alice", name="Alpha")

    canonical_id = resolve_workspace_id(workspace)
    persisted = await store.get(canonical_id)

    assert persisted is not None
    assert canonical_id == workspace.workspace_id == persisted.workspace_id
    assert persisted.name == "Alpha"


def test_workspace_role_uses_canonical_collaboration_vocabulary() -> None:
    assert WorkspaceRole is not ProjectMemberRole
    assert {role.value for role in WorkspaceRole} == {"owner", "contributor", "member"}
    membership = WorkspaceMembership(workspace_id="ws-1", user_id="bob", role=WorkspaceRole.MEMBER)
    assert membership.can_use is True
    assert membership.can_contribute is False


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Workspace(workspace_id="ws-1", name="Alpha"), "ws-1"),
        (_CanonicalChild(workspace_id="ws-2"), "ws-2"),
        ({"workspace_id": "ws-3"}, "ws-3"),
    ],
)
def test_resolve_workspace_id_accepts_canonical_scopes(value: object, expected: str) -> None:
    assert resolve_workspace_id(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        object(),
        _LegacyProjectChild(project_id="project-1"),
        {"project_id": "project-2"},
        {"id": "looks-like-a-workspace-but-is-not-declared-as-one"},
        {"workspace_id": ""},
        {"workspace_id": 123},
    ],
)
def test_resolve_workspace_id_fails_closed_without_canonical_ownership(
    value: object,
) -> None:
    with pytest.raises(WorkspaceOwnershipError):
        resolve_workspace_id(value)
