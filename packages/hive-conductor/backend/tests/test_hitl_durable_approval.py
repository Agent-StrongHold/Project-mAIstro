"""HITL answer settles DurableApproval before Graph resume (#55 / #1192)."""

from __future__ import annotations

import pytest
from services.workspace_authority import create_workspace

from maistro.capabilities.approval_store import (
    ApprovalStatus,
    DurableApproval,
    InMemoryApprovalStore,
    approval_request_digest,
)
from maistro.capabilities.slots.approval import ApprovalRequest
from maistro.graph.definitions import Graph, Node
from maistro.graph.durable_runs import InMemoryDurableRunStore
from maistro.graph.durable_runs.types import DurableRunRecord
from maistro.graph.execution_state import GraphExecutionState
from maistro.graph.nodes.base import PAUSE_AWAITING_HUMAN_APPROVAL
from maistro.runs.lifecycle import transition_node_run, transition_run
from maistro.runs.model import GraphSnapshot, NodeRun, Run, RunStatus
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID

_EFFECT_KEY = "write:hitl-55"
_DIGEST = approval_request_digest({"action": "restart_container", "params": {"name": "x"}})


@pytest.fixture(autouse=True)
def _bind_stores(monkeypatch: pytest.MonkeyPatch) -> InMemoryApprovalStore:
    from types import SimpleNamespace

    from services import dag_agents
    from services.engine import get_engine

    graph_store = InMemoryDurableRunStore()
    approvals = InMemoryApprovalStore()
    monkeypatch.setattr(dag_agents, "get_canonical_run_store", lambda: graph_store)

    engine = get_engine()
    effects = SimpleNamespace(approval_store=approvals)
    port = SimpleNamespace(container=SimpleNamespace(capability_effects=effects))
    monkeypatch.setattr(engine, "_agent_port", port)
    return approvals


def _paused_node_run(run_id: str, node_id: str, *, node_run_id: str) -> NodeRun:
    node_run = NodeRun(run_id=run_id, node_id=node_id, ordinal=1, node_run_id=node_run_id)
    node_run = transition_node_run(node_run, RunStatus.QUEUED)
    node_run = transition_node_run(node_run, RunStatus.RUNNING)
    return transition_node_run(node_run, RunStatus.PAUSED)


def _approval_paused_record(
    run_id: str,
    *,
    workspace_id: str,
    project_id: str,
    request_id: str,
    node_run_id: str = "nr-approval-1",
    binding_id: str = "binding-55",
) -> DurableRunRecord:
    graph = Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name="capability-approval",
        nodes=[Node(node_id="effect", node_type="infra.approval_gated_action")],
    )
    run = Run(
        run_id=run_id,
        workspace_id=workspace_id,
        project_id=project_id,
        graph=GraphSnapshot.from_graph(graph),
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    run = transition_run(run, RunStatus.QUEUED)
    run = transition_run(run, RunStatus.RUNNING)
    run = transition_run(run, RunStatus.PAUSED)
    state = GraphExecutionState(
        run_id=run_id,
        active_node_ids=("effect",),
        blackboard_snapshot={},
        metadata={
            "initial_inputs": {},
            "hitl_answers": {},
            "pauses": {
                "effect": {
                    "kind": "hitl",
                    "metadata": {
                        "paused_reason": PAUSE_AWAITING_HUMAN_APPROVAL,
                        "approval_request_id": request_id,
                        "effect_key": _EFFECT_KEY,
                        "request_digest": _DIGEST,
                        "binding_id": binding_id,
                        "action": "restart_container",
                    },
                }
            },
        },
    )
    return DurableRunRecord(
        run=run,
        graph_state=state,
        node_runs=(_paused_node_run(run_id, "effect", node_run_id=node_run_id),),
        version=1,
    )


async def _seed_approval_pause(
    graph_store: InMemoryDurableRunStore,
    approvals: InMemoryApprovalStore,
    *,
    run_id: str,
    request_id: str = "apr-55-1",
) -> tuple[str, str, str]:
    workspace = await create_workspace(
        creator_user_id="admin",
        name=f"Approval WS-{run_id}",
        persona_template_id="default",
        checklist=[],
        theme_id="default",
        voice_tone_override=None,
    )
    from services.workspace_authority import canonical_store_for_tests

    root = await canonical_store_for_tests().project_store.root_for_workspace(workspace.id)
    node_run_id = f"nr-{run_id}"
    record = _approval_paused_record(
        run_id,
        workspace_id=workspace.id,
        project_id=root.project_id,
        request_id=request_id,
        node_run_id=node_run_id,
    )
    await graph_store.create(record)
    await approvals.create(
        DurableApproval(
            request=ApprovalRequest(
                request_id=request_id,
                action="infra_action",
                params={"request": {"action": "restart_container", "params": {"name": "x"}}},
                tier="policy",
                requester="self_repair",
            ),
            workspace_id=workspace.id,
            project_id=root.project_id,
            run_id=run_id,
            node_run_id=node_run_id,
            attempt_id="attempt-1",
            binding_id="binding-55",
            effect_key=_EFFECT_KEY,
            request_digest=_DIGEST,
        )
    )
    return workspace.id, root.project_id, node_run_id


@pytest.fixture
def approval_client(admin_client, _bind_stores):
    from services.dag_agents import get_canonical_run_store

    return admin_client, get_canonical_run_store(), _bind_stores


async def test_approve_resolves_durable_approval_then_answers(approval_client) -> None:
    client, graph_store, approvals = approval_client
    await _seed_approval_pause(graph_store, approvals, run_id="hitl-apr-ok")

    response = client.post(
        "/v1/hitl/hitl-apr-ok/effect/answer",
        json={
            "approved": True,
            "expected_approval_request_id": "apr-55-1",
            "note": "ship it",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["run_status"] != RunStatus.PAUSED.value

    settled = await approvals.get("apr-55-1")
    assert settled is not None
    assert settled.status is ApprovalStatus.APPROVED
    assert settled.actor  # verified principal, never empty


async def test_deny_resolves_durable_approval_as_denied(approval_client) -> None:
    client, graph_store, approvals = approval_client
    await _seed_approval_pause(graph_store, approvals, run_id="hitl-apr-deny", request_id="apr-deny")

    response = client.post(
        "/v1/hitl/hitl-apr-deny/effect/answer",
        json={"approved": False, "expected_approval_request_id": "apr-deny"},
    )
    assert response.status_code == 200, response.text
    settled = await approvals.get("apr-deny")
    assert settled is not None
    assert settled.status is ApprovalStatus.DENIED


async def test_missing_approved_bool_is_422(approval_client) -> None:
    client, graph_store, approvals = approval_client
    await _seed_approval_pause(graph_store, approvals, run_id="hitl-apr-missing")

    response = client.post(
        "/v1/hitl/hitl-apr-missing/effect/answer",
        json={"expected_approval_request_id": "apr-55-1", "answer": "yes"},
    )
    assert response.status_code == 422
    assert await approvals.get("apr-55-1") is not None
    assert (await approvals.get("apr-55-1")).status is ApprovalStatus.PENDING


async def test_coerced_string_approved_is_rejected(approval_client) -> None:
    client, graph_store, approvals = approval_client
    await _seed_approval_pause(graph_store, approvals, run_id="hitl-apr-coerce")

    response = client.post(
        "/v1/hitl/hitl-apr-coerce/effect/answer",
        json={"approved": "true", "expected_approval_request_id": "apr-55-1"},
    )
    assert response.status_code == 422


async def test_stale_expected_request_id_is_409(approval_client) -> None:
    client, graph_store, approvals = approval_client
    await _seed_approval_pause(graph_store, approvals, run_id="hitl-apr-stale")

    response = client.post(
        "/v1/hitl/hitl-apr-stale/effect/answer",
        json={"approved": True, "expected_approval_request_id": "apr-old-ordinal"},
    )
    assert response.status_code == 409
    assert (await approvals.get("apr-55-1")).status is ApprovalStatus.PENDING


async def test_contrary_first_writer_wins_is_409(approval_client) -> None:
    client, graph_store, approvals = approval_client
    await _seed_approval_pause(
        graph_store, approvals, run_id="hitl-apr-contrary", request_id="apr-contrary"
    )
    await approvals.resolve("apr-contrary", approved=True, actor="first-writer")

    response = client.post(
        "/v1/hitl/hitl-apr-contrary/effect/answer",
        json={"approved": False, "expected_approval_request_id": "apr-contrary"},
    )
    assert response.status_code == 409
    assert "contrary" in response.json()["detail"]
    settled = await approvals.get("apr-contrary")
    assert settled is not None
    assert settled.status is ApprovalStatus.APPROVED
    assert settled.actor == "first-writer"


async def test_ordinary_human_pause_still_answers_without_approval_fields(
    admin_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-approval HITL pauses must not require the durable-approval contract."""
    from services import dag_agents

    store = InMemoryDurableRunStore()
    monkeypatch.setattr(dag_agents, "get_canonical_run_store", lambda: store)

    workspace = await create_workspace(
        creator_user_id="admin",
        name="Ordinary HITL",
        persona_template_id="default",
        checklist=[],
        theme_id="default",
        voice_tone_override=None,
    )
    from services.workspace_authority import canonical_store_for_tests

    root = await canonical_store_for_tests().project_store.root_for_workspace(workspace.id)
    graph = Graph(
        workspace_id=workspace.id,
        project_id=root.project_id,
        name="ask",
        nodes=[Node(node_id="ask", node_type="human.ask_question")],
    )
    run = transition_run(
        transition_run(
            transition_run(
                Run(
                    run_id="hitl-ordinary",
                    workspace_id=workspace.id,
                    project_id=root.project_id,
                    graph=GraphSnapshot.from_graph(graph),
                    actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
                ),
                RunStatus.QUEUED,
            ),
            RunStatus.RUNNING,
        ),
        RunStatus.PAUSED,
    )
    state = GraphExecutionState(
        run_id="hitl-ordinary",
        active_node_ids=("ask",),
        blackboard_snapshot={},
        metadata={
            "initial_inputs": {},
            "hitl_answers": {},
            "pauses": {"ask": {"kind": "hitl", "metadata": {"question": "Ship it?"}}},
        },
    )
    await store.create(
        DurableRunRecord(
            run=run,
            graph_state=state,
            node_runs=(_paused_node_run("hitl-ordinary", "ask", node_run_id="nr-ordinary"),),
            version=1,
        )
    )

    response = admin_client.post("/v1/hitl/hitl-ordinary/ask/answer", json={"answer": "yes"})
    assert response.status_code == 200, response.text
