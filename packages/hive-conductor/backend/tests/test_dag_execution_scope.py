from datetime import UTC, datetime

import pytest
import stores
from fastapi.testclient import TestClient
from models.workspace import Workspace, WorkspaceMember
from services.dag_execution_scope import (
    DagWorkspaceSelectionError,
    authorize_hive_dag_workspace,
)
from starlette.websockets import WebSocketDisconnect

POLICY_VIOLATION = 1008
NORMAL_CLOSURE = 1000


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


def test_dag_run_socket_authorizes_an_explicit_workspace_selection(
    admin_client: TestClient,
) -> None:
    """The seam's accepting branch: a member selection reaches the socket.

    Authorization happens before ``accept()``, so a workspace the principal
    belongs to must still land on the normal DAG-not-found path — proving the
    check was passed, not merely not crashed.
    """
    workspace = _workspace("scope-socket-member", member_user_id="admin")
    stores.workspaces[workspace.id] = workspace
    try:
        with (
            admin_client.websocket_connect(
                f"/v1/ws/dags/no-such-dag/run?workspace_id={workspace.id}"
            ) as ws,
            pytest.raises(WebSocketDisconnect) as exc,
        ):
            assert ws.receive_json() == {"error": "dag not found"}
            ws.receive_json()
        assert exc.value.code == NORMAL_CLOSURE
    finally:
        stores.workspaces.pop(workspace.id, None)


def test_dag_run_socket_refuses_a_selection_the_principal_cannot_use(
    admin_client: TestClient,
) -> None:
    """The seam's refusing branch: a non-member selection never accepts.

    The refusal shares one close code for unknown, non-member, and archived
    Workspaces so the boundary stays a non-oracle; asserting 1008 rather than
    a bare disconnect keeps that contract load-bearing.
    """
    workspace = _workspace("scope-socket-nonmember", member_user_id="someone-else")
    stores.workspaces[workspace.id] = workspace
    try:
        with (
            pytest.raises(WebSocketDisconnect) as exc,
            admin_client.websocket_connect(
                f"/v1/ws/dags/no-such-dag/run?workspace_id={workspace.id}"
            ) as ws,
        ):
            ws.receive_json()
        assert exc.value.code == POLICY_VIOLATION, (
            f"expected close {POLICY_VIOLATION} (refused before accept) but got "
            f"{exc.value.code}; {NORMAL_CLOSURE} means the socket was accepted"
        )
    finally:
        stores.workspaces.pop(workspace.id, None)


def test_dag_run_socket_treats_a_blank_selection_as_omitted(
    admin_client: TestClient,
) -> None:
    """The transitional compatibility arc: whitespace-only is not a selection.

    Until DagBuilder sends ``activeWorkspaceId`` the omitted-id path stays
    live (see the PR description); this pins that a blank id takes exactly
    that path rather than the refusing one.
    """
    with (
        admin_client.websocket_connect("/v1/ws/dags/no-such-dag/run?workspace_id=%20") as ws,
        pytest.raises(WebSocketDisconnect) as exc,
    ):
        assert ws.receive_json() == {"error": "dag not found"}
        ws.receive_json()
    assert exc.value.code == NORMAL_CLOSURE
