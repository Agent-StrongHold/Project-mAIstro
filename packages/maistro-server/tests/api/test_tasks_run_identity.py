"""POST /tasks returns a run_id that resolves in the Run store (#41).

The unit tests prove the seam works when something wires it. This proves the
wiring actually reaches the HTTP boundary — the gap where a canonical-identity
claim most easily becomes true in the library and false in the product.

The parity assertions matter as much as the new ones: admitting a Run must not
have changed what /tasks already did.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maistro.runs.concurrency import RunConcurrencyLimits
from maistro.runs.model import RunStatus
from maistro.runs.wiring import wire_execution_spine
from maistro.tasks import queue as queue_module
from maistro.tasks.idempotency import (
    TASK_SUBMIT_ACTION,
    InMemoryTaskIdempotencyStore,
    admission_scope_key,
)
from maistro.tasks.queue import configure_task_queue
from maistro_server.api.tasks import router as tasks_router
from maistro_server.main import app

WORKSPACE = "/tmp/maistro-workspace/test"  # nosec B108 — API contract, gated by the route


@pytest.fixture
async def wired():
    """Install a queue on a real Run spine, as the app's lifespan does."""
    previous = queue_module._queue
    queue_module._queue = None
    (
        _scope_store,
        run_store,
        admitter,
        _templates,
        _schedules,
        _continuations,
    ) = await wire_execution_spine(None, workspace_id="test-workspace")
    configure_task_queue(admitter=admitter)
    try:
        yield run_store
    finally:
        queue_module._queue = previous


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
async def wired_bounded():
    """A queue on a real Run spine whose configured ceiling is one active
    root Run for this principal, with the in-memory claim tier wired.

    ``concurrency_limits`` is the wiring's operator-facing path — the same
    object ``RunConcurrencyLimits.configured()`` builds from settings — so
    the ceiling that refuses here is the real store's, tightened for the
    test, not a stub standing in for one.
    """
    previous = queue_module._queue
    queue_module._queue = None
    (
        _scope_store,
        run_store,
        admitter,
        _templates,
        _schedules,
        _continuations,
    ) = await wire_execution_spine(
        None,
        workspace_id="test-workspace",
        concurrency_limits=RunConcurrencyLimits(per_principal=1, per_workspace=4),
    )
    idempotency = InMemoryTaskIdempotencyStore()
    queue = configure_task_queue(admitter=admitter, idempotency_store=idempotency)
    bounded_app = FastAPI()
    bounded_app.include_router(tasks_router)
    try:
        yield queue, run_store, idempotency, bounded_app
    finally:
        queue_module._queue = previous


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


async def test_task_submission_at_capacity_returns_429_without_retained_claim(
    wired_bounded,
) -> None:
    """A new submission the canonical ceiling refuses is backpressure, not success.

    The saturation is real: the first task is admitted by the wired spine and
    still holds its slot, so the refusal comes out of the same
    ``RunStore.create_run`` ceiling every transport shares — nothing on the
    route is stubbed to raise. That refusal must answer 429 with
    ``Retry-After`` (the chat turn convention), mint neither a receipt nor a
    Run nor a dispatch, release its temporary claim, and admit cleanly once a
    terminal release frees the slot.
    """
    queue, run_store, idempotency, bounded_app = wired_bounded
    bounded_client = TestClient(bounded_app)
    body = {"description": "Add a hello endpoint", "workspace": WORKSPACE}

    admitted = bounded_client.post("/tasks", json=body, headers={"Idempotency-Key": "k-admitted"})
    assert admitted.status_code == 202

    refused = bounded_client.post(
        "/tasks",
        json={"description": "More work while full", "workspace": WORKSPACE},
        headers={"Idempotency-Key": "k-refused"},
    )

    assert refused.status_code == 429
    assert int(refused.headers["Retry-After"]) > 0
    # Refused, not admitted: no success Location and no receipt shape on the
    # body — the caller is sent away to retry, never handed a task.
    assert "Location" not in refused.headers
    assert "task_id" not in refused.json()
    assert "run_id" not in refused.json()
    # Nothing was queued or dispatched behind the refusal: the queue holds
    # only the first task's receipt, and the store holds only its Run.
    receipts, _cursor = queue.list_tasks(user_id="dev")
    assert [task.task_id for task in receipts] == [admitted.json()["task_id"]]
    queued = await run_store.list_by_status(RunStatus.QUEUED)
    assert [run.run_id for run in queued] == [admitted.json()["run_id"]]
    # The temporary claim went back: the claim tier holds no row under the
    # refused key, so the caller's retry is a fresh admission, not a wait on
    # a twin that never existed.
    refused_scope = admission_scope_key(
        principal="dev",
        workspace_id="test-workspace",
        action=TASK_SUBMIT_ACTION,
        key="k-refused",
    )
    assert await idempotency.get(refused_scope) is None

    # A replay of the already-admitted key still answers with its original
    # receipt while the store is saturated — reconciliation reads the claim,
    # so backpressure never strands it — without admitting anything again.
    replay = bounded_client.post("/tasks", json=body, headers={"Idempotency-Key": "k-admitted"})
    assert replay.status_code == 202
    assert replay.json()["task_id"] == admitted.json()["task_id"]
    assert replay.json()["run_id"] == admitted.json()["run_id"]
    assert len(await run_store.list_by_status(RunStatus.QUEUED)) == 1

    # The admitted root terminalizes through the canonical cancel path and
    # releases its slot; the previously refused task is then accepted as a
    # new admission with a Run of its own.
    cancelled = bounded_client.delete(f"/tasks/{admitted.json()['task_id']}")
    assert cancelled.status_code == 200
    retried = bounded_client.post(
        "/tasks",
        json={"description": "More work while full", "workspace": WORKSPACE},
        headers={"Idempotency-Key": "k-refused"},
    )
    assert retried.status_code == 202
    assert retried.json()["task_id"] != admitted.json()["task_id"]
    assert await run_store.get_run(retried.json()["run_id"]) is not None
