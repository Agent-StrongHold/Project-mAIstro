"""Workspace BacklogItem history API (#101): member reads, outsider 404s."""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.workspaces import InMemoryWorkspaceStore, WorkspaceRole
from maistro.workspaces.backlog_history import (
    BacklogHistoryEvent,
    BacklogHistoryEventKind,
    InMemoryBacklogHistoryStore,
    recording,
)
from maistro_server.api import workspaces as workspace_api
from maistro_server.api.auth import verify_api_key
from maistro_server.api.backlog_history import list_item_history
from maistro_server.api.principal import Principal
from maistro_server.api.route_table import iter_effective_routes
from maistro_server.main import app as server_app


def _as_user(app: FastAPI, user_id: str) -> None:
    principal = Principal(
        user_id=user_id, roles=frozenset({"user"})
    )
    app.dependency_overrides[verify_api_key] = lambda: principal


class _Api(SimpleNamespace):
    app: FastAPI
    client: TestClient
    workspaces: InMemoryWorkspaceStore
    projects: InMemoryProjectScopeStore
    history: InMemoryBacklogHistoryStore


@pytest.fixture
async def api() -> AsyncIterator[_Api]:
    projects = InMemoryProjectScopeStore()
    workspaces = InMemoryWorkspaceStore(project_store=projects)
    history = InMemoryBacklogHistoryStore()
    app = FastAPI()
    app.state.container = SimpleNamespace(
        project_scope_store=projects,
        backlog_history_store=history,
    )
    app.include_router(workspace_api.router)
    workspace_api.configure_workspace_store(workspaces)
    client = TestClient(app)
    try:
        yield _Api(
            app=app, client=client, workspaces=workspaces, projects=projects, history=history
        )
    finally:
        client.close()
        app.dependency_overrides.clear()
        workspace_api.configure_workspace_store(None)


async def _workspace(api: _Api) -> tuple[str, str]:
    workspace = await api.workspaces.create(creator_user_id="owner", name="Alpha")
    await api.workspaces.set_membership(
        workspace.workspace_id, user_id="member", role=WorkspaceRole.MEMBER
    )
    root = await api.projects.root_for_workspace(workspace.workspace_id)
    return workspace.workspace_id, root.project_id


async def test_members_replay_the_full_history_oldest_first(api: _Api) -> None:
    workspace_id, project_id = await _workspace(api)
    subject = recording.BacklogSubject(
        workspace_id=workspace_id, project_id=project_id, item_id="item-1"
    )
    store = api.history
    await recording.item_recorded(store, subject, source_ref="spec:SPEC-177")
    await recording.progress_noted(store, subject, note="1 of 2 checks", actor_agent_id="agent-1")
    closed = await recording.closure_recorded(
        store,
        subject,
        evidence_refs=("spec:SPEC-177#AC-1",),
        to_status="implemented",
    )

    _as_user(api.app, "member")
    response = api.client.get(f"/workspaces/{workspace_id}/backlog/item-1/history")
    assert response.status_code == 200, response.text
    events = response.json()
    assert [event["kind"] for event in events] == [
        "item_recorded",
        "progress_noted",
        "closure_recorded",
    ]
    assert [event["sequence"] for event in events] == [1, 2, 3]
    assert events[0]["source_ref"] == "spec:SPEC-177"
    assert events[1]["actor_agent_id"] == "agent-1"
    assert events[2]["evidence_refs"] == ["spec:SPEC-177#AC-1"]

    filtered = api.client.get(
        f"/workspaces/{workspace_id}/backlog/item-1/history",
        params={"kind": BacklogHistoryEventKind.CLOSURE_RECORDED.value},
    )
    assert [event["event_id"] for event in filtered.json()] == [closed.event_id]


async def test_non_members_and_unknown_items_are_indistinguishable(api: _Api) -> None:
    workspace_id, project_id = await _workspace(api)
    await recording.item_recorded(
        api.history,
        recording.BacklogSubject(
            workspace_id=workspace_id, project_id=project_id, item_id="item-1"
        ),
    )

    _as_user(api.app, "stranger")
    outsider = api.client.get(f"/workspaces/{workspace_id}/backlog/item-1/history")
    assert outsider.status_code == 404

    _as_user(api.app, "member")
    missing = api.client.get(f"/workspaces/{workspace_id}/backlog/no-such-item/history")
    assert missing.status_code == 200
    assert missing.json() == []


async def test_an_unconfigured_history_store_answers_503(api: _Api) -> None:
    """A Container with no BacklogItem history store is a 503, not a crash."""
    workspace_id, _project_id = await _workspace(api)
    api.app.state.container = SimpleNamespace(project_scope_store=api.projects)
    _as_user(api.app, "member")
    response = api.client.get(f"/workspaces/{workspace_id}/backlog/item-1/history")
    assert response.status_code == 503, response.text
    assert "No BacklogItem history store" in response.json()["detail"]


def test_the_history_route_is_mounted_on_the_production_app() -> None:
    paths = {route.path for route in iter_effective_routes(server_app.routes)}
    assert "/v1/workspaces/{workspace_id}/backlog/{item_id}/history" in paths


def test_route_handler_is_the_registered_endpoint() -> None:
    """The route's endpoint is the named handler, so vulture-visible usage and
    production behavior cannot drift apart."""
    routes = [
        route
        for route in iter_effective_routes(workspace_api.router.routes)
        if getattr(route, "path", "") == "/workspaces/{workspace_id}/backlog/{item_id}/history"
    ]
    assert len(routes) == 1
    assert routes[0].endpoint is list_item_history  # type: ignore[attr-defined]


def test_history_events_serialize_for_the_wire() -> None:
    event = BacklogHistoryEvent(
        workspace_id="ws-a",
        project_id="p-1",
        item_id="item-1",
        kind=BacklogHistoryEventKind.ITEM_RECORDED,
    )
    payload = event.model_dump(mode="json")
    assert payload["kind"] == "item_recorded"
    assert payload["occurred_at"].endswith("+00:00") or payload["occurred_at"].endswith("Z")
