"""Controls are offered only where they can work (#190 review).

Retiring `usePmPoc()` exposed two controls that the POC branch had been
hiding for the wrong reason: Restart on engine-backed missions, which
`update_mission_status` refuses with a 409 whatever the deployment mode, and
bulk-clear on a backend with no bulk removal, where `clear_tasks` returns 0 and
the caller is told a clear succeeded. Both are now reported by the backend so
the UI can decide from capability rather than from deployment mode.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from models.schemas import Mission


class _Rec:
    id = "task-1"
    name = "n"
    description = "d"
    mission_status = "completed"
    progress = 1.0
    error = None
    started_at = None
    completed_at = None

    def __init__(self) -> None:
        self.created_at = datetime.now(UTC)


def test_an_engine_backed_mission_says_so() -> None:
    from routes.missions import _task_to_mission

    mission = _task_to_mission(_Rec())

    assert mission.metadata["engine_backed"] is True


def test_an_engine_backed_missions_status_is_refused(admin_client, monkeypatch) -> None:
    """The metadata is not decoration: the route really does refuse."""
    import routes.missions as missions_routes

    class _Engine:
        _backend = object()

        def get_task(self, _task_id: str, **_kw: Any) -> _Rec:
            return _Rec()

    monkeypatch.setattr(missions_routes, "get_engine", lambda: _Engine())

    r = admin_client.patch("/v1/tasks/task-1/status", json={"status": "pending"})

    assert r.status_code == 409


@pytest.mark.parametrize("has_remove_where", [True, False])
def test_clear_support_reflects_the_backend(has_remove_where: bool) -> None:
    from services.engine import EngineService

    class _Backend:
        pass

    class _Clearable:
        def remove_where(self, **_kw: Any) -> int:
            return 0

    svc = EngineService()
    svc._backend = _Clearable() if has_remove_where else _Backend()

    assert svc.supports_clear is has_remove_where


def test_clear_support_is_false_with_no_backend() -> None:
    from services.engine import EngineService

    assert EngineService().supports_clear is False


def test_health_reports_clear_support(admin_client) -> None:
    body = admin_client.get("/health").json()

    assert "task_clear_supported" in body
    assert isinstance(body["task_clear_supported"], bool)


class _EngineRecord:
    """A TaskRecord-like row whose owner differs per instance."""

    name = "engine mission"
    description = "d"
    progress = 0.5
    current_step = "reviewing"
    started_at = None
    completed_at = None

    def __init__(self, id: str, user_id: str, mission_status: str = "running") -> None:
        self.id = id
        self.user_id = user_id
        self.mission_status = mission_status
        self.created_at = datetime.now(UTC)


def _install_engine(monkeypatch: pytest.MonkeyPatch, records: list[_EngineRecord]) -> None:
    import routes.missions as routes_missions

    class _Engine:
        _backend = object()
        is_configured = True

        def list_tasks(self, *, user_id: str | None = None) -> list[_EngineRecord]:
            if user_id is None:
                return list(records)
            return [r for r in records if r.user_id == user_id]

        def get_task(self, task_id: str, *, user_id: str | None = None) -> _EngineRecord | None:
            for r in self.list_tasks(user_id=user_id):
                if r.id == task_id:
                    return r
            return None

    # main.py's router functions live in routes.missions (the app imports the
    # module under that name), so patching it is what the routes consult.
    monkeypatch.setattr(routes_missions, "get_engine", lambda: _Engine())


def test_an_engine_backed_mission_list_only_shows_the_callers_own_work(
    admin_client, monkeypatch
) -> None:
    """Two users behind one engine stay distinguishable in task visibility."""
    _install_engine(
        monkeypatch,
        [_EngineRecord("m-alice", "alice"), _EngineRecord("m-bob", "admin")],
    )

    body = admin_client.get("/v1/tasks").json()

    names = {m["id"] for m in body}
    assert names == {"m-bob"}


def test_an_engine_backed_mission_is_hidden_from_another_user(admin_client, monkeypatch) -> None:
    _install_engine(monkeypatch, [_EngineRecord("m-alice", "alice")])

    r = admin_client.get("/v1/tasks/m-alice")

    assert r.status_code == 404


def test_an_engine_backed_mission_projects_its_current_step(admin_client, monkeypatch) -> None:
    _install_engine(monkeypatch, [_EngineRecord("m-mine", "admin")])

    steps = admin_client.get("/v1/tasks/m-mine/steps").json()

    assert len(steps) == 1
    assert steps[0]["name"] == "reviewing"
    assert steps[0]["status"] == "running"


def test_engine_backed_mission_scoping_fails_closed_on_blank_ownership(
    admin_client, monkeypatch
) -> None:
    """An engine row with no attributable owner is nobody's mission."""
    _install_engine(monkeypatch, [_EngineRecord("m-orphan", "")])

    assert admin_client.get("/v1/tasks/m-orphan").status_code == 404
    assert admin_client.get("/v1/tasks/m-orphan/steps").status_code == 404


def test_creating_a_mission_through_the_engine_carries_the_caller(
    admin_client, monkeypatch
) -> None:
    """The route half of #1057: the submission names the authenticated user,
    and the created mission carries them as its owner."""
    import routes.missions as rm

    seen: dict[str, object] = {}

    class _Engine:
        _backend = object()
        is_configured = True

        async def submit_task(self, name, description, *, user_id, workspace_id=None):
            seen["user_id"] = user_id
            seen["workspace_id"] = workspace_id
            return _EngineRecord("m-new", user_id, mission_status="pending")

    monkeypatch.setattr(rm, "get_engine", lambda: _Engine())

    created = admin_client.post("/v1/tasks", json={"name": "engine mission"})

    assert created.status_code == 200
    assert created.json()["user_id"] == "admin"
    assert seen["user_id"] == "admin"
    assert seen["workspace_id"] is None


def test_creating_a_mission_in_an_unroutable_workspace_answers_501(
    admin_client, monkeypatch
) -> None:
    import routes.missions as rm
    from adapters.task_backend import WORKSPACE_NOT_ROUTABLE_DETAIL, WorkspaceNotRoutable

    class _Engine:
        _backend = object()
        is_configured = True

        async def submit_task(self, name, description, *, user_id, workspace_id=None):
            raise WorkspaceNotRoutable("no proof key")

    monkeypatch.setattr(rm, "get_engine", lambda: _Engine())

    r = admin_client.post("/v1/tasks", json={"name": "n"})

    assert r.status_code == 501
    assert r.json()["detail"] == WORKSPACE_NOT_ROUTABLE_DETAIL


def test_creating_a_mission_without_an_engine_stores_it_for_the_caller(
    admin_client, monkeypatch
) -> None:
    import routes.missions as rm
    import stores

    class _Engine:
        _backend = None
        is_configured = False

    monkeypatch.setattr(rm, "get_engine", lambda: _Engine())

    created = admin_client.post("/v1/tasks", json={"name": "store mission"})

    assert created.status_code == 200
    mission = created.json()
    assert mission["user_id"] == "admin"
    stores.missions.pop(mission["id"], None)
    stores.mission_steps.pop(mission["id"], None)


def test_deleting_an_engine_backed_mission_cancels_under_the_caller(
    admin_client, monkeypatch
) -> None:
    import routes.missions as rm

    seen: dict[str, object] = {}

    class _Engine:
        _backend = object()

        async def cancel_task(self, task_id, *, user_id=None):
            seen["task_id"] = task_id
            seen["user_id"] = user_id
            return True

    monkeypatch.setattr(rm, "get_engine", lambda: _Engine())

    r = admin_client.delete("/v1/tasks/m-mine")

    assert r.status_code == 204
    assert seen == {"task_id": "m-mine", "user_id": "admin"}


def test_deleting_an_engine_mission_that_will_not_cancel_is_404(admin_client, monkeypatch) -> None:
    import routes.missions as rm

    class _Engine:
        _backend = object()

        async def cancel_task(self, task_id, *, user_id=None):
            return False

    monkeypatch.setattr(rm, "get_engine", lambda: _Engine())

    assert admin_client.delete("/v1/tasks/m-mine").status_code == 404


def test_a_userless_request_is_refused_not_faked(admin_client, monkeypatch) -> None:
    """`_user_id` fails closed: no principal, no mission, 401."""
    from types import SimpleNamespace

    import routes.missions as rm
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as excinfo:
        rm._user_id(SimpleNamespace(state=SimpleNamespace(user=None)))

    assert excinfo.value.status_code == 401


def test_engine_backed_steps_fall_through_to_an_owned_store_mission(
    admin_client, monkeypatch
) -> None:
    """When the engine does not know the id, the owned store mission does."""
    from datetime import UTC

    import routes.missions as rm
    import stores

    class _Engine:
        _backend = object()
        is_configured = True

        def get_task(self, task_id, *, user_id=None):
            return None

    monkeypatch.setattr(rm, "get_engine", lambda: _Engine())

    mission = Mission(
        id="m-store",
        user_id="admin",
        name="stored",
        description="",
        status="pending",
        priority="medium",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    stores.missions["m-store"] = mission
    stores.mission_steps["m-store"] = []
    try:
        steps = admin_client.get("/v1/tasks/m-store/steps")
        assert steps.status_code == 200
        assert steps.json() == []
    finally:
        stores.missions.pop("m-store", None)
        stores.mission_steps.pop("m-store", None)


def test_a_store_mission_is_visible_to_its_owner_when_the_engine_misses(
    admin_client, monkeypatch
) -> None:
    import routes.missions as rm
    import stores

    class _Engine:
        _backend = object()
        is_configured = True

        def get_task(self, task_id, *, user_id=None):
            return None

    monkeypatch.setattr(rm, "get_engine", lambda: _Engine())
    mission = Mission(
        id="m-store-get",
        user_id="admin",
        name="stored",
        description="",
        status="pending",
        priority="medium",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    stores.missions["m-store-get"] = mission
    try:
        r = admin_client.get("/v1/tasks/m-store-get")
        assert r.status_code == 200
        assert r.json()["id"] == "m-store-get"
    finally:
        stores.missions.pop("m-store-get", None)


def test_deleting_a_store_mission_without_an_engine_backend(admin_client, monkeypatch) -> None:
    import routes.missions as rm
    import stores

    class _Engine:
        _backend = None

    monkeypatch.setattr(rm, "get_engine", lambda: _Engine())
    mission = Mission(
        id="m-store-del",
        user_id="admin",
        name="stored",
        description="",
        status="completed",
        priority="medium",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    stores.missions["m-store-del"] = mission
    stores.mission_steps["m-store-del"] = []
    try:
        r = admin_client.delete("/v1/tasks/m-store-del")
        assert r.status_code == 204
        assert "m-store-del" not in stores.missions
    finally:
        stores.missions.pop("m-store-del", None)
        stores.mission_steps.pop("m-store-del", None)
