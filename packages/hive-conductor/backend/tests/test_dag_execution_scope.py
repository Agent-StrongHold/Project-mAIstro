import asyncio
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from models.workspace import Workspace, WorkspaceMember, WorkspacePresentation
from services.dag_execution_scope import (
    DagWorkspaceSelectionError,
    authorize_hive_dag_workspace,
)
from starlette.websockets import WebSocketDisconnect

POLICY_VIOLATION = 1008
NORMAL_CLOSURE = 1000


async def _canonical_workspace(
    workspace_id: str,
    *,
    member_user_id: str,
    active: bool = True,
) -> Workspace:
    from services.workspace_authority import canonical_store_for_tests, presentation_store

    now = datetime.now(UTC)
    store = canonical_store_for_tests()
    await store.create(
        creator_user_id=member_user_id,
        name=workspace_id,
        workspace_id=workspace_id,
        created_at=now,
        updated_at=now,
    )
    presentation_store()[workspace_id] = WorkspacePresentation(
        workspace_id=workspace_id,
        persona_template_id="test-persona",
        active=active,
        updated_at=now,
    )
    selected = await store.get(workspace_id)
    assert selected is not None
    return selected


@pytest.mark.asyncio
async def test_dag_workspace_selection_requires_workspace_and_principal() -> None:
    with pytest.raises(DagWorkspaceSelectionError, match="Workspace selection is required"):
        await authorize_hive_dag_workspace(workspace_id=" ", user_id="user-a")

    with pytest.raises(DagWorkspaceSelectionError, match="authenticated user identity is required"):
        await authorize_hive_dag_workspace(workspace_id="workspace-a", user_id=" ")


@pytest.mark.asyncio
async def test_dag_workspace_selection_hides_unknown_nonmember_and_archived() -> None:
    await _canonical_workspace("scope-member-check", member_user_id="user-a")
    await _canonical_workspace("scope-archived-check", member_user_id="user-a", active=False)

    with pytest.raises(DagWorkspaceSelectionError, match="Workspace not found"):
        await authorize_hive_dag_workspace(workspace_id="does-not-exist", user_id="user-a")
    with pytest.raises(DagWorkspaceSelectionError, match="Workspace not found"):
        await authorize_hive_dag_workspace(workspace_id="scope-member-check", user_id="user-b")
    with pytest.raises(DagWorkspaceSelectionError, match="Workspace not found"):
        await authorize_hive_dag_workspace(workspace_id="scope-archived-check", user_id="user-a")


@pytest.mark.asyncio
async def test_dag_workspace_selection_returns_authorized_active_workspace() -> None:
    await _canonical_workspace("scope-authorized-check", member_user_id="user-a")

    selected = await authorize_hive_dag_workspace(
        workspace_id="scope-authorized-check", user_id="user-a"
    )
    assert selected.id == "scope-authorized-check"
    assert selected.members == [WorkspaceMember(user_id="user-a", role="owner")]


@pytest.mark.asyncio
async def test_dag_workspace_selection_ignores_legacy_membership_records() -> None:
    import stores

    await _canonical_workspace("scope-canonical-check", member_user_id="canonical-user")
    stores.workspaces["scope-canonical-check"] = Workspace(
        id="scope-canonical-check",
        persona_template_id="test-persona",
        name="legacy projection",
        members=[WorkspaceMember(user_id="legacy-user", role="owner")],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    assert (
        await authorize_hive_dag_workspace(
            workspace_id="scope-canonical-check", user_id="canonical-user"
        )
    ).id == "scope-canonical-check"
    with pytest.raises(DagWorkspaceSelectionError, match="Workspace not found"):
        await authorize_hive_dag_workspace(
            workspace_id="scope-canonical-check", user_id="legacy-user"
        )


def test_dag_run_socket_authorizes_an_explicit_workspace_selection(
    admin_client: TestClient,
) -> None:
    """The seam's accepting branch: a member selection reaches the socket.

    Authorization happens before ``accept()``, so a workspace the principal
    belongs to must still land on the normal DAG-not-found path — proving the
    check was passed, not merely not crashed.
    """
    workspace_id = "scope-socket-member"
    asyncio.run(_canonical_workspace(workspace_id, member_user_id="admin"))
    with (
        admin_client.websocket_connect(
            f"/v1/ws/dags/no-such-dag/run?workspace_id={workspace_id}"
        ) as ws,
        pytest.raises(WebSocketDisconnect) as exc,
    ):
        assert ws.receive_json() == {"error": "dag not found"}
        ws.receive_json()
    assert exc.value.code == NORMAL_CLOSURE


def test_dag_run_socket_refuses_a_selection_the_principal_cannot_use(
    admin_client: TestClient,
) -> None:
    """The seam's refusing branch: a non-member selection never accepts.

    The refusal shares one close code for unknown, non-member, and archived
    Workspaces so the boundary stays a non-oracle; asserting 1008 rather than
    a bare disconnect keeps that contract load-bearing.
    """
    workspace_id = "scope-socket-nonmember"
    asyncio.run(_canonical_workspace(workspace_id, member_user_id="someone-else"))
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        admin_client.websocket_connect(
            f"/v1/ws/dags/no-such-dag/run?workspace_id={workspace_id}"
        ) as ws,
    ):
        ws.receive_json()
    assert exc.value.code == POLICY_VIOLATION, (
        f"expected close {POLICY_VIOLATION} (refused before accept) but got "
        f"{exc.value.code}; {NORMAL_CLOSURE} means the socket was accepted"
    )


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
