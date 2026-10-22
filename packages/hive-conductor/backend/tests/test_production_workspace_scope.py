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
    DELEGATION_HEADER,
    WORKSPACE_ID_HEADER,
    WORKSPACE_SCOPE_SIGNATURE_HEADER,
    sign_workspace_scope,
    verify_delegation_context,
)
from maistro.tasks.models import TaskCreate

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

SCOPE_KEY = "test-only-workspace-scope-key"
DELEGATION_KEY = "test-only-task-delegation-key"


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
        delegation_key=DELEGATION_KEY,
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
    assert DELEGATION_HEADER in seen_headers
    context = verify_delegation_context(seen_headers[DELEGATION_HEADER], DELEGATION_KEY)
    assert context.service_principal == "conductor"
    assert context.originating_principal == "user-1"


async def test_shared_bridge_keeps_two_authenticated_user_tasks_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the real adapter against the real server ASGI boundary."""
    task_backend_module = _backend_module()
    from unittest.mock import patch

    from fastapi.testclient import TestClient
    from main import app as hive_app
    from services.engine import EngineService

    from maistro.config.settings import get_settings
    from maistro.tasks.queue import TaskQueue
    from maistro_server.main import app as server_app

    monkeypatch.setenv("API_KEYS", '["conductor:service-secret"]')
    monkeypatch.setenv("TASK_DELEGATION_KEY", DELEGATION_KEY)
    get_settings.cache_clear()

    queue_module = importlib.import_module("maistro.tasks.queue")
    previous_queue = queue_module._queue
    queue_module._queue = TaskQueue()

    @asynccontextmanager
    async def _server_client(*, timeout: float):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server_app),
            base_url="http://maistro-server",
            timeout=timeout,
        ) as client:
            yield client

    monkeypatch.setattr(task_backend_module, "shared_client", _server_client)
    backend = task_backend_module.MaistroServerTaskBackend(
        base_url="http://maistro-server",
        api_key="service-secret",
        delegation_key=DELEGATION_KEY,
        service_principal="conductor",
    )

    try:
        # Go through the real Hive session-bound route, rather than calling the
        # adapter with a caller-supplied identity. The body attempts to name a
        # different user and must not affect the bridge assertion.
        alice_client = TestClient(hive_app)
        bob_client = TestClient(hive_app)
        for client, username, password in (
            (alice_client, "testuser", "testpass"),
            (bob_client, "testadmin", "adminpass"),
        ):
            logged_in = client.post(
                "/v1/auth/login",
                json={"username": username, "password": password},
            )
            assert logged_in.status_code == 200

        engine = EngineService()
        engine._backend = backend
        with patch("services.engine._singleton", engine):
            alice_response = alice_client.post(
                "/v1/tasks",
                json={"name": "Alice work", "user_id": "bob"},
            )
            bob_response = bob_client.post(
                "/v1/tasks",
                json={"name": "Bob work", "user_id": "alice"},
            )
        assert alice_response.status_code == 200
        assert bob_response.status_code == 200
        alice_id = alice_response.json()["id"]
        bob_id = bob_response.json()["id"]

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server_app),
            base_url="http://maistro-server",
        ) as client:
            alice_headers = backend._headers(user_id="user")
            bob_headers = backend._headers(user_id="admin")
            own = await client.get(f"/tasks/{alice_id}", headers=alice_headers)
            cross = await client.get(f"/tasks/{alice_id}", headers=bob_headers)
            mutate = await client.delete(f"/tasks/{alice_id}", headers=bob_headers)
            bob_own = await client.get(f"/tasks/{bob_id}", headers=bob_headers)

        assert own.status_code == 200
        assert bob_own.status_code == 200
        assert own.json()["user_id"] == "user"
        assert bob_own.json()["user_id"] == "admin"
        assert own.json()["service_principal_id"] == "conductor"
        assert cross.status_code == 404
        assert mutate.status_code == 404
    finally:
        queue_module._queue = previous_queue
        get_settings.cache_clear()


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

    with pytest.raises(ValueError, match="workspace_id must be a non-empty string"):
        await backend.submit(
            TaskCreate(description="ship it"),
            user_id="user-1",
            workspace_id="   ",
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
    backend = backend_type(
        base_url="http://maistro-server",
        api_key=None,
        workspace_scope_key="",
        delegation_key=DELEGATION_KEY,
    )

    await backend.submit(TaskCreate(description="ship it"), user_id="user-1")

    assert WORKSPACE_ID_HEADER not in seen_headers
    assert WORKSPACE_SCOPE_SIGNATURE_HEADER not in seen_headers
