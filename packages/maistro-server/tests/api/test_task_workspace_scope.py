"""POST /tasks honors explicit Workspace scope across the HTTP boundary (#234)."""

from __future__ import annotations

import aiosqlite
import pytest
from httpx import ASGITransport, AsyncClient

from maistro.runs.wiring import wire_execution_spine
from maistro.tasks import queue as queue_module
from maistro.tasks.http_contract import (
    DELEGATION_HEADER,
    WORKSPACE_ID_HEADER,
    WORKSPACE_SCOPE_SIGNATURE_HEADER,
    sign_delegation_context,
    sign_workspace_scope,
)
from maistro.tasks.queue import configure_task_queue
from maistro_server.api.runs import configure_run_store
from maistro_server.main import app

TASK_WORKSPACE = "/tmp/maistro-workspace/test"  # nosec B108 -- API contract fixture
SCOPE_KEY = "test-only-workspace-scope-key"
DELEGATION_KEY = "test-only-task-delegation-key"


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
    configure_run_store(run_store)
    try:
        yield scope_store, run_store
    finally:
        configure_run_store(None)
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


def _delegation_headers(user_id: str) -> dict[str, str]:
    return {
        "Authorization": "Bearer service-secret",
        DELEGATION_HEADER: sign_delegation_context(
            service_principal="conductor",
            originating_principal=user_id,
            key=DELEGATION_KEY,
        ),
    }


async def test_delegated_users_keep_distinct_task_and_run_ownership(
    durable_spine, client: AsyncClient, monkeypatch
) -> None:
    """The shared service credential cannot collapse Alice and Bob."""
    _scope_store, run_store = durable_spine
    monkeypatch.setenv("API_KEYS", '["conductor:service-secret"]')
    monkeypatch.setenv("TASK_DELEGATION_KEY", DELEGATION_KEY)

    alice = await client.post(
        "/tasks",
        headers=_delegation_headers("alice"),
        json={
            "description": "Alice task",
            "workspace": TASK_WORKSPACE,
            "user_id": "mallory",
        },
    )
    bob = await client.post(
        "/tasks",
        headers=_delegation_headers("bob"),
        json={"description": "Bob task", "workspace": TASK_WORKSPACE},
    )

    assert alice.status_code == 202
    assert bob.status_code == 202
    alice_body = alice.json()
    bob_body = bob.json()
    assert alice_body["task"]["user_id"] == "alice"
    assert bob_body["task"]["user_id"] == "bob"
    assert alice_body["task"]["service_principal_id"] == "conductor"
    assert bob_body["task"]["service_principal_id"] == "conductor"

    alice_run = await run_store.get_run(alice_body["run_id"])
    bob_run = await run_store.get_run(bob_body["run_id"])
    assert alice_run is not None and bob_run is not None
    assert alice_run.actor_principal_id == "alice"
    assert bob_run.actor_principal_id == "bob"
    assert alice_run.provenance["service_principal_id"] == "conductor"
    assert bob_run.provenance["service_principal_id"] == "conductor"
    assert alice_run.provenance["delegation_id"] == alice_body["task"]["delegation_id"]
    assert bob_run.provenance["delegation_id"] == bob_body["task"]["delegation_id"]

    own = await client.get(f"/tasks/{alice_body['task_id']}", headers=_delegation_headers("alice"))
    cross = await client.get(f"/tasks/{alice_body['task_id']}", headers=_delegation_headers("bob"))
    assert own.status_code == 200
    assert cross.status_code == 404

    own_run = await client.get(
        f"/runs/{alice_body['run_id']}", headers=_delegation_headers("alice")
    )
    cross_run = await client.get(
        f"/runs/{alice_body['run_id']}", headers=_delegation_headers("bob")
    )
    assert own_run.status_code == 200
    assert own_run.json()["provenance"]["service_principal_id"] == "conductor"
    assert cross_run.status_code == 404
    cross_cancel = await client.delete(
        f"/tasks/{alice_body['task_id']}", headers=_delegation_headers("bob")
    )
    assert cross_cancel.status_code == 404


async def test_a_forged_originating_principal_is_rejected(
    durable_spine, client: AsyncClient, monkeypatch
) -> None:
    del durable_spine
    monkeypatch.setenv("API_KEYS", '["conductor:service-secret"]')
    monkeypatch.setenv("TASK_DELEGATION_KEY", DELEGATION_KEY)
    forged = sign_delegation_context(
        service_principal="other-service",
        originating_principal="alice",
        key=DELEGATION_KEY,
    )

    response = await client.post(
        "/tasks",
        headers={"Authorization": "Bearer service-secret", DELEGATION_HEADER: forged},
        json={"description": "must not admit", "workspace": TASK_WORKSPACE},
    )

    assert response.status_code == 403


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
    assert response.json()["error"]["message"] == "Workspace scope assertion is not authorized"
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
    assert response.json()["error"]["message"] == "Workspace id must be a non-empty string"
