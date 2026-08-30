"""POST /tasks honors explicit Workspace scope across the HTTP boundary (#234)."""

from __future__ import annotations

import aiosqlite
import pytest
from httpx import ASGITransport, AsyncClient

from maistro.runs.wiring import wire_execution_spine
from maistro.tasks import queue as queue_module
from maistro.tasks.http_contract import (
    WORKSPACE_ID_HEADER,
    WORKSPACE_SCOPE_SIGNATURE_HEADER,
    sign_workspace_scope,
)
from maistro.tasks.queue import configure_task_queue
from maistro_server.main import app

TASK_WORKSPACE = "/tmp/maistro-workspace/test"  # nosec B108 -- API contract fixture
SCOPE_KEY = "test-only-workspace-scope-key"


@pytest.fixture
async def durable_spine(tmp_path, monkeypatch):
    """Wire /tasks to the SQLite canonical stores used by durable deployments."""
    previous = queue_module._queue
    queue_module._queue = None
    monkeypatch.setenv("WORKSPACE_SCOPE_KEY", SCOPE_KEY)
    conn = await aiosqlite.connect(tmp_path / "spine.db")
    (
        scope_store,
        run_store,
        admitter,
        _templates,
        _schedules,
        _continuations,
    ) = await wire_execution_spine(conn, workspace_id="default")
    configure_task_queue(admitter=admitter)
    try:
        yield scope_store, run_store
    finally:
        queue_module._queue = previous
        await conn.close()


@pytest.fixture
async def client():
    """Exercise the real ASGI route on the same loop as the durable SQLite spine."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client


def _scope_headers(workspace_id: str) -> dict[str, str]:
    return {
        WORKSPACE_ID_HEADER: workspace_id,
        WORKSPACE_SCOPE_SIGNATURE_HEADER: sign_workspace_scope(workspace_id, SCOPE_KEY),
    }


async def test_named_workspace_run_resolves_under_that_workspaces_root_project(
    durable_spine, client: AsyncClient
) -> None:
    scope_store, run_store = durable_spine

    response = await client.post(
        "/tasks",
        headers=_scope_headers("workspace-a"),
        json={"description": "ship it", "workspace": TASK_WORKSPACE},
    )

    assert response.status_code == 202
    run = await run_store.get_run(response.json()["run_id"])
    root = await scope_store.root_for_workspace("workspace-a")
    assert run is not None
    assert run.workspace_id == "workspace-a"
    assert run.project_id == root.project_id


async def test_two_workspace_headers_produce_runs_in_distinct_projects(
    durable_spine, client: AsyncClient
) -> None:
    scope_store, run_store = durable_spine

    first = await client.post(
        "/tasks",
        headers=_scope_headers("workspace-a"),
        json={"description": "first", "workspace": TASK_WORKSPACE},
    )
    second = await client.post(
        "/tasks",
        headers=_scope_headers("workspace-b"),
        json={"description": "second", "workspace": TASK_WORKSPACE},
    )

    assert first.status_code == 202
    assert second.status_code == 202
    first_run = await run_store.get_run(first.json()["run_id"])
    second_run = await run_store.get_run(second.json()["run_id"])
    first_root = await scope_store.root_for_workspace("workspace-a")
    second_root = await scope_store.root_for_workspace("workspace-b")
    assert first_run is not None
    assert second_run is not None
    assert first_run.project_id == first_root.project_id
    assert second_run.project_id == second_root.project_id
    assert first_run.project_id != second_run.project_id


async def test_authenticated_client_cannot_assert_workspace_without_hive_proof(
    durable_spine, client: AsyncClient
) -> None:
    del durable_spine

    response = await client.post(
        "/tasks",
        headers={WORKSPACE_ID_HEADER: "workspace-a"},
        json={"description": "must not admit", "workspace": TASK_WORKSPACE},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Workspace scope assertion is not authorized"
    assert queue_module._queue is not None
    items, _ = queue_module._queue.list_tasks(limit=10)
    assert items == []


async def test_workspace_signature_is_bound_to_the_named_workspace(
    durable_spine, client: AsyncClient
) -> None:
    del durable_spine

    response = await client.post(
        "/tasks",
        headers={
            WORKSPACE_ID_HEADER: "workspace-b",
            WORKSPACE_SCOPE_SIGNATURE_HEADER: sign_workspace_scope("workspace-a", SCOPE_KEY),
        },
        json={"description": "must not admit", "workspace": TASK_WORKSPACE},
    )

    assert response.status_code == 403
    assert queue_module._queue is not None
    items, _ = queue_module._queue.list_tasks(limit=10)
    assert items == []


async def test_unscoped_submission_keeps_configured_default_workspace(
    durable_spine, client: AsyncClient
) -> None:
    scope_store, run_store = durable_spine

    response = await client.post(
        "/tasks",
        json={"description": "default", "workspace": TASK_WORKSPACE},
    )

    assert response.status_code == 202
    run = await run_store.get_run(response.json()["run_id"])
    root = await scope_store.root_for_workspace("default")
    assert run is not None
    assert run.workspace_id == "default"
    assert run.project_id == root.project_id


async def test_blank_workspace_header_is_rejected_before_admission(
    durable_spine, client: AsyncClient
) -> None:
    del durable_spine

    response = await client.post(
        "/tasks",
        headers={WORKSPACE_ID_HEADER: " "},
        json={"description": "ship it", "workspace": TASK_WORKSPACE},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Workspace id must be a non-empty string"
