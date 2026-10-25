"""CONNECT proof: routes.projects is mounted on the live Conductor app."""

from __future__ import annotations

import pathlib
import sys
from typing import Any
from unittest.mock import AsyncMock, patch

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def test_projects_router_is_mounted_on_main_app() -> None:
    from fastapi.routing import APIRoute
    from main import app

    paths: set[str] = set()
    for route in app.routes:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            prefix = str(getattr(getattr(route, "include_context", None), "prefix", "") or "")
            for sub in getattr(inner, "routes", []):
                if isinstance(sub, APIRoute):
                    paths.add(prefix + sub.path)
        elif isinstance(route, APIRoute):
            paths.add(route.path)

    assert any(p == "/v1/projects" or p.startswith("/v1/projects/") for p in paths)
    assert "/v1/projects/{project_id}/scan" in paths


class TestProjectsAuthorizationScope:
    """PROTECTED_OPS + webhook carve-out for /v1/projects (#34 CONNECT)."""

    def test_mutating_project_paths_require_projects_write(self) -> None:
        from services.authorization import required_permission

        assert required_permission("POST", "/v1/projects") == "projects.write"
        assert required_permission("POST", "/v1/projects/proj-1/scan") == "projects.write"
        assert required_permission("POST", "/v1/projects/proj-1/deploy") == "projects.write"
        assert required_permission("DELETE", "/v1/projects/proj-1") == "projects.write"

    def test_external_build_webhook_is_not_session_scoped(self) -> None:
        from services.authorization import required_permission

        # Bearer EXTERNAL_BUILD_CALLBACK_TOKEN is checked in the route body.
        assert required_permission("POST", "/v1/projects/webhooks/external-build") is None
        assert required_permission("POST", "/v1/projects/webhooks/external-build/") is None


class TestTheProjectsScanActuallyScans:
    """Behavioral coverage for POST /v1/projects/{project_id}/scan (scan contract)."""

    def test_trigger_scan_runs_repo_scanner(self, admin_client: Any) -> None:
        project = {
            "id": "proj-1",
            "user_id": "admin",
            "repo_url": "https://github.com/example/repo.git",
            "branch": "main",
            "dockerfile_path": "Dockerfile",
            "status": "created",
        }
        scan = {"id": "scan-1", "project_id": "proj-1", "status": "running"}
        scan_result = {
            "status": "passed",
            "findings": [{"rule": "ok"}],
            "summary": {"files": 1},
        }

        with (
            patch("routes.projects._user_id", return_value="admin"),
            patch("routes.projects.onboard_db.get_project", new=AsyncMock(return_value=project)),
            patch("routes.projects.onboard_db.update_project", new=AsyncMock()),
            patch("routes.projects.onboard_db.create_scan", new=AsyncMock(return_value=scan)),
            patch("routes.projects.onboard_db.update_scan", new=AsyncMock()),
            patch("routes.projects._publish_event", new=AsyncMock()),
            patch(
                "routes.projects.repo_scanner.scan_repo",
                new=AsyncMock(return_value=scan_result),
            ) as scan_repo,
        ):
            response = admin_client.post("/v1/projects/proj-1/scan")

        assert response.status_code == 202
        body = response.json()
        assert body == {"scan_id": "scan-1", "status": "running"}
        scan_repo.assert_awaited_once_with(
            "https://github.com/example/repo.git",
            "main",
        )
