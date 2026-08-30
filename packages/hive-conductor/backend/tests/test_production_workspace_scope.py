"""Production Hive task submission preserves canonical Workspace scope (#234)."""

from __future__ import annotations

import pathlib
import sys
from contextlib import asynccontextmanager
from typing import Any

import httpx

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from adapters import task_backend as task_backend_module  # noqa: E402
from adapters.task_backend import MaistroServerTaskBackend  # noqa: E402
from maistro.tasks.http_contract import WORKSPACE_ID_HEADER  # noqa: E402
from maistro.tasks.models import TaskCreate  # noqa: E402


def _task_body() -> dict[str, Any]:
    return {
        "task_id": "srv-1",
        "status": "queued",
        "description": "ship it",
        "workspace": "/tmp/maistro-workspace",  # nosec B108 -- TaskCreate fixture
        "tier": 2,
        "phase": "queued",
        "progress": {"subtasks": 0, "completed": 0, "current": ""},
        "result": None,
        "created_at": "2026-08-30T00:00:00Z",
        "started_at": None,
        "completed_at": None,
    }


async def test_named_workspace_crosses_the_production_http_boundary(monkeypatch) -> None:
    seen_headers: dict[str, str] = {}

    class _Client:
        async def post(self, url: str, *, headers: dict[str, str], json: object) -> httpx.Response:
            del json
            seen_headers.update(headers)
            return httpx.Response(
                202,
                request=httpx.Request("POST", url),
                json={"task_id": "srv-1", "status": "queued", "task": _task_body()},
            )

    @asynccontextmanager
    async def _client(*, timeout: float):
        assert timeout == 30.0
        yield _Client()

    monkeypatch.setattr(task_backend_module, "shared_client", _client)
    backend = MaistroServerTaskBackend(base_url="http://maistro-server", api_key="secret")

    record = await backend.submit(
        TaskCreate(description="ship it"),
        user_id="user-1",
        workspace_id="workspace-a",
    )

    assert record.id == "srv-1"
    assert seen_headers[WORKSPACE_ID_HEADER] == "workspace-a"
    assert seen_headers["Authorization"] == "Bearer secret"


async def test_unscoped_submission_does_not_fabricate_a_workspace_header(monkeypatch) -> None:
    seen_headers: dict[str, str] = {}

    class _Client:
        async def post(self, url: str, *, headers: dict[str, str], json: object) -> httpx.Response:
            del json
            seen_headers.update(headers)
            return httpx.Response(
                202,
                request=httpx.Request("POST", url),
                json={"task_id": "srv-1", "status": "queued", "task": _task_body()},
            )

    @asynccontextmanager
    async def _client(*, timeout: float):
        assert timeout == 30.0
        yield _Client()

    monkeypatch.setattr(task_backend_module, "shared_client", _client)
    backend = MaistroServerTaskBackend(base_url="http://maistro-server", api_key=None)

    await backend.submit(TaskCreate(description="ship it"), user_id="user-1")

    assert WORKSPACE_ID_HEADER not in seen_headers
