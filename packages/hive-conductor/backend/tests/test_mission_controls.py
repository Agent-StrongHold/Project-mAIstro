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
