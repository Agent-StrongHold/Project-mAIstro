"""Production Hive task submission preserves canonical Workspace scope (#234)."""

from __future__ import annotations

import importlib
import pathlib
import sys
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest

from maistro.tasks.http_contract import (
    WORKSPACE_ID_HEADER,
    WORKSPACE_SCOPE_SIGNATURE_HEADER,
    sign_workspace_scope,
)
from maistro.tasks.models import TaskCreate

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

SCOPE_KEY = "test-only-workspace-scope-key"


def _backend_module() -> Any:
    return importlib.import_module("adapters.task_backend")


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


async def test_named_workspace_crosses_the_production_http_boundary(
    monkeypatch,
) -> None:
    task_backend_module = _backend_module()
    backend_type = task_backend_module.MaistroServerTaskBackend
    seen_headers: dict[str, str] = {}

    class _Client:
        async def post(
            self,
            url: str,
            *,
            headers: dict[str, str],
            json: object,
        ) -> httpx.Response:
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
    backend = backend_type(
        base_url="http://maistro-server",
        api_key="secret",
        workspace_scope_key=SCOPE_KEY,
    )

    record = await backend.submit(
        TaskCreate(description="ship it"),
        user_id="user-1",
        workspace_id="workspace-a",
    )

    assert record.id == "srv-1"
    assert seen_headers[WORKSPACE_ID_HEADER] == "workspace-a"
    assert seen_headers[WORKSPACE_SCOPE_SIGNATURE_HEADER] == sign_workspace_scope(
        "workspace-a", SCOPE_KEY
    )
    assert seen_headers["Authorization"] == "Bearer secret"


async def test_named_workspace_fails_closed_without_scope_proof_key() -> None:
    task_backend_module = _backend_module()
    backend = task_backend_module.MaistroServerTaskBackend(
        base_url="http://maistro-server",
        api_key="secret",
        workspace_scope_key="",
    )

    with pytest.raises(task_backend_module.WorkspaceNotRoutable):
        await backend.submit(
            TaskCreate(description="ship it"),
            user_id="user-1",
            workspace_id="workspace-a",
        )


async def test_unscoped_submission_does_not_fabricate_workspace_scope(
    monkeypatch,
) -> None:
    task_backend_module = _backend_module()
    backend_type = task_backend_module.MaistroServerTaskBackend
    seen_headers: dict[str, str] = {}

    class _Client:
        async def post(
            self,
            url: str,
            *,
            headers: dict[str, str],
            json: object,
        ) -> httpx.Response:
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
    backend = backend_type(base_url="http://maistro-server", api_key=None, workspace_scope_key="")

    await backend.submit(TaskCreate(description="ship it"), user_id="user-1")

    assert WORKSPACE_ID_HEADER not in seen_headers
    assert WORKSPACE_SCOPE_SIGNATURE_HEADER not in seen_headers
