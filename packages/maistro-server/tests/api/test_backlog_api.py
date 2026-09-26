"""Workspace BacklogItem API (#98): membership reads, contributor writes, CAS."""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.workspaces import InMemoryWorkspaceStore, WorkspaceRole
from maistro.workspaces.backlog import InMemoryBacklogItemStore
from maistro_server.api import workspaces as workspace_api
from maistro_server.api.auth import verify_api_key
from maistro_server.api.principal import AuthenticatedPrincipal
from maistro_server.api.route_table import iter_effective_routes
from maistro_server.main import app as server_app


def _as_user(app: FastAPI, user_id: str) -> None:
    principal = AuthenticatedPrincipal(
        user_id=user_id, token=f"token-{user_id}", roles=frozenset({"user"})
    )
    app.dependency_overrides[verify_api_key] = lambda: principal


class _Api(SimpleNamespace):
    app: FastAPI
    client: TestClient
    workspaces: InMemoryWorkspaceStore
    projects: InMemoryProjectScopeStore


@pytest.fixture
async def api() -> AsyncIterator[_Api]:
    projects = InMemoryProjectScopeStore()
    workspaces = InMemoryWorkspaceStore(project_store=projects)
    app = FastAPI()
    app.state.container = SimpleNamespace(
        project_scope_store=projects,
        backlog_store=InMemoryBacklogItemStore(project_store=projects),
    )
    app.include_router(workspace_api.router)
    workspace_api.configure_workspace_store(workspaces)
    client = TestClient(app)
    try:
        yield _Api(app=app, client=client, workspaces=workspaces, projects=projects)
    finally:
        client.close()
        app.dependency_overrides.clear()
        workspace_api.configure_workspace_store(None)


async def _workspace(api: _Api, name: str = "Alpha") -> tuple[str, str]:
    workspace = await api.workspaces.create(creator_user_id="owner", name=name)
    await api.workspaces.set_membership(
        workspace.workspace_id, user_id="member", role=WorkspaceRole.MEMBER
    )
    await api.workspaces.set_membership(
        workspace.workspace_id, user_id="contributor", role=WorkspaceRole.CONTRIBUTOR
    )
    root = await api.projects.root_for_workspace(workspace.workspace_id)
    return workspace.workspace_id, root.project_id


def _create(api: _Api, workspace_id: str, project_id: str, **fields) -> dict:
    response = api.client.post(
        f"/workspaces/{workspace_id}/backlog",
        json={"project_id": project_id, "title": "Ship backlog", **fields},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_contributor_creates_and_member_reads(api) -> None:
    workspace_id, project_id = await _workspace(api)
    _as_user(api.app, "contributor")
    created = _create(
        api,
        workspace_id,
        project_id,
        external_key="engine-001",
        goal_ref={"goal_id": "g-1", "goal_revision": 4},
    )
    assert created["workspace_id"] == workspace_id
    assert created["version"] == 1
    assert created["goal_ref"] == {"goal_id": "g-1", "goal_revision": 4}

    _as_user(api.app, "member")
    listed = api.client.get(f"/workspaces/{workspace_id}/backlog")
    assert listed.status_code == 200
    assert [item["item_id"] for item in listed.json()] == [created["item_id"]]
    filtered = api.client.get(f"/workspaces/{workspace_id}/backlog", params={"status": "blocked"})
    assert filtered.json() == []
    fetched = api.client.get(f"/workspaces/{workspace_id}/backlog/{created['item_id']}")
    assert fetched.status_code == 200
    assert fetched.json() == created


async def test_member_cannot_write(api) -> None:
    workspace_id, project_id = await _workspace(api)
    _as_user(api.app, "contributor")
    item = _create(api, workspace_id, project_id)
    other = _create(api, workspace_id, project_id)

    _as_user(api.app, "member")
    base = f"/workspaces/{workspace_id}/backlog"
    responses = [
        api.client.post(base, json={"project_id": project_id, "title": "x"}),
        api.client.patch(f"{base}/{item['item_id']}", json={"expected_version": 1, "title": "x"}),
        api.client.put(f"{base}/{item['item_id']}/dependencies/{other['item_id']}"),
        api.client.delete(f"{base}/{item['item_id']}/dependencies/{other['item_id']}"),
        api.client.put(
            f"{base}/{item['item_id']}/parent",
            json={"expected_version": 1, "parent_item_id": other["item_id"]},
        ),
    ]
    assert [r.status_code for r in responses] == [403] * 5
    assert api.client.get(f"{base}/{item['item_id']}").json()["version"] == 1


async def test_non_member_gets_404(api) -> None:
    workspace_id, project_id = await _workspace(api)
    _as_user(api.app, "contributor")
    item = _create(api, workspace_id, project_id)

    _as_user(api.app, "stranger")
    base = f"/workspaces/{workspace_id}/backlog"
    assert api.client.get(base).status_code == 404
    assert api.client.get(f"{base}/{item['item_id']}").status_code == 404
    assert api.client.post(base, json={"project_id": project_id, "title": "x"}).status_code == 404


async def test_stale_patch_returns_409_with_the_current_item(api) -> None:
    workspace_id, project_id = await _workspace(api)
    _as_user(api.app, "contributor")
    item = _create(api, workspace_id, project_id)
    url = f"/workspaces/{workspace_id}/backlog/{item['item_id']}"

    first = api.client.patch(url, json={"expected_version": 1, "status": "accepted"})
    assert first.status_code == 200
    assert (first.json()["version"], first.json()["status"]) == (2, "accepted")

    stale = api.client.patch(url, json={"expected_version": 1, "title": "Overwrite"})
    assert stale.status_code == 409
    assert stale.json()["current"] == first.json()
    assert api.client.get(url).json() == first.json()

    missing_version = api.client.patch(url, json={"title": "No version"})
    assert missing_version.status_code == 422


async def test_cross_workspace_ids_return_404(api) -> None:
    a_id, a_project = await _workspace(api, "A")
    b_id, b_project = await _workspace(api, "B")
    _as_user(api.app, "contributor")
    a_item = _create(api, a_id, a_project)
    b_item = _create(api, b_id, b_project)

    a_base = f"/workspaces/{a_id}/backlog"
    assert api.client.get(f"{a_base}/{b_item['item_id']}").status_code == 404
    assert (
        api.client.patch(
            f"{a_base}/{b_item['item_id']}", json={"expected_version": 1, "title": "x"}
        ).status_code
        == 404
    )
    assert (
        api.client.put(f"{a_base}/{a_item['item_id']}/dependencies/{b_item['item_id']}").status_code
        == 404
    )
    assert (
        api.client.put(
            f"{a_base}/{a_item['item_id']}/parent",
            json={"expected_version": 1, "parent_item_id": b_item["item_id"]},
        ).status_code
        == 404
    )
    assert api.client.post(a_base, json={"project_id": b_project, "title": "x"}).status_code == 404
    assert (
        api.client.patch(
            f"{a_base}/{a_item['item_id']}", json={"expected_version": 1, "project_id": b_project}
        ).status_code
        == 404
    )
    assert api.client.get(f"{a_base}/{a_item['item_id']}").json()["version"] == 1


async def test_dependency_and_parent_edges(api) -> None:
    workspace_id, project_id = await _workspace(api)
    _as_user(api.app, "contributor")
    parent = _create(api, workspace_id, project_id, rank=1)
    child = _create(api, workspace_id, project_id, rank=2)
    base = f"/workspaces/{workspace_id}/backlog"

    assert (
        api.client.put(f"{base}/{child['item_id']}/dependencies/{parent['item_id']}").status_code
        == 204
    )
    deps = api.client.get(f"{base}/{child['item_id']}/dependencies").json()
    assert [d["item_id"] for d in deps] == [parent["item_id"]]
    dependents = api.client.get(f"{base}/{parent['item_id']}/dependents").json()
    assert [d["item_id"] for d in dependents] == [child["item_id"]]
    cycle = api.client.put(f"{base}/{parent['item_id']}/dependencies/{child['item_id']}")
    assert cycle.status_code == 409
    self_edge = api.client.put(f"{base}/{parent['item_id']}/dependencies/{parent['item_id']}")
    assert self_edge.status_code == 409

    moved = api.client.put(
        f"{base}/{child['item_id']}/parent",
        json={"expected_version": 1, "parent_item_id": parent["item_id"]},
    )
    assert moved.status_code == 200
    assert (moved.json()["parent_item_id"], moved.json()["version"]) == (parent["item_id"], 2)
    children = api.client.get(f"{base}/{parent['item_id']}/children").json()
    assert [c["item_id"] for c in children] == [child["item_id"]]
    stale = api.client.put(
        f"{base}/{child['item_id']}/parent",
        json={"expected_version": 1, "parent_item_id": None},
    )
    assert stale.status_code == 409
    assert stale.json()["current"]["version"] == 2

    assert (
        api.client.delete(f"{base}/{child['item_id']}/dependencies/{parent['item_id']}").status_code
        == 204
    )
    assert api.client.get(f"{base}/{child['item_id']}/dependencies").json() == []
    assert api.client.get(f"{base}/missing/children").status_code == 404


async def test_create_refuses_claim_fields_and_duplicate_external_key(api) -> None:
    workspace_id, project_id = await _workspace(api)
    _as_user(api.app, "contributor")
    base = f"/workspaces/{workspace_id}/backlog"

    claimed = api.client.post(base, json={"project_id": project_id, "title": "x", "fence_token": 3})
    assert claimed.status_code == 422
    _create(api, workspace_id, project_id, external_key="engine-001")
    duplicate = api.client.post(
        base, json={"project_id": project_id, "title": "x", "external_key": "engine-001"}
    )
    assert duplicate.status_code == 409


def test_backlog_routes_are_mounted_on_the_server() -> None:
    paths = {route.path for route in iter_effective_routes(server_app.routes)}
    assert "/workspaces/{workspace_id}/backlog" in paths
    assert "/v1/workspaces/{workspace_id}/backlog/{item_id}" in paths


async def test_backlog_routes_fail_closed_without_a_container_store() -> None:
    projects = InMemoryProjectScopeStore()
    workspaces = InMemoryWorkspaceStore(project_store=projects)
    workspace = await workspaces.create(creator_user_id="owner", name="Alpha")
    app = FastAPI()
    app.state.container = SimpleNamespace(project_scope_store=projects)
    app.include_router(workspace_api.router)
    workspace_api.configure_workspace_store(workspaces)
    _as_user(app, "owner")
    try:
        with TestClient(app) as client:
            response = client.get(f"/workspaces/{workspace.workspace_id}/backlog")
        assert response.status_code == 503
    finally:
        workspace_api.configure_workspace_store(None)


async def test_malformed_writes_are_422_or_404_not_500(api) -> None:
    workspace_id, project_id = await _workspace(api)
    _as_user(api.app, "contributor")
    item = _create(api, workspace_id, project_id)
    base = f"/workspaces/{workspace_id}/backlog"
    url = f"{base}/{item['item_id']}"

    for field in ("title", "rank", "status", "description", "paused", "acceptance_refs"):
        response = api.client.patch(url, json={"expected_version": 1, field: None})
        assert response.status_code == 422, (field, response.text)
    infinite = api.client.patch(
        url,
        content='{"expected_version": 1, "rank": 1e999}',
        headers={"content-type": "application/json"},
    )
    assert infinite.status_code == 422
    missing_parent = api.client.post(
        base, json={"project_id": project_id, "title": "x", "parent_item_id": "nope"}
    )
    assert missing_parent.status_code == 404
    listed = api.client.get(base)
    assert listed.status_code == 200
    assert [i["version"] for i in listed.json()] == [1]
