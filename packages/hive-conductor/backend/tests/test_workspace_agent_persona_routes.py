"""HTTP + Agent-tool surface for Workspace Agent persona swap (#2277).

Identity/concurrency remain in `test_workspace_agent_identity.py`. This suite
pins the public GET/PUT door, fail-closed authz, and tool/API parity on the
same durable row.
"""

from __future__ import annotations

from typing import Any

import pytest
import stores
from fastapi.testclient import TestClient
from main import app
from services import chat_completion, workspace_agent
from services.chat_completion import _tool_set_workspace_agent_persona


def _create_workspace(admin_client: TestClient, name: str = "Agent persona WS") -> str:
    r = admin_client.post("/v1/workspaces", json={"persona_template_id": "pm_fleet", "name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _add_member(admin_client: TestClient, workspace_id: str, user_id: str, role: str) -> None:
    r = admin_client.post(
        f"/v1/workspaces/{workspace_id}/members", json={"user_id": user_id, "role": role}
    )
    assert r.status_code == 200, r.text


def _set_tool_workspace(workspace_id: str | None) -> Any:
    return chat_completion._chat_workspace_id.set(workspace_id)


@pytest.fixture(autouse=True)
def _clean_agents():
    before = set(stores.agents.keys())
    yield
    for key in set(stores.agents.keys()) - before:
        stores.agents.pop(key, None)


def test_anonymous_callers_get_401(admin_client: TestClient) -> None:
    ws = _create_workspace(admin_client)
    anon = TestClient(app)
    assert anon.get(f"/v1/workspaces/{ws}/agent").status_code == 401
    assert (
        anon.put(f"/v1/workspaces/{ws}/agent", json={"persona_template_id": "delivery"}).status_code
        == 401
    )


def test_non_member_cannot_read_or_write(admin_client, authed_client) -> None:
    ws = _create_workspace(admin_client)
    # GET: membership 404 (no existence oracle).
    assert authed_client.get(f"/v1/workspaces/{ws}/agent").status_code == 404
    # PUT: daily user lacks `workspaces.write`, so the scope gate refuses
    # before membership — same shape as tool-bindings (#2277 / #1417).
    assert (
        authed_client.put(
            f"/v1/workspaces/{ws}/agent", json={"persona_template_id": "delivery"}
        ).status_code
        == 403
    )


def test_viewer_reads_but_cannot_swap(admin_client, authed_client) -> None:
    ws = _create_workspace(admin_client)
    _add_member(admin_client, ws, "user", "viewer")
    got = authed_client.get(f"/v1/workspaces/{ws}/agent")
    assert got.status_code == 200, got.text
    assert got.json()["persona_template_id"] == "program_manager"
    refused = authed_client.put(
        f"/v1/workspaces/{ws}/agent", json={"persona_template_id": "delivery"}
    )
    assert refused.status_code == 403


def test_owner_put_keeps_agent_id_and_created_at(admin_client) -> None:
    ws = _create_workspace(admin_client)
    first = admin_client.get(f"/v1/workspaces/{ws}/agent")
    assert first.status_code == 200, first.text
    body = first.json()
    agent_id = body["workspace_agent_id"]
    created_at = body["created_at"]
    assert body["persona_template_id"] == "program_manager"

    put = admin_client.put(f"/v1/workspaces/{ws}/agent", json={"persona_template_id": "delivery"})
    assert put.status_code == 200, put.text
    after = put.json()
    assert after["workspace_agent_id"] == agent_id
    assert after["created_at"] == created_at
    assert after["persona_template_id"] == "delivery"

    again = admin_client.get(f"/v1/workspaces/{ws}/agent").json()
    assert again["workspace_agent_id"] == agent_id
    assert again["persona_template_id"] == "delivery"


def test_unshaped_persona_is_422(admin_client) -> None:
    ws = _create_workspace(admin_client)
    r = admin_client.put(
        f"/v1/workspaces/{ws}/agent", json={"persona_template_id": "Not A Template"}
    )
    assert r.status_code == 422


def test_agent_tool_matches_the_route(admin_client) -> None:
    ws = _create_workspace(admin_client)
    via_api = admin_client.get(f"/v1/workspaces/{ws}/agent").json()
    token = _set_tool_workspace(ws)
    try:
        result = asyncio_run(
            _tool_set_workspace_agent_persona(
                {"persona_template_id": "risk_dependency"}, "admin", None
            )
        )
    finally:
        chat_completion._chat_workspace_id.reset(token)

    assert result["swapped"] is True
    assert result["workspace_agent_id"] == via_api["workspace_agent_id"]
    assert result["persona_template_id"] == "risk_dependency"
    # created_at is the same instant; JSON may emit Z vs +00:00.
    assert result["created_at"].startswith(via_api["created_at"].rstrip("Z"))

    via_api_again = admin_client.get(f"/v1/workspaces/{ws}/agent").json()
    assert via_api_again["persona_template_id"] == "risk_dependency"
    assert via_api_again["workspace_agent_id"] == via_api["workspace_agent_id"]
    assert (
        workspace_agent.persona_template_id(stores.agents[via_api["workspace_agent_id"]])
        == "risk_dependency"
    )


def test_get_maps_resolve_failures(admin_client, monkeypatch: pytest.MonkeyPatch) -> None:
    from routes import workspaces as ws_routes

    ws = _create_workspace(admin_client)

    async def _missing(*_a: object, **_k: object) -> Any:
        raise workspace_agent.WorkspaceNotFound(ws)

    monkeypatch.setattr(ws_routes, "resolve_workspace_agent", _missing)
    assert admin_client.get(f"/v1/workspaces/{ws}/agent").status_code == 404

    async def _conflict(*_a: object, **_k: object) -> Any:
        raise workspace_agent.WorkspaceAgentConflict("id held by another Workspace")

    monkeypatch.setattr(ws_routes, "resolve_workspace_agent", _conflict)
    assert admin_client.get(f"/v1/workspaces/{ws}/agent").status_code == 409


def test_put_handler_authz_and_service_failures(
    admin_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reach handler-local 404/403/409 after the scope gate has already passed."""
    from routes import workspaces as ws_routes

    ws = _create_workspace(admin_client)

    async def _invisible(*_a: object, **_k: object) -> None:
        return None

    monkeypatch.setattr(ws_routes, "visible_view", _invisible)
    assert (
        admin_client.put(
            f"/v1/workspaces/{ws}/agent", json={"persona_template_id": "delivery"}
        ).status_code
        == 404
    )

    async def _visible(*_a: object, **_k: object) -> object:
        return object()

    async def _editor(*_a: object, **_k: object) -> str:
        return "editor"

    monkeypatch.setattr(ws_routes, "visible_view", _visible)
    monkeypatch.setattr(ws_routes, "member_role", _editor)
    refused = admin_client.put(
        f"/v1/workspaces/{ws}/agent", json={"persona_template_id": "delivery"}
    )
    assert refused.status_code == 403
    assert "owner" in refused.json()["detail"]

    async def _owner(*_a: object, **_k: object) -> str:
        return "owner"

    monkeypatch.setattr(ws_routes, "member_role", _owner)

    async def _missing(*_a: object, **_k: object) -> Any:
        raise workspace_agent.WorkspaceNotFound(ws)

    monkeypatch.setattr(ws_routes, "set_workspace_agent_persona", _missing)
    assert (
        admin_client.put(
            f"/v1/workspaces/{ws}/agent", json={"persona_template_id": "delivery"}
        ).status_code
        == 404
    )

    async def _conflict(*_a: object, **_k: object) -> Any:
        raise workspace_agent.WorkspaceAgentConflict("id held by another Workspace")

    monkeypatch.setattr(ws_routes, "set_workspace_agent_persona", _conflict)
    assert (
        admin_client.put(
            f"/v1/workspaces/{ws}/agent", json={"persona_template_id": "delivery"}
        ).status_code
        == 409
    )


def test_agent_tool_error_paths(admin_client, monkeypatch: pytest.MonkeyPatch) -> None:
    from services import workspace_authority

    # No Workspace context on the turn.
    token = _set_tool_workspace(None)
    try:
        bare = asyncio_run(
            _tool_set_workspace_agent_persona({"persona_template_id": "delivery"}, "admin", None)
        )
    finally:
        chat_completion._chat_workspace_id.reset(token)
    assert bare["swapped"] is False
    assert "Workspace context" in bare["error"]

    ws = _create_workspace(admin_client)
    token = _set_tool_workspace(ws)
    try:

        async def _invisible(*_a: object, **_k: object) -> None:
            return None

        monkeypatch.setattr(workspace_authority, "visible_view", _invisible)
        missing = asyncio_run(
            _tool_set_workspace_agent_persona({"persona_template_id": "delivery"}, "admin", None)
        )
        assert missing == {"swapped": False, "error": "workspace not found"}

        async def _visible(*_a: object, **_k: object) -> object:
            return object()

        async def _editor(*_a: object, **_k: object) -> str:
            return "editor"

        monkeypatch.setattr(workspace_authority, "visible_view", _visible)
        monkeypatch.setattr(workspace_authority, "member_role", _editor)
        refused = asyncio_run(
            _tool_set_workspace_agent_persona({"persona_template_id": "delivery"}, "admin", None)
        )
        assert refused["swapped"] is False
        assert "owner" in refused["error"]

        async def _owner(*_a: object, **_k: object) -> str:
            return "owner"

        monkeypatch.setattr(workspace_authority, "member_role", _owner)

        async def _bad_value(*_a: object, **_k: object) -> Any:
            raise ValueError("unknown persona template: nope")

        monkeypatch.setattr(workspace_agent, "set_workspace_agent_persona", _bad_value)
        bad = asyncio_run(
            _tool_set_workspace_agent_persona({"persona_template_id": "nope"}, "admin", None)
        )
        assert bad["swapped"] is False
        assert "unknown persona" in bad["error"]

        async def _gone(*_a: object, **_k: object) -> Any:
            raise workspace_agent.WorkspaceNotFound(ws)

        monkeypatch.setattr(workspace_agent, "set_workspace_agent_persona", _gone)
        gone = asyncio_run(
            _tool_set_workspace_agent_persona({"persona_template_id": "delivery"}, "admin", None)
        )
        assert gone == {"swapped": False, "error": "workspace not found"}

        async def _conflict(*_a: object, **_k: object) -> Any:
            raise workspace_agent.WorkspaceAgentConflict("conflict")

        monkeypatch.setattr(workspace_agent, "set_workspace_agent_persona", _conflict)
        conflict = asyncio_run(
            _tool_set_workspace_agent_persona({"persona_template_id": "delivery"}, "admin", None)
        )
        assert conflict == {"swapped": False, "error": "conflict"}
    finally:
        chat_completion._chat_workspace_id.reset(token)


def asyncio_run(coro: Any) -> Any:
    import asyncio

    return asyncio.run(coro)
