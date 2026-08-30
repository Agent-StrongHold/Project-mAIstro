from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maistro.workspaces import InMemoryWorkspaceStore, WorkspaceOwnershipError
from maistro_server.api import workspaces as workspace_api
from maistro_server.api.auth import verify_api_key
from maistro_server.api.principal import AuthenticatedPrincipal
from maistro_server.main import app as server_app


def _principal(user_id: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id,
        token=f"token-{user_id}",
        roles=frozenset({"user"}),
    )


def _as_user(app: FastAPI, user_id: str) -> None:
    principal = _principal(user_id)
    app.dependency_overrides[verify_api_key] = lambda: principal


@pytest.fixture
async def api() -> AsyncIterator[tuple[FastAPI, TestClient, InMemoryWorkspaceStore]]:
    app = FastAPI()
    app.include_router(workspace_api.router)
    store = InMemoryWorkspaceStore()
    workspace_api.configure_workspace_store(store)
    client = TestClient(app)
    try:
        yield app, client, store
    finally:
        client.close()
        app.dependency_overrides.clear()
        workspace_api.configure_workspace_store(None)


async def test_create_list_and_get_use_authenticated_canonical_membership(api) -> None:
    app, client, _store = api
    _as_user(app, "alice")

    created_response = client.post(
        "/workspaces",
        json={"name": "Alpha", "description": "canonical"},
    )
    assert created_response.status_code == 201
    created = created_response.json()

    listed = client.get("/workspaces")
    assert listed.status_code == 200
    assert [item["workspace_id"] for item in listed.json()] == [created["workspace_id"]]

    fetched = client.get(f"/workspaces/{created['workspace_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "Alpha"

    members = client.get(f"/workspaces/{created['workspace_id']}/members")
    assert members.status_code == 200
    assert members.json()[0]["user_id"] == "alice"
    assert members.json()[0]["role"] == "owner"


async def test_non_member_cannot_discover_workspace_identity(api) -> None:
    app, client, store = api
    workspace = await store.create(creator_user_id="alice", name="Private")
    _as_user(app, "mallory")

    assert client.get(f"/workspaces/{workspace.workspace_id}").status_code == 404
    assert client.get(f"/workspaces/{workspace.workspace_id}/members").status_code == 404


async def test_unknown_workspace_is_404_without_existence_leak(api) -> None:
    app, client, _store = api
    _as_user(app, "alice")

    assert client.get("/workspaces/no-such-workspace").status_code == 404


async def test_owner_can_add_member_but_contributor_cannot_administer(api) -> None:
    app, client, _store = api
    _as_user(app, "alice")
    workspace_id = client.post("/workspaces", json={"name": "Shared"}).json()["workspace_id"]

    added = client.put(
        f"/workspaces/{workspace_id}/members/bob",
        json={"role": "contributor"},
    )
    assert added.status_code == 200
    assert added.json()["role"] == "contributor"

    _as_user(app, "bob")
    visible = client.get(f"/workspaces/{workspace_id}")
    assert visible.status_code == 200
    forbidden = client.patch(f"/workspaces/{workspace_id}", json={"name": "Hijacked"})
    assert forbidden.status_code == 403


async def test_non_owner_cannot_remove_another_member(api) -> None:
    app, client, _store = api
    _as_user(app, "alice")
    workspace_id = client.post("/workspaces", json={"name": "Shared"}).json()["workspace_id"]
    assert (
        client.put(
            f"/workspaces/{workspace_id}/members/bob",
            json={"role": "contributor"},
        ).status_code
        == 200
    )
    assert (
        client.put(
            f"/workspaces/{workspace_id}/members/cara",
            json={"role": "member"},
        ).status_code
        == 200
    )

    _as_user(app, "bob")
    response = client.delete(f"/workspaces/{workspace_id}/members/cara")

    assert response.status_code == 403


async def test_member_can_remove_self(api) -> None:
    app, client, _store = api
    _as_user(app, "alice")
    workspace_id = client.post("/workspaces", json={"name": "Shared"}).json()["workspace_id"]
    assert (
        client.put(
            f"/workspaces/{workspace_id}/members/bob",
            json={"role": "member"},
        ).status_code
        == 200
    )

    _as_user(app, "bob")
    response = client.delete(f"/workspaces/{workspace_id}/members/bob")

    assert response.status_code == 204
    assert client.get(f"/workspaces/{workspace_id}").status_code == 404


async def test_owner_can_remove_another_member(api) -> None:
    app, client, _store = api
    _as_user(app, "alice")
    workspace_id = client.post("/workspaces", json={"name": "Shared"}).json()["workspace_id"]
    client.put(f"/workspaces/{workspace_id}/members/bob", json={"role": "member"})

    response = client.delete(f"/workspaces/{workspace_id}/members/bob")

    assert response.status_code == 204
    members = client.get(f"/workspaces/{workspace_id}/members").json()
    assert [item["user_id"] for item in members] == ["alice"]


async def test_last_owner_cannot_remove_self(api) -> None:
    app, client, _store = api
    _as_user(app, "alice")
    workspace_id = client.post("/workspaces", json={"name": "Owned"}).json()["workspace_id"]

    response = client.delete(f"/workspaces/{workspace_id}/members/alice")

    assert response.status_code == 409


async def test_last_owner_cannot_demote_self(api) -> None:
    app, client, _store = api
    _as_user(app, "alice")
    workspace_id = client.post("/workspaces", json={"name": "Owned"}).json()["workspace_id"]

    response = client.put(
        f"/workspaces/{workspace_id}/members/alice",
        json={"role": "member"},
    )

    assert response.status_code == 409


async def test_owner_can_update_identity_fields(api) -> None:
    app, client, _store = api
    _as_user(app, "alice")
    workspace_id = client.post("/workspaces", json={"name": "Before"}).json()["workspace_id"]

    updated = client.patch(
        f"/workspaces/{workspace_id}",
        json={"name": "After", "description": "renamed"},
    )

    assert updated.status_code == 200
    assert updated.json()["name"] == "After"
    assert updated.json()["description"] == "renamed"


async def test_empty_identity_patch_is_safe_noop(api) -> None:
    app, client, _store = api
    _as_user(app, "alice")
    workspace_id = client.post("/workspaces", json={"name": "Stable"}).json()["workspace_id"]

    updated = client.patch(f"/workspaces/{workspace_id}", json={})

    assert updated.status_code == 200
    assert updated.json()["name"] == "Stable"


async def test_owner_can_delete_empty_workspace(api) -> None:
    app, client, _store = api
    _as_user(app, "alice")
    workspace_id = client.post("/workspaces", json={"name": "Disposable"}).json()["workspace_id"]

    response = client.delete(f"/workspaces/{workspace_id}")

    assert response.status_code == 204
    assert client.get("/workspaces").json() == []


async def test_workspace_delete_conflict_is_409(api, monkeypatch: pytest.MonkeyPatch) -> None:
    app, client, store = api
    _as_user(app, "alice")
    workspace_id = client.post("/workspaces", json={"name": "Durable"}).json()["workspace_id"]
    blocked = AsyncMock(side_effect=WorkspaceOwnershipError("Workspace has durable state"))
    monkeypatch.setattr(store, "delete", blocked)

    response = client.delete(f"/workspaces/{workspace_id}")

    assert response.status_code == 409
    assert "durable state" in response.json()["detail"]


def test_unauthenticated_dev_principal_fallback_is_explicit() -> None:
    assert workspace_api._user_id(None) == "dev"


def test_production_app_mounts_workspace_routes_at_v1_and_legacy_paths() -> None:
    paths = {route.path for route in server_app.routes}
    assert "/v1/workspaces" in paths
    assert "/workspaces" in paths


async def test_routes_fail_closed_when_no_workspace_store_is_configured() -> None:
    app = FastAPI()
    app.include_router(workspace_api.router)
    workspace_api.configure_workspace_store(None)
    client = TestClient(app)
    try:
        response = client.get("/workspaces")
        assert response.status_code == 503
    finally:
        client.close()
        workspace_api.configure_workspace_store(None)
