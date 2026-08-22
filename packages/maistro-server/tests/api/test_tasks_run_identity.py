"""POST /tasks returns a run_id that resolves in the Run store (#41).

The unit tests prove the seam works when something wires it. This proves the
wiring actually reaches the HTTP boundary — the gap where a canonical-identity
claim most easily becomes true in the library and false in the product.

The parity assertions matter as much as the new ones: admitting a Run must not
have changed what /tasks already did.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from maistro.runs.wiring import wire_execution_spine
from maistro.tasks import queue as queue_module
from maistro.tasks.queue import configure_task_queue
from maistro_server.main import app

WORKSPACE = "/tmp/maistro-workspace/test"  # nosec B108 — API contract, gated by the route


@pytest.fixture
async def wired():
    """Install a queue on a real Run spine, as the app's lifespan does."""
    previous = queue_module._queue
    queue_module._queue = None
    spine = await wire_execution_spine(None, workspace_id="test-workspace")
    run_store, admitter = spine.run_store, spine.task_admitter
    configure_task_queue(admitter=admitter)
    try:
        yield run_store
    finally:
        queue_module._queue = previous


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


async def test_post_tasks_returns_a_resolvable_run_id(wired, client: TestClient) -> None:
    response = client.post(
        "/tasks", json={"description": "Add a hello endpoint", "workspace": WORKSPACE}
    )

    assert response.status_code == 202
    body = response.json()
    assert body["run_id"]
    assert body["task"]["run_id"] == body["run_id"]

    run = await wired.get_run(body["run_id"])
    assert run is not None
    assert run.workspace_id == "test-workspace"


async def test_the_run_points_back_at_the_task(wired, client: TestClient) -> None:
    response = client.post(
        "/tasks", json={"description": "Add a hello endpoint", "workspace": WORKSPACE}
    )
    body = response.json()

    run = await wired.get_run(body["run_id"])

    assert run is not None
    assert run.provenance["task_id"] == body["task_id"]
    assert run.provenance["admission_source"] == "task_queue"


async def test_the_run_is_one_executable_node(wired, client: TestClient) -> None:
    from maistro.graph.nodes import list_kinds

    response = client.post(
        "/tasks", json={"description": "Add a hello endpoint", "workspace": WORKSPACE}
    )
    run = await wired.get_run(response.json()["run_id"])

    assert run is not None
    graph = run.graph.materialize()
    assert len(graph.nodes) == 1
    assert graph.nodes[0].node_type in list_kinds()


async def test_get_tasks_still_answers_as_before(wired, client: TestClient) -> None:
    """Parity: admitting a Run changed nothing the endpoint already promised."""
    created = client.post(
        "/tasks", json={"description": "Add a hello endpoint", "workspace": WORKSPACE}
    ).json()

    fetched = client.get(f"/tasks/{created['task_id']}")

    assert fetched.status_code == 200
    body = fetched.json()
    assert body["task_id"] == created["task_id"]
    assert body["status"] == "queued"
    assert body["description"] == "Add a hello endpoint"


async def test_cancel_still_works_and_takes_the_run_with_it(wired, client: TestClient) -> None:
    created = client.post(
        "/tasks", json={"description": "Add a hello endpoint", "workspace": WORKSPACE}
    ).json()

    cancelled = client.delete(f"/tasks/{created['task_id']}")

    assert cancelled.status_code == 200
    assert cancelled.json()["cancelled"] is True
    run = await wired.get_run(created["run_id"])
    assert run is not None
    assert run.status.value == "cancelled"


def test_an_unwired_app_still_serves_tasks(client: TestClient) -> None:
    """No Run spine installed (no lifespan): /tasks answers, run_id is null."""
    previous = queue_module._queue
    queue_module._queue = None
    try:
        response = client.post(
            "/tasks", json={"description": "Add a hello endpoint", "workspace": WORKSPACE}
        )

        assert response.status_code == 202
        assert response.json()["run_id"] is None
    finally:
        queue_module._queue = previous
