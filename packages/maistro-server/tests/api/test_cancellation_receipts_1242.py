"""The cancellation routes must report requested vs confirmed separately (#1242).

Before the receipt contract, `POST /runs/{id}/cancel` returned a `RunSummary`
whose `status: cancelled` every caller read as "the provider stopped", and
`DELETE /tasks/{id}` returned `cancelled: true` with nothing beside it. Both
routes now carry the physical evidence in the same vocabulary the Conductor
route uses. These drive the real routes over the wired spine — no stubs — and
pin the fields that keep a logical fence from being read as a physical stop.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from maistro.runs import AttemptStatus
from maistro.runs.store_boundary import RunStoreBoundary
from maistro.runs.wiring import wire_execution_spine
from maistro.tasks import queue as queue_module
from maistro.tasks.models import TaskStatus
from maistro.tasks.queue import configure_task_queue
from maistro.workspaces import InMemoryWorkspaceStore
from maistro_server.api import runs as runs_api
from maistro_server.main import app

WORKSPACE = "/tmp/maistro-workspace/test"  # nosec B108 — API contract, gated by the route


@pytest.fixture
async def wired():
    previous = queue_module._queue
    queue_module._queue = None
    (
        scope_store,
        run_store,
        admitter,
        _templates,
        _schedules,
        _continuations,
    ) = await wire_execution_spine(None, workspace_id="test-workspace")
    workspaces = InMemoryWorkspaceStore(project_store=scope_store)
    await workspaces.create(
        creator_user_id="dev", name="test-workspace", workspace_id="test-workspace"
    )
    configure_task_queue(admitter=admitter)
    runs_api.configure_run_store(run_store)
    runs_api.configure_run_boundary(RunStoreBoundary(run_store, workspaces, scope_store))
    try:
        yield run_store
    finally:
        queue_module._queue = previous
        runs_api.configure_run_store(None)
        runs_api.configure_run_boundary(None)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _submit(client: TestClient) -> dict:
    response = client.post(
        "/tasks", json={"description": "cancel receipt me", "workspace": WORKSPACE}
    )
    assert response.status_code == 202
    return response.json()


async def test_the_run_cancel_route_carries_the_physical_evidence(
    wired, client: TestClient
) -> None:
    """A queued Run has no physical try: the fence plus a confirmed stop."""
    created = _submit(client)

    response = client.post(f"/runs/{created['run_id']}/cancel")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled"
    assert body["fenced"] is True
    assert body["stop_confirmed"] is True
    assert body["disposition"] == "stop_confirmed"
    assert body["cause"] == "requested"
    assert body["diagnosis"]
    assert body["attempts"] == []
    # The old compatibility fields are unchanged.
    assert body["run_id"] == created["run_id"]
    assert body["workspace_id"] == "test-workspace"


async def test_the_run_route_never_claims_a_stop_the_process_cannot_prove(
    wired, client: TestClient
) -> None:
    """An Attempt live under another worker's lease is `stop_pending`."""
    created = _submit(client)
    run_id = created["run_id"]
    run = await wired.get_run(run_id)
    assert run is not None
    node_id = run.graph.materialize().nodes[0].node_id
    node_run = await wired.create_node_run(run_id, node_id=node_id)
    attempt = await wired.create_attempt(
        node_run.node_run_id,
        runtime_id="remote-runtime",
        lease_holder="worker-b",
        lease_ttl=timedelta(minutes=5),
    )
    assert attempt.execution_lease is not None
    await wired.transition_attempt(
        attempt.attempt_id,
        AttemptStatus.RUNNING,
        fencing_token=attempt.execution_lease.fencing_token,
    )

    body = client.post(f"/runs/{run_id}/cancel").json()

    assert body["status"] == "cancelled"
    assert body["fenced"] is True
    assert body["stop_confirmed"] is False
    assert body["disposition"] == "stop_pending"
    [row] = body["attempts"]
    assert row["attempt_id"] == attempt.attempt_id
    assert row["status"] == "running"
    assert row["disposition"] == "stop_pending"
    assert row["owner"] == "worker-b"
    assert row["diagnosis"]


async def test_the_task_cancel_route_reports_the_same_vocabulary(wired, client: TestClient) -> None:
    """`cancelled` keeps its accept meaning; the physical fact rides beside it."""
    created = _submit(client)

    response = client.delete(f"/tasks/{created['task_id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["cancelled"] is True
    assert body["stop_confirmed"] is True
    assert body["disposition"] == "stop_confirmed"
    assert body["run_id"] == created["run_id"]
    assert body["diagnosis"]

    receipt = client.get(f"/tasks/{created['task_id']}").json()
    assert receipt["status"] == TaskStatus.CANCELLED.value


async def test_the_task_cancel_route_refusal_names_the_actual_winner(
    wired, client: TestClient
) -> None:
    """A second cancellation is the route's 400, with no stop claimed."""
    created = _submit(client)
    first = client.delete(f"/tasks/{created['task_id']}")
    assert first.status_code == 200

    second = client.delete(f"/tasks/{created['task_id']}")

    assert second.status_code == 400
