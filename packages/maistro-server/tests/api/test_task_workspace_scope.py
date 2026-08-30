"""POST /tasks honors explicit Workspace scope across the HTTP boundary (#234)."""

from __future__ import annotations

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from maistro.runs.wiring import wire_execution_spine
from maistro.tasks import queue as queue_module
from maistro.tasks.http_contract import WORKSPACE_ID_HEADER
from maistro.tasks.queue import configure_task_queue
from maistro_server.main import app

TASK_WORKSPACE = "/tmp/maistro-workspace/test"  # nosec B108 -- API contract fixture


@pytest.fixture
async def durable_spine(tmp_path):
    """Wire /tasks to the SQLite canonical stores used by durable deployments."""
    previous = queue_module._queue
    queue_module._queue = None
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
def client() -> TestClient:
    return TestClient(app)


async def test_named_workspace_run_resolves_under_that_workspaces_root_project(
    durable_spine, client: TestClient
) -> None:
    scope_store, run_store = durable_spine

    response = client.post(
        "/tasks",
        headers={WORKSPACE_ID_HEADER: "workspace-a"},
        json={"description": "ship it", "workspace": TASK_WORKSPACE},
    )

    assert response.status_code == 202
    run = await run_store.get_run(response.json()["run_id"])
    root = await scope_store.root_for_workspace("workspace-a")
    assert run is not None
    assert run.workspace_id == "workspace-a"
    assert run.project_id == root.project_id


async def test_two_workspace_headers_produce_runs_in_distinct_projects(
    durable_spine, client: TestClient
) -> None:
    scope_store, run_store = durable_spine

    first = client.post(
        "/tasks",
        headers={WORKSPACE_ID_HEADER: "workspace-a"},
        json={"description": "first", "workspace": TASK_WORKSPACE},
    )
    second = client.post(
        "/tasks",
        headers={WORKSPACE_ID_HEADER: "workspace-b"},
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


def test_blank_workspace_header_is_rejected_before_admission(
    durable_spine, client: TestClient
) -> None:
    response = client.post(
        "/tasks",
        headers={WORKSPACE_ID_HEADER: " "},
        json={"description": "ship it", "workspace": TASK_WORKSPACE},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Workspace id must be a non-empty string"
