from datetime import UTC, datetime

import pytest

import stores
from models.workspace import Workspace, WorkspaceMember
from services.dag_execution_scope import (
    DagWorkspaceSelectionError,
    authorize_hive_dag_workspace,
)


def _workspace(
    workspace_id: str,
    *,
    member_user_id: str,
    active: bool = True,
) -> Workspace:
    now = datetime.now(UTC)
    return Workspace(
        id=workspace_id,
        persona_template_id="test-persona",
        name=workspace_id,
        members=[WorkspaceMember(user_id=member_user_id, role="owner")],
        active=active,
        created_at=now,
        updated_at=now,
    )


def test_dag_workspace_selection_requires_workspace_and_principal() -> None:
    with pytest.raises(DagWorkspaceSelectionError, match="Workspace selection is required"):
        authorize_hive_dag_workspace(workspace_id=" ", user_id="user-a")

    with pytest.raises(DagWorkspaceSelectionError, match="authenticated user identity is required"):
        authorize_hive_dag_workspace(workspace_id="workspace-a", user_id=" ")


def test_dag_workspace_selection_hides_unknown_nonmember_and_archived() -> None:
    member_workspace = _workspace("scope-member-check", member_user_id="user-a")
    archived_workspace = _workspace(
        "scope-archived-check",
        member_user_id="user-a",
        active=False,
    )
    stores.workspaces[member_workspace.id] = member_workspace
    stores.workspaces[archived_workspace.id] = archived_workspace
    try:
        with pytest.raises(DagWorkspaceSelectionError, match="Workspace not found"):
            authorize_hive_dag_workspace(workspace_id="does-not-exist", user_id="user-a")
        with pytest.raises(DagWorkspaceSelectionError, match="Workspace not found"):
            authorize_hive_dag_workspace(workspace_id=member_workspace.id, user_id="user-b")
        with pytest.raises(DagWorkspaceSelectionError, match="Workspace not found"):
            authorize_hive_dag_workspace(workspace_id=archived_workspace.id, user_id="user-a")
    finally:
        stores.workspaces.pop(member_workspace.id, None)
        stores.workspaces.pop(archived_workspace.id, None)


def test_dag_workspace_selection_returns_authorized_active_workspace() -> None:
    workspace = _workspace("scope-authorized-check", member_user_id="user-a")
    stores.workspaces[workspace.id] = workspace
    try:
        selected = authorize_hive_dag_workspace(workspace_id=workspace.id, user_id="user-a")
        assert selected.id == workspace.id
        assert selected is workspace
    finally:
        stores.workspaces.pop(workspace.id, None)
