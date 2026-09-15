from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from services.dag_execution_scope import (
    DagWorkspaceSelectionError,
    authorize_hive_dag_scope,
    authorize_hive_dag_workspace,
)
from services.workspace_authority import canonical_store_for_tests
from starlette.websockets import WebSocketDisconnect

POLICY_VIOLATION = 1008
NORMAL_CLOSURE = 1000


async def _canonical_workspace(workspace_id: str, *, member_user_id: str) -> None:
    store = canonical_store_for_tests()
    await store.create(
        creator_user_id=member_user_id,
        workspace_id=workspace_id,
        name=workspace_id,
    )


def _make_workspace(workspace_id: str, *, member_user_id: str) -> None:
    asyncio.run(_canonical_workspace(workspace_id, member_user_id=member_user_id))


@pytest.mark.asyncio
async def test_dag_workspace_selection_requires_workspace_and_principal() -> None:
    with pytest.raises(DagWorkspaceSelectionError, match="Workspace selection is required"):
        await authorize_hive_dag_workspace(workspace_id=" ", user_id="user-a")

    with pytest.raises(DagWorkspaceSelectionError, match="authenticated user identity is required"):
        await authorize_hive_dag_workspace(workspace_id="workspace-a", user_id=" ")


@pytest.mark.asyncio
async def test_dag_scope_reads_canonical_workspace_without_legacy_row() -> None:
    await _canonical_workspace("canonical-only", member_user_id="user-a")

    scope = await authorize_hive_dag_scope(workspace_id="canonical-only", user_id="user-a")
    assert scope.workspace_id == "canonical-only"
    assert scope.user_id == "user-a"
    assert scope.project_id


@pytest.mark.asyncio
async def test_dag_workspace_selection_hides_unknown_and_nonmember() -> None:
    await _canonical_workspace("scope-member-check", member_user_id="user-a")

    with pytest.raises(DagWorkspaceSelectionError, match="Workspace not found"):
        await authorize_hive_dag_workspace(workspace_id="does-not-exist", user_id="user-a")
    with pytest.raises(DagWorkspaceSelectionError, match="Workspace not found"):
        await authorize_hive_dag_workspace(workspace_id="scope-member-check", user_id="user-b")


def test_dag_run_socket_requires_and_authorizes_canonical_workspace(
    admin_client: TestClient,
) -> None:
    _make_workspace("scope-socket-member", member_user_id="admin")
    with (
        admin_client.websocket_connect(
            "/v1/ws/dags/no-such-dag/run?workspace_id=scope-socket-member"
        ) as ws,
        pytest.raises(WebSocketDisconnect) as exc,
    ):
        assert ws.receive_json() == {"error": "dag not found"}
        ws.receive_json()
    assert exc.value.code == NORMAL_CLOSURE


def test_dag_run_socket_refuses_unknown_or_nonmember_workspace(
    admin_client: TestClient,
) -> None:
    _make_workspace("scope-socket-nonmember", member_user_id="someone-else")
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        admin_client.websocket_connect(
            "/v1/ws/dags/no-such-dag/run?workspace_id=scope-socket-nonmember"
        ) as ws,
    ):
        ws.receive_json()
    assert exc.value.code == POLICY_VIOLATION


def test_dag_run_socket_refuses_omitted_workspace(admin_client: TestClient) -> None:
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        admin_client.websocket_connect("/v1/ws/dags/no-such-dag/run") as ws,
    ):
        ws.receive_json()
    assert exc.value.code == POLICY_VIOLATION
