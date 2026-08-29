from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maistro.workspaces import InMemoryWorkspaceStore
from maistro_server.api import workspaces as workspace_api
from maistro_server.api.auth import verify_api_key
from maistro_server.api.principal import AuthenticatedPrincipal


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(workspace_api.router)
    workspace_api.configure_workspace_store(InMemoryWorkspaceStore())
    principal = AuthenticatedPrincipal(
        user_id="alice",
        token="token-alice",
        roles=frozenset({"user"}),
    )
    app.dependency_overrides[verify_api_key] = lambda: principal
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    workspace_api.configure_workspace_store(None)


def test_whitespace_only_create_name_is_rejected(client: TestClient) -> None:
    response = client.post("/workspaces", json={"name": "   "})

    assert response.status_code == 422
    assert client.get("/workspaces").json() == []


def test_whitespace_only_update_name_is_rejected_without_mutation(client: TestClient) -> None:
    created = client.post("/workspaces", json={"name": "Stable"})
    assert created.status_code == 201
    workspace_id = created.json()["workspace_id"]

    response = client.patch(f"/workspaces/{workspace_id}", json={"name": "   "})

    assert response.status_code == 422
    fetched = client.get(f"/workspaces/{workspace_id}")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "Stable"
