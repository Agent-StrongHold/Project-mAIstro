"""Inbound A2A admission is a durable canonical effect claim (#1194)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from maistro.runs import RunStatus
from maistro.runs.wiring import wire_execution_spine
from maistro_server.api import a2a
from maistro_server.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


async def test_replayed_a2a_create_returns_one_canonical_run(client: TestClient) -> None:
    (
        scope_store,
        run_store,
        _admitter,
        _templates,
        _schedules,
        _continuations,
    ) = await wire_execution_spine(None, workspace_id="a2a-workspace")
    a2a.configure_a2a_admission(
        run_store,
        scope_store,
        workspace_id="a2a-workspace",
    )
    try:
        payload = {
            "agent_id": "researcher",
            "messages": [{"role": "user", "content": "research X"}],
            "idempotency_key": "agent.delegate_remote:a2a-effect",
        }
        first = client.post("/a2a/tasks/create", json=payload)
        second = client.post("/a2a/tasks/create", json=payload)

        assert first.status_code == second.status_code == 202
        assert first.json() == second.json()
        assert len(await run_store.list_by_status(RunStatus.CREATED)) == 1

        # The reconciliation half of transport idempotency: a worker that lost
        # its lease after an ambiguous POST polls the key and gets the original
        # receipt back, never a second admission.
        receipt = client.get(f"/a2a/tasks/by-idempotency-key/{payload['idempotency_key']}")
        assert receipt.status_code == 200
        assert receipt.json()["task_id"] == first.json()["task_id"]

        unknown = client.get("/a2a/tasks/by-idempotency-key/never-claimed")
        assert unknown.status_code == 404
    finally:
        a2a.configure_a2a_admission(None, None)


def test_unconfigured_admission_is_a_503_never_a_false_admission(client: TestClient) -> None:
    """Without wired canonical stores the endpoint refuses, it does not guess."""
    a2a.configure_a2a_admission(None, None)
    try:
        refused = client.post(
            "/a2a/tasks/create",
            json={
                "agent_id": "researcher",
                "messages": [{"role": "user", "content": "research X"}],
                "idempotency_key": "agent.delegate_remote:unconfigured",
            },
        )
        assert refused.status_code == 503

        receipt = client.get("/a2a/tasks/by-idempotency-key/agent.delegate_remote:unconfigured")
        assert receipt.status_code == 503
    finally:
        a2a.configure_a2a_admission(None, None)
