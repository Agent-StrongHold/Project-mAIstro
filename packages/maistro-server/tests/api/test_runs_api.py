"""The run_id POST /tasks returns actually resolves (#41 review).

Advertising an identity with nothing behind it is worse than not advertising
one, because a client can build on it. These check that it resolves, that it
resolves only for its owner, and that the endpoint is honest about the part
that is not built yet.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from maistro.runs.wiring import wire_execution_spine
from maistro.tasks import queue as queue_module
from maistro.tasks.queue import configure_task_queue
from maistro_server.api import runs as runs_api
from maistro_server.main import app

WORKSPACE = "/tmp/maistro-workspace/test"  # nosec B108 — API contract, gated by the route


@pytest.fixture
async def wired():
    previous = queue_module._queue
    queue_module._queue = None
    spine = await wire_execution_spine(None, workspace_id="test-workspace")
    run_store, admitter = spine.run_store, spine.task_admitter
    configure_task_queue(admitter=admitter)
    runs_api.configure_run_store(run_store)
    try:
        yield run_store
    finally:
        queue_module._queue = previous
        runs_api.configure_run_store(None)


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


async def test_a_queued_run_has_no_node_runs_yet(wired, client: TestClient) -> None:
    """Empty because nothing has executed it — this fixture wires the queue but
    no runner. Before #143 it was empty because execution went around the spine
    entirely; the test below is what tells those two apart."""
    created = _submit(client)

    response = client.get(f"/runs/{created['run_id']}/node-runs")

    assert response.status_code == 200
    assert response.json() == []


async def test_an_executed_run_reports_its_node_run(wired, client: TestClient) -> None:
    """The endpoint stops being correct-and-always-empty (#143)."""
    from maistro.agents.types import CodeOutput, ConductorOutput
    from maistro.tasks.queue import get_task_queue
    from maistro.tasks.runner import TaskRunner

    created = _submit(client)

    async def _executor(_request):
        return ConductorOutput(
            success=True,
            final_answer="done",
            code=CodeOutput(files_changed=["a.py"], description="done"),
        )

    runner = TaskRunner(get_task_queue(), executor=_executor, run_store=wired)
    await runner._execute_task(created["task_id"])

    response = client.get(f"/runs/{created['run_id']}/node-runs")

    assert response.status_code == 200
    assert len(response.json()) == 1


async def test_node_runs_for_an_unknown_run_are_404(wired, client: TestClient) -> None:
    assert client.get("/runs/no-such-run/node-runs").status_code == 404


async def test_another_principals_run_is_not_visible(wired, client: TestClient) -> None:
    """404 rather than 403 on a scope mismatch: a 403 confirms the run_id
    exists, which is what an enumeration attempt is asking."""
    from maistro.graph.definitions import Graph, Node

    graph = Graph(
        workspace_id="test-workspace",
        project_id=(await wired.get_run(_submit(client)["run_id"])).project_id,
        name="someone else's",
        nodes=[Node(node_type="transform.format_markdown", name="n")],
    )
    other = await wired.create_run(graph, actor_principal_id="somebody-else")

    assert client.get(f"/runs/{other.run_id}").status_code == 404


def test_the_endpoint_says_so_when_no_store_is_configured(client: TestClient) -> None:
    previous = runs_api._run_store
    runs_api.configure_run_store(None)
    try:
        assert client.get("/runs/anything").status_code == 503
    finally:
        runs_api.configure_run_store(previous)
