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
    await _seed_approval_pause(
        graph_store, approvals, run_id="hitl-apr-deny", request_id="apr-deny"
    )

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


async def test_synthetic_binding_scope_still_answers(approval_client) -> None:
    """Self-repair Binding keeps default/default; Run uses hive workspace (#2423 P1)."""
    client, graph_store, approvals = approval_client
    workspace = await create_workspace(
        creator_user_id="admin",
        name="Approval WS-hitl-apr-synth",
        persona_template_id="default",
        checklist=[],
        theme_id="default",
        voice_tone_override=None,
    )
    from services.workspace_authority import canonical_store_for_tests

    root = await canonical_store_for_tests().project_store.root_for_workspace(workspace.id)
    run_id = "hitl-apr-synth"
    node_run_id = f"nr-{run_id}"
    await graph_store.create(
        _approval_paused_record(
            run_id,
            workspace_id=workspace.id,
            project_id=root.project_id,
            request_id="apr-synth",
            node_run_id=node_run_id,
        )
    )
    # governed_invocation stamps Binding scope (default/default), not the Run's.
    await approvals.create(
        DurableApproval(
            request=ApprovalRequest(
                request_id="apr-synth",
                action="infra_action",
                params={"request": {"action": "restart_container", "params": {"name": "x"}}},
                tier="policy",
                requester="self_repair",
            ),
            workspace_id="default",
            project_id="default",
            run_id=run_id,
            node_run_id=node_run_id,
            attempt_id="attempt-1",
            binding_id="binding-55",
            effect_key=_EFFECT_KEY,
            request_digest=_DIGEST,
        )
    )

    response = client.post(
        f"/v1/hitl/{run_id}/effect/answer",
        json={"approved": True, "expected_approval_request_id": "apr-synth"},
    )
    assert response.status_code == 200, response.text
    settled = await approvals.get("apr-synth")
    assert settled is not None and settled.status is ApprovalStatus.APPROVED
    assert settled.workspace_id == "default"
    assert settled.project_id == "default"
    assert workspace.id != "default"


async def test_elapsed_deadline_refuses_before_approval_resolve(approval_client) -> None:
    """An elapsed pause must not permanently resolve the ApprovalStore (#2423 P2)."""
    from datetime import UTC, datetime, timedelta

    client, graph_store, approvals = approval_client
    await _seed_approval_pause(
        graph_store, approvals, run_id="hitl-apr-deadline", request_id="apr-deadline"
    )
    record = await graph_store.get("hitl-apr-deadline")
    assert record is not None
    pauses = dict(record.graph_state.metadata["pauses"])
    pauses["effect"] = {
        **pauses["effect"],
        "resume_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
    }
    metadata = {**record.graph_state.metadata, "pauses": pauses}
    await graph_store.update(
        DurableRunRecord(
            run=record.run,
            graph_state=record.graph_state.model_copy(update={"metadata": metadata}),
            node_runs=record.node_runs,
            version=record.version + 1,
        )
    )

    response = client.post(
        "/v1/hitl/hitl-apr-deadline/effect/answer",
        json={"approved": True, "expected_approval_request_id": "apr-deadline"},
    )
    assert response.status_code == 409, response.text
    pending = await approvals.get("apr-deadline")
    assert pending is not None and pending.status is ApprovalStatus.PENDING


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


async def test_is_durable_approval_pause_false_without_metadata() -> None:
    from routes.hitl import _is_durable_approval_pause

    record = _approval_paused_record(
        "r-meta",
        workspace_id="ws",
        project_id="proj",
        request_id="apr",
    )
    # Drop pause metadata so the helper returns False via the None branch.
    pauses = dict(record.graph_state.metadata["pauses"])
    pauses["effect"] = {"kind": "hitl"}
    record = DurableRunRecord(
        run=record.run,
        graph_state=record.graph_state.model_copy(
            update={"metadata": {**record.graph_state.metadata, "pauses": pauses}}
        ),
        node_runs=record.node_runs,
        version=record.version,
    )
    assert _is_durable_approval_pause(record, "effect") is False
    assert _is_durable_approval_pause(record, "missing-node") is False


async def test_missing_expected_approval_request_id_is_422(approval_client) -> None:
    client, graph_store, approvals = approval_client
    await _seed_approval_pause(graph_store, approvals, run_id="hitl-apr-no-expected")

    response = client.post(
        "/v1/hitl/hitl-apr-no-expected/effect/answer",
        json={"approved": True},
    )
    assert response.status_code == 422
    assert "expected_approval_request_id" in response.json()["detail"]


async def test_approval_store_unavailable_is_503(
    approval_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from services.engine import get_engine

    client, graph_store, approvals = approval_client
    await _seed_approval_pause(graph_store, approvals, run_id="hitl-apr-no-store")

    engine = get_engine()
    monkeypatch.setattr(
        engine,
        "_agent_port",
        SimpleNamespace(container=SimpleNamespace(capability_effects=SimpleNamespace())),
    )
    response = client.post(
        "/v1/hitl/hitl-apr-no-store/effect/answer",
        json={"approved": True, "expected_approval_request_id": "apr-55-1"},
    )
    assert response.status_code == 503
    assert "ApprovalStore" in response.json()["detail"]


async def test_non_approver_authority_is_403(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-admin without approvals.resolve refuses at the durable-approval gate."""
    from types import SimpleNamespace

    from fastapi import HTTPException
    from routes.hitl import _require_approver_authority

    principal = SimpleNamespace(
        is_admin=False,
        actor_id=lambda: "user-plain",
    )
    monkeypatch.setattr("routes.hitl.require_principal", lambda _req: principal)
    monkeypatch.setattr("routes.hitl.principal_has_permission", lambda _p, _perm: False)
    audited: list[str] = []

    def _audit(event, *_a, **_k):
        audited.append(event)

    monkeypatch.setattr("routes.hitl.log_audit", _audit)
    monkeypatch.setattr("routes.hitl._session_principal", lambda _req: "user-plain")

    with pytest.raises(HTTPException) as excinfo:
        _require_approver_authority(SimpleNamespace())
    assert excinfo.value.status_code == 403
    assert "not authorized" in excinfo.value.detail
    assert audited == ["hitl_approval_resolve_refused"]


async def test_approval_mismatch_is_409(approval_client) -> None:
    client, graph_store, approvals = approval_client
    await _seed_approval_pause(
        graph_store, approvals, run_id="hitl-apr-mismatch", request_id="apr-mismatch"
    )
    loaded = await approvals.get("apr-mismatch")
    assert loaded is not None
    approvals._items["apr-mismatch"] = loaded.model_copy(update={"effect_key": "write:other"})

    response = client.post(
        "/v1/hitl/hitl-apr-mismatch/effect/answer",
        json={"approved": True, "expected_approval_request_id": "apr-mismatch"},
    )
    assert response.status_code == 409
    assert "effect_key" in response.json()["detail"]


async def test_paused_node_run_requires_exactly_one_match() -> None:
    from fastapi import HTTPException
    from routes.hitl import _paused_node_run as require_paused

    record = _approval_paused_record(
        "hitl-apr-nr",
        workspace_id="ws",
        project_id="proj",
        request_id="apr-nr",
        node_run_id="nr-1",
    )
    with pytest.raises(HTTPException) as empty:
        require_paused(
            DurableRunRecord(
                run=record.run,
                graph_state=record.graph_state,
                node_runs=(),
                version=1,
            ),
            "effect",
        )
    assert empty.value.status_code == 409

    first = record.node_runs[0]
    second = first.model_copy(update={"node_run_id": "nr-2", "ordinal": 2})
    with pytest.raises(HTTPException) as dup:
        require_paused(
            DurableRunRecord(
                run=record.run,
                graph_state=record.graph_state,
                node_runs=(first, second),
                version=1,
            ),
            "effect",
        )
    assert dup.value.status_code == 409
    assert "not awaiting" in dup.value.detail


async def test_approval_get_failure_and_missing_are_translated(
    approval_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, graph_store, approvals = approval_client
    await _seed_approval_pause(
        graph_store, approvals, run_id="hitl-apr-getfail", request_id="apr-getfail"
    )

    async def boom(_request_id: str):
        raise RuntimeError("store down")

    monkeypatch.setattr(approvals, "get", boom)
    response = client.post(
        "/v1/hitl/hitl-apr-getfail/effect/answer",
        json={"approved": True, "expected_approval_request_id": "apr-getfail"},
    )
    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"]

    await _seed_approval_pause(
        graph_store, approvals, run_id="hitl-apr-missing", request_id="apr-missing"
    )

    async def missing(_request_id: str):
        return None

    monkeypatch.setattr(approvals, "get", missing)
    response = client.post(
        "/v1/hitl/hitl-apr-missing/effect/answer",
        json={"approved": True, "expected_approval_request_id": "apr-missing"},
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


async def test_approval_resolve_keyerror_and_valueerror(
    approval_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, graph_store, approvals = approval_client
    await _seed_approval_pause(
        graph_store, approvals, run_id="hitl-apr-rkey", request_id="apr-rkey"
    )

    async def raise_key(*_a, **_k):
        raise KeyError("apr-rkey")

    monkeypatch.setattr(approvals, "resolve", raise_key)
    response = client.post(
        "/v1/hitl/hitl-apr-rkey/effect/answer",
        json={"approved": True, "expected_approval_request_id": "apr-rkey"},
    )
    assert response.status_code == 404

    await _seed_approval_pause(
        graph_store, approvals, run_id="hitl-apr-rval", request_id="apr-rval"
    )

    async def raise_val(*_a, **_k):
        raise ValueError("already resolved")

    monkeypatch.setattr(approvals, "resolve", raise_val)
    response = client.post(
        "/v1/hitl/hitl-apr-rval/effect/answer",
        json={"approved": True, "expected_approval_request_id": "apr-rval"},
    )
    assert response.status_code == 409
    assert "already resolved" in response.json()["detail"]


async def test_unanswerable_fence_valueerror_before_resolve() -> None:
    """ValueError from require_answerable_fence → 409 before ApprovalStore.resolve."""
    from fastapi import HTTPException
    from routes.hitl import _require_answerable_before_approval_resolve

    record = _approval_paused_record(
        "hitl-apr-fence",
        workspace_id="ws",
        project_id="proj",
        request_id="apr-fence",
    )
    # Node off the active frontier → ValueError (not HitlDeadlineElapsed).
    off_frontier = DurableRunRecord(
        run=record.run,
        graph_state=record.graph_state.model_copy(update={"active_node_ids": ()}),
        node_runs=record.node_runs,
        version=1,
    )
    with pytest.raises(HTTPException) as excinfo:
        _require_answerable_before_approval_resolve(off_frontier, "effect")
    assert excinfo.value.status_code == 409
    assert "frontier" in str(excinfo.value.detail)


async def test_node_pause_helpers_tolerate_malformed_pause_maps() -> None:
    from routes.hitl import _is_durable_approval_pause, _node_pause, _node_pause_metadata

    record = _approval_paused_record(
        "r-malformed",
        workspace_id="ws",
        project_id="proj",
        request_id="apr",
    )
    # pauses is not a Mapping → _node_pause returns None (line 134).
    broken = DurableRunRecord(
        run=record.run,
        graph_state=record.graph_state.model_copy(
            update={"metadata": {**record.graph_state.metadata, "pauses": ["not-a-map"]}}
        ),
        node_runs=record.node_runs,
        version=1,
    )
    assert _node_pause(broken, "effect") is None
    assert _node_pause_metadata(broken, "effect") is None
    assert _is_durable_approval_pause(broken, "effect") is False
