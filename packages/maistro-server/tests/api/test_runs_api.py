"""The run_id POST /tasks returns actually resolves (#41 review).

Advertising an identity with nothing behind it is worse than not advertising
one, because a client can build on it. These check that it resolves, that it
resolves only for its owner, and that the endpoint is honest about the part
that is not built yet.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from maistro.observability.metrics import active_tasks
from maistro.runs.model import RunStatus
from maistro.runs.sources import ADMISSION_SOURCE
from maistro.runs.store_boundary import RunStoreBoundary
from maistro.runs.wiring import wire_execution_spine
from maistro.tasks import queue as queue_module
from maistro.tasks.admission import TASK_ID_KEY, TASK_QUEUE_SOURCE
from maistro.tasks.models import TaskCreate, TaskResult, TaskStatus
from maistro.tasks.queue import configure_task_queue
from maistro.workspaces import InMemoryWorkspaceStore
from maistro_server.api import runs as runs_api
from maistro_server.main import app

WORKSPACE = "/tmp/maistro-workspace/test"  # nosec B108 — API contract, gated by the route


def _gauge_total(gauge: Any) -> float:
    return sum(float(sample["value"]) for sample in gauge.collect())


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
    # "dev" is the Workspace owner at creation; membership grants it VIEW.
    # The id is pinned to the spine's configured Workspace, or the Run's
    # scope and the membership would name different Workspaces.
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
        "/tasks", json={"description": "Add a hello endpoint", "workspace": WORKSPACE}
    )
    assert response.status_code == 202
    return response.json()


async def test_the_returned_run_id_resolves(wired, client: TestClient) -> None:
    created = _submit(client)

    fetched = client.get(f"/runs/{created['run_id']}")

    assert fetched.status_code == 200
    body = fetched.json()
    assert body["run_id"] == created["run_id"]
    assert body["status"] == "queued"
    assert body["workspace_id"] == "test-workspace"


async def test_the_run_carries_its_correlation_back(wired, client: TestClient) -> None:
    created = _submit(client)

    body = client.get(f"/runs/{created['run_id']}").json()

    assert body["provenance"]["task_id"] == created["task_id"]
    assert body["provenance"]["admission_source"] == "task_queue"


async def test_an_unknown_run_is_404(wired, client: TestClient) -> None:
    assert client.get("/runs/no-such-run").status_code == 404
    assert client.post("/runs/no-such-run/cancel").status_code == 404


async def test_run_cancel_uses_the_canonical_lifecycle(wired, client: TestClient) -> None:
    baseline = _gauge_total(active_tasks)
    created = _submit(client)
    queue = queue_module.get_task_queue()
    receipt = queue.get(created["task_id"])
    assert receipt is not None and receipt.status is TaskStatus.QUEUED
    assert _gauge_total(active_tasks) == pytest.approx(baseline + 1)

    response = client.post(f"/runs/{created['run_id']}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    persisted = await wired.get_run(created["run_id"])
    assert persisted is not None
    assert persisted.status.value == "cancelled"
    receipt = queue.get(created["task_id"])
    assert receipt is not None
    assert receipt.status is TaskStatus.CANCELLED
    assert receipt.completed_at == persisted.finished_at
    assert receipt.started_at is None
    assert receipt.result is not None and receipt.result.error == persisted.error
    assert _gauge_total(active_tasks) == pytest.approx(baseline)

    # Repeated canonical cancellation must not decrement the active gauge twice.
    repeated = client.post(f"/runs/{created['run_id']}/cancel")
    assert repeated.status_code == 200
    assert repeated.json()["finished_at"] == response.json()["finished_at"]
    assert receipt.completed_at == persisted.finished_at
    assert _gauge_total(active_tasks) == pytest.approx(baseline)


@pytest.mark.parametrize(
    "provenance",
    [
        {ADMISSION_SOURCE: "another-source", TASK_ID_KEY: "unrelated"},
        {ADMISSION_SOURCE: TASK_QUEUE_SOURCE},
        {ADMISSION_SOURCE: TASK_QUEUE_SOURCE, TASK_ID_KEY: ""},
        {ADMISSION_SOURCE: TASK_QUEUE_SOURCE, TASK_ID_KEY: 7},
    ],
    ids=["non-task-run", "missing-task-id", "empty-task-id", "non-string-task-id"],
)
async def test_cancel_without_a_task_correlation_keeps_local_receipts_unchanged(
    wired, client: TestClient, provenance: dict[str, Any]
) -> None:
    admitted = _submit(client)
    owner_run = await wired.get_run(admitted["run_id"])
    if provenance[ADMISSION_SOURCE] != TASK_QUEUE_SOURCE:
        # A coincident task_id alone must not make a non-task Run its owner.
        provenance = {**provenance, TASK_ID_KEY: admitted["task_id"]}
    run = await wired.create_run(
        owner_run.graph.materialize(), actor_principal_id="dev", provenance=provenance
    )
    queue = queue_module.get_task_queue()
    before = queue.get(admitted["task_id"]).model_dump()
    gauge = _gauge_total(active_tasks)

    response = client.post(f"/runs/{run.run_id}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert (await wired.get_run(run.run_id)).status is RunStatus.CANCELLED
    assert queue.get(admitted["task_id"]).model_dump() == before
    assert _gauge_total(active_tasks) == gauge


async def test_cancel_can_reach_canonical_run_when_this_replica_has_no_receipt(
    wired, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The local projection does not provide shared receipt visibility (#1690).

    Two queues share one in-memory Run store here. This is a boundary test,
    not a production two-process PostgreSQL/failover proof for #91/#849.
    """
    created = _submit(client)
    accepting_queue = queue_module.get_task_queue()
    other_queue = queue_module.TaskQueue()
    monkeypatch.setattr(queue_module, "_queue", other_queue)

    response = client.post(f"/runs/{created['run_id']}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert (await wired.get_run(created["run_id"])).status is RunStatus.CANCELLED
    assert other_queue.get(created["task_id"]) is None
    assert accepting_queue.get(created["task_id"]).status is TaskStatus.QUEUED


async def test_cancel_rejects_a_same_source_correlation_to_another_runs_receipt(
    wired, client: TestClient
) -> None:
    """Inconsistent stored provenance must not cross the canonical identity boundary.

    This sets up the inconsistency through the store; it does not claim an
    external caller can currently mint that provenance through an API.
    """
    queue = queue_module.get_task_queue()
    other_task = await queue.submit(
        TaskCreate(description="Bob's work", workspace=WORKSPACE), user_id="bob"
    )
    other_run = await wired.get_run(other_task.run_id)
    run = await wired.create_run(
        other_run.graph.materialize(),
        actor_principal_id="dev",
        provenance={ADMISSION_SOURCE: TASK_QUEUE_SOURCE, TASK_ID_KEY: other_task.task_id},
    )
    receipt_before = other_task.model_dump()
    run_before = other_run.model_dump()
    gauge = _gauge_total(active_tasks)

    response = client.post(f"/runs/{run.run_id}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert (await wired.get_run(run.run_id)).status is RunStatus.CANCELLED
    assert (await wired.get_run(other_task.run_id)).model_dump() == run_before
    assert queue.get(other_task.task_id).model_dump() == receipt_before
    assert _gauge_total(active_tasks) == gauge


async def test_cancel_clears_a_stale_receipt_result_when_canonical_outcome_is_empty(
    wired, client: TestClient
) -> None:
    created = _submit(client)
    queue = queue_module.get_task_queue()
    queue.set_result(created["task_id"], TaskResult(files_changed=["stale.py"]))
    run = await wired.transition_run(created["run_id"], RunStatus.CANCELLED)
    assert run.result is None and run.error is None

    response = client.post(f"/runs/{run.run_id}/cancel")

    assert response.status_code == 200
    receipt = queue.get(created["task_id"])
    assert receipt.status is TaskStatus.CANCELLED
    assert receipt.result is None
    assert client.get(f"/tasks/{created['task_id']}").json()["result"] is None


async def test_cancel_preserves_a_completed_canonical_winner(wired, client: TestClient) -> None:
    """The cancellation service can return completion; project that winner."""
    from maistro.agents.types import CodeOutput, ConductorOutput
    from maistro.tasks.execution import TaskAttemptExecutor
    from maistro.tasks.models import TaskCreate

    baseline = _gauge_total(active_tasks)
    created = _submit(client)

    async def execute(_request: TaskCreate) -> ConductorOutput:
        return ConductorOutput(
            success=True,
            final_answer="done",
            code=CodeOutput(description="generated", files_changed=["hello.py"]),
        )

    await TaskAttemptExecutor(wired).execute(
        created["run_id"],
        TaskCreate(description="Add a hello endpoint", workspace=WORKSPACE),
        execute,
    )
    run = await wired.get_run(created["run_id"])
    assert run is not None and run.status is RunStatus.COMPLETED

    response = client.post(f"/runs/{created['run_id']}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    receipt = queue_module.get_task_queue().get(created["task_id"])
    assert receipt.status is TaskStatus.COMPLETED
    assert receipt.started_at == run.started_at
    assert receipt.completed_at == run.finished_at
    assert receipt.result.files_changed == ["hello.py"]
    assert _gauge_total(active_tasks) == pytest.approx(baseline)


async def test_node_runs_are_empty_until_the_task_executes(wired, client: TestClient) -> None:
    """Empty because nothing has run yet, not because nothing ever will."""
    created = _submit(client)

    response = client.get(f"/runs/{created['run_id']}/node-runs")

    assert response.status_code == 200
    assert response.json() == []


async def test_an_executed_task_shows_its_real_node_run(wired, client: TestClient) -> None:
    """The endpoint #130 added now has something behind it (#143).

    Execution is driven here rather than by the server's own runner: the
    fixture wires the spine without starting a worker pool, and the point being
    checked is that the route reads back what the Attempt seam wrote.
    """
    from maistro.agents.types import CodeOutput, ConductorOutput
    from maistro.tasks.execution import TaskAttemptExecutor
    from maistro.tasks.models import TaskCreate

    created = _submit(client)

    async def _executor(_request: TaskCreate) -> ConductorOutput:
        return ConductorOutput(
            success=True,
            final_answer="done",
            code=CodeOutput(description="generated", files_changed=["hello.py"]),
        )

    await TaskAttemptExecutor(wired).execute(
        created["run_id"],
        TaskCreate(description="Add a hello endpoint", workspace=WORKSPACE),
        _executor,
    )

    body = client.get(f"/runs/{created['run_id']}/node-runs").json()
    assert len(body) == 1
    run = await wired.get_run(created["run_id"])
    assert run is not None
    assert body[0]["node_id"] == run.graph.materialize().nodes[0].node_id
    assert body[0]["status"] == "completed"
    assert body[0]["finished_at"] is not None
    (attempt,) = body[0]["attempts"]
    assert attempt["executor_id"] == "task_runner"
    assert attempt["status"] == "completed"
    assert attempt["agent"] is None


async def test_a_failed_task_attempt_is_visible_without_its_error_text(
    wired, client: TestClient
) -> None:
    from maistro.agents.types import ConductorOutput
    from maistro.tasks.execution import TaskAttemptExecutor
    from maistro.tasks.models import TaskCreate

    created = _submit(client)

    async def _executor(_request: TaskCreate) -> ConductorOutput:
        raise RuntimeError("token=sk-do-not-leak")

    with pytest.raises(RuntimeError):
        await TaskAttemptExecutor(wired).execute(
            created["run_id"],
            TaskCreate(description="Add a hello endpoint", workspace=WORKSPACE),
            _executor,
        )

    response = client.get(f"/runs/{created['run_id']}/node-runs")
    (attempt,) = response.json()[0]["attempts"]
    assert attempt["status"] == "failed"
    assert attempt["executor_id"] == "task_runner"
    assert "error" not in attempt
    assert "result" not in attempt
    assert "sk-do-not-leak" not in response.text


async def test_only_a_chat_attempt_names_an_agent(wired, client: TestClient) -> None:
    """A graph node's output is its Attempt result, and may hold an "agent" key of
    its own; that is not the agent the node was dispatched to (ADR-082526-7f02)."""
    from maistro.runs.model import AttemptStatus

    run_id = _submit(client)["run_id"]
    run = await wired.get_run(run_id)
    assert run is not None
    node_run = await wired.create_node_run(run_id, node_id=run.graph.materialize().nodes[0].node_id)
    attempt = await wired.create_attempt(node_run.node_run_id, executor_id="transform")
    await wired.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
    await wired.transition_attempt(
        attempt.attempt_id, AttemptStatus.COMPLETED, result={"agent": "not-a-dispatch"}
    )

    body = client.get(f"/runs/{run_id}/node-runs").json()

    assert body[0]["attempts"][0]["agent"] is None


async def test_node_runs_for_an_unknown_run_are_404(wired, client: TestClient) -> None:
    assert client.get("/runs/no-such-run/node-runs").status_code == 404


async def test_a_member_reads_a_run_they_did_not_initiate(wired, client: TestClient) -> None:
    """Owner decision 2026-09-23 (#1152): visibility is Workspace membership.

    The initiating principal is provenance, not a gate, so the Workspace
    member reads another principal's Run; a missing id stays a 404 that is
    word-for-word the refusal any outsider gets.
    """
    from maistro.graph.definitions import Graph, Node

    graph = Graph(
        workspace_id="test-workspace",
        project_id=(await wired.get_run(_submit(client)["run_id"])).project_id,
        name="someone else's",
        nodes=[Node(node_type="transform.format_markdown", name="n")],
    )
    other = await wired.create_run(graph, actor_principal_id="somebody-else")

    # "dev" is the Workspace owner: membership, not initiator identity, reads.
    assert client.get(f"/runs/{other.run_id}").status_code == 200
    assert client.get(f"/runs/{other.run_id}/node-runs").status_code == 200
    assert client.post(f"/runs/{other.run_id}/cancel").status_code == 200

    # A missing id and a refused id are the same answer, so the route leaks
    # nothing about existence.
    missing = client.get("/runs/no-such-run")
    assert missing.status_code == 404
    assert "Run not found" in missing.json()["error"]["message"]
    assert (await wired.get_run(other.run_id)).status is RunStatus.CANCELLED


def test_the_endpoint_says_so_when_no_store_is_configured(client: TestClient) -> None:
    previous = runs_api._run_store
    runs_api.configure_run_store(None)
    try:
        assert client.get("/runs/anything").status_code == 503
        assert client.post("/runs/anything/cancel").status_code == 503
    finally:
        runs_api.configure_run_store(previous)


def test_the_endpoint_says_so_when_no_boundary_is_configured(wired, client: TestClient) -> None:
    """The boundary half of the same fail-loud rule (#1152), with the store
    itself still configured: reads and cancellation must refuse loudly
    instead of serving authorization-skipped traffic."""
    previous = runs_api._run_boundary
    runs_api.configure_run_boundary(None)
    try:
        refused = client.get("/runs/anything")
        assert refused.status_code == 503
        assert "No Run authorization boundary is configured" in refused.json()["error"]["message"]
        assert client.post("/runs/anything/cancel").status_code == 503
        assert client.get("/runs/anything/node-runs").status_code == 503
    finally:
        runs_api.configure_run_boundary(previous)
