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


async def test_a_delegation_context_is_filed_as_evidence_on_the_admitted_run(
    client: TestClient,
) -> None:
    """Issue #959: the sender's canonical caller/scope/Goal/Run binding rides
    the delegation envelope and lands on the admitted Run's provenance, so the
    remote execution is traceable from the delegating Goal/Run evidence."""
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
            "idempotency_key": "agent.delegate_remote:context-effect",
            "delegation_context": {
                "caller_principal_id": "actor-9",
                "delegating_agent": "planner",
                "workspace_id": "delegating-workspace",
                "project_id": "delegating-project",
                "run_id": "delegating-run",
                "node_run_id": "delegating-node-run",
                "goal_id": "goal-1",
                "goal_revision": 2,
                "subgoal_of": "goal-0",
                "delegated_scopes": ["web.read"],
                "delegation_key": "agent.delegate_remote:context-effect",
            },
        }
        response = client.post("/a2a/tasks/create", json=payload)
        assert response.status_code == 202

        claim = await run_store.find_run_by_effect(payload["idempotency_key"])
        assert claim is not None
        filed = claim.provenance["a2a_delegation_context"]
        assert filed["caller_principal_id"] == "actor-9"
        assert filed["workspace_id"] == "delegating-workspace"
        assert filed["goal_id"] == "goal-1"
        assert filed["goal_revision"] == 2
        assert filed["subgoal_of"] == "goal-0"
        # Evidence of the delegating scope, not authorization: the admitted
        # Run still belongs to THIS service's configured Workspace.
        assert claim.workspace_id == "a2a-workspace"

        malformed = client.post(
            "/a2a/tasks/create",
            json={
                **payload,
                "idempotency_key": "agent.delegate_remote:bad",
                "delegation_context": {"caller_principal_id": ""},
            },
        )
        assert malformed.status_code == 422, (
            "an unparseable binding is a protocol violation, not admissible evidence"
        )
    finally:
        a2a.configure_a2a_admission(None, None)
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
