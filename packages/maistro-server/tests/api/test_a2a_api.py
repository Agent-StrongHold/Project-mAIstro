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
    finally:
        a2a.configure_a2a_admission(None, None)
