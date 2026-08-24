"""A submission names its Workspace, and only a member may name it (#158).

Hive task Runs were all admitted into the deployment's default Workspace, so
two users in two workspaces produced Runs that were indistinguishable by scope.
The Workspace now travels with the submission. These tests hold the route half
of that: the parameter reaches the engine, a non-member is refused in the same
403 shape `routes/agents.py` uses for its own workspace-scoped writes, and a
submission that names no Workspace still succeeds with the default named
explicitly rather than inferred.
"""

from __future__ import annotations

from typing import Any

import pytest
import stores


@pytest.fixture(autouse=True)
def _clear_state():
    to_clear = (stores.workspaces, stores.work_item_drafts, stores.program_contexts, stores.agents)
    for store in to_clear:
        for key in list(store.keys()):
            store.pop(key, None)
    yield
    for store in to_clear:
        for key in list(store.keys()):
            store.pop(key, None)


class _FakeTaskRecord:
    id = "task-1"
    name = "n"
    description = "d"
    mission_status = "pending"
    progress = 0.0
    current_step = ""
    started_at = None
    completed_at = None

    def __init__(self) -> None:
        from datetime import UTC, datetime

        self.created_at = datetime.now(UTC)


class _CapturingEngine:
    """Stands in for EngineService, recording what the route asked for."""

    is_configured = True

    def __init__(self) -> None:
        self._backend = object()
        self.calls: list[dict[str, Any]] = []

    async def submit_task(self, *args: Any, **kwargs: Any) -> _FakeTaskRecord:
        self.calls.append(kwargs)
        return _FakeTaskRecord()


def _create_workspace(client, persona_template_id: str = "pm_fleet") -> str:
    r = client.post(
        "/v1/workspaces",
        json={"persona_template_id": persona_template_id, "name": "Test WS"},
    )
    assert r.status_code == 201
    return r.json()["id"]


# --- missions (POST /v1/tasks) -------------------------------------------


def test_a_members_submission_carries_its_workspace(admin_client, monkeypatch) -> None:
    import routes.missions as missions_routes

    engine = _CapturingEngine()
    monkeypatch.setattr(missions_routes, "get_engine", lambda: engine)
    ws_id = _create_workspace(admin_client)

    r = admin_client.post(f"/v1/tasks?workspace_id={ws_id}", json={"name": "Ship it"})

    assert r.status_code == 200
    assert engine.calls[0]["workspace_id"] == ws_id


def test_a_non_members_submission_is_refused_with_403(authed_client, admin_client) -> None:
    ws_id = _create_workspace(admin_client)

    r = authed_client.post(f"/v1/tasks?workspace_id={ws_id}", json={"name": "Ship it"})

    assert r.status_code == 403
    assert r.json()["detail"] == "only a workspace member can submit work to it"


def test_an_unknown_workspace_is_refused_rather_than_falling_back(admin_client) -> None:
    # Not 404: the caller is not a member of a workspace that does not exist,
    # and answering "no such workspace" would let anyone probe which ids are
    # real -- the same reason routes/agents.py answers 403 here.
    r = admin_client.post("/v1/tasks?workspace_id=nope", json={"name": "Ship it"})

    assert r.status_code == 403


def test_an_unscoped_submission_names_the_default_explicitly(admin_client, monkeypatch) -> None:
    import routes.missions as missions_routes

    engine = _CapturingEngine()
    monkeypatch.setattr(missions_routes, "get_engine", lambda: engine)

    r = admin_client.post("/v1/tasks", json={"name": "Ship it"})

    assert r.status_code == 200
    # Present and None, not absent: the route states "no Workspace named" and
    # lets the engine's default answer it, rather than omitting the argument
    # and leaving the answer to whatever the call chain happens to default to.
    assert engine.calls[0]["workspace_id"] is None


# --- work items (POST /v1/work-items/{id}/confirm) ------------------------


def _ready_draft(client, ws_id: str) -> str:
    r = client.post(
        f"/v1/work-items/suggest?workspace_id={ws_id}",
        json={"work_type": "epic", "reason": "test"},
    )
    assert r.status_code == 200
    draft_id = r.json()["draft"]["id"]
    client.post(
        f"/v1/work-items/{draft_id}/clarify",
        json={
            "answers": {
                "summary": "Do the thing",
                "description": "Because reasons",
                "parent_key": "X-1",
            }
        },
    )
    return draft_id


def test_a_draft_cannot_be_suggested_without_a_workspace(admin_client) -> None:
    """The one #158 behaviour #129 changed, and deliberately.

    An unscoped draft used to be legal, and its confirmation submitted with
    `workspace_id=None`. There is no roster to resolve its agent against, so
    what it produced was a Run naming an agent from a global fleet the
    deployment-wide POC flag synthesised. With that flag gone the draft has
    to name a workspace up front. `/v1/tasks` is untouched -- an unscoped
    *task* submission is still legal and still names the default explicitly.
    """
    r = admin_client.post("/v1/work-items/suggest", json={"work_type": "epic", "reason": "test"})

    assert r.status_code == 404


# --- the backend that cannot honour a Workspace ---------------------------


async def test_the_http_backend_refuses_a_named_workspace() -> None:
    """maistro-server binds one Workspace per instance (ADR-019/ADR-068).

    Refusing is the point: admitting anyway would file the work in that
    server's default Project while the caller was told it went to theirs,
    which is precisely the silent scope loss this issue removes.
    """
    from adapters.task_backend import MaistroServerTaskBackend, WorkspaceNotRoutable

    from maistro.tasks.models import TaskCreate

    backend = MaistroServerTaskBackend(base_url="http://tasks.invalid", api_key=None)

    with pytest.raises(WorkspaceNotRoutable):
        await backend.submit(TaskCreate(description="d"), user_id="u", workspace_id="w-alpha")


async def test_the_http_backend_still_accepts_an_unscoped_submission(monkeypatch) -> None:
    """And the refusal must not have cost the default path anything."""
    import adapters.task_backend as backend_mod

    from maistro.tasks.models import TaskCreate

    posted: dict[str, Any] = {}

    class _Response:
        status_code = 202

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "task": {
                    "task_id": "t-1",
                    "status": "queued",
                    "description": "d",
                    # nosec B108 — the API contract's workspace mount root, not a
                    # temp file this test creates.
                    "workspace": "/tmp/maistro-workspace",  # nosec B108
                    "tier": 2,
                    "created_at": "2026-01-01T00:00:00Z",
                }
            }

    class _Client:
        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

        async def post(self, url: str, **kwargs: Any) -> _Response:
            posted["url"] = url
            return _Response()

    monkeypatch.setattr(backend_mod, "shared_client", lambda **kw: _Client())
    backend = backend_mod.MaistroServerTaskBackend(base_url="http://tasks.invalid", api_key=None)

    rec = await backend.submit(TaskCreate(description="d"), user_id="u")

    assert rec.id == "t-1"
    assert posted["url"].endswith("/tasks")


# --- review findings ------------------------------------------------------


def test_confirm_files_the_run_where_the_draft_was_suggested(admin_client, monkeypatch) -> None:
    """The frontend confirms without a query parameter.

    Reading the scope from the request would file a workspace-scoped draft in
    the default Project while its program context came from the workspace.
    """
    import routes.work_items as work_items_routes

    engine = _CapturingEngine()
    ws_id = _create_workspace(admin_client)
    draft_id = _ready_draft(admin_client, ws_id)
    monkeypatch.setattr(work_items_routes, "get_engine", lambda: engine)

    r = admin_client.post(f"/v1/work-items/{draft_id}/confirm")

    assert r.status_code == 200
    assert engine.calls[0]["workspace_id"] == ws_id
    assert engine.calls[0]["program_context"]["project_id"] == ws_id


def test_confirm_refuses_a_workspace_the_draft_was_not_suggested_under(
    admin_client, monkeypatch
) -> None:
    import routes.work_items as work_items_routes

    engine = _CapturingEngine()
    first = _create_workspace(admin_client)
    second = _create_workspace(admin_client)
    draft_id = _ready_draft(admin_client, first)
    monkeypatch.setattr(work_items_routes, "get_engine", lambda: engine)

    r = admin_client.post(f"/v1/work-items/{draft_id}/confirm?workspace_id={second}")

    assert r.status_code == 409
    assert engine.calls == []


def test_confirm_refuses_a_non_member_before_the_pm_gate(
    authed_client, admin_client, monkeypatch
) -> None:
    """403, not the 404 the capability gate would have answered first."""
    ws_id = _create_workspace(admin_client)

    r = authed_client.post(f"/v1/work-items/does-not-matter/confirm?workspace_id={ws_id}")

    assert r.status_code == 403
