"""Optimizer target ownership gate (#2469) — two-Workspace ASGI evidence.

Before this gate the optimizer's five HTTP surfaces answered on bare global
ids: the lists returned every tenant's stored proposals (model-authored
rationale, source DAG identity, requested mutations, evaluation evidence),
a decision rewrote any proposal id unconditionally, and a run executed any
``dag_id`` under whichever Workspace the caller selected. Authentication
happens in AuthMiddleware; it is not authorization, and the coarse
``dags.write`` middleware grant for ``POST /v1/optimizer`` is a session
capability, not target-scoped authority.

The contract these tests pin, all through the real FastAPI ASGI stack with
the canonical Workspace/Project authority and the canonical template store:

- **Reads** (global and per-DAG lists) return only rows whose canonical
  owning Workspace — the DAG's registered GraphTemplate identity, else the
  server-recorded tenant of the triggering run — is in the caller's live
  membership universe. A foreign DAG shares one non-disclosing 404 with an
  unknown one; a principal with no Workspaces sees nothing.
- **Decisions** resolve the proposal through the same canonical identity
  and require live write membership there. A foreign actor's refusal writes
  nothing: no decision field, no audit-as-success, no candidate, no
  promotion, no provider execution. The authorized owner's acceptance
  promotes the immutable candidate under the gate-resolved tenant with the
  real actor named.
- **Runs** refuse a DAG bound to another tenant, a missing descriptor, and
  a Project that names another tenant, before any baseline or variant
  execution, Run, or proposal can exist.
- **Aliasing** — a forged Workspace field on a stored proposal, or a
  registration that contradicts the recordings — freezes the whole DAG's
  optimizer surface (visible to no one, decidable by no one) instead of
  rehoming it to whichever tenant asked.
- **Revocation** removes access through the live canonical store even while
  the session and its elevation remain valid.
- **Mutation control**: with the gate bypassed at its one seam, every one
  of the five endpoints exhibits the cross-tenant behavior the gate
  refuses — so removing the gate makes this suite fail.
"""

from __future__ import annotations

import asyncio
import copy
import pathlib
import sys
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

pytestmark = [pytest.mark.contract("boundary")]

_A_USER_ID = "admin"  # the session conftest seeds admin
_B_USER_ID = "optimizer-b"  # the second principal this module registers
_FOREIGN_TENANT = "tenant-foreign-registration"


def _wipe(store: Any) -> None:
    for key in list(store.keys()):
        store.pop(key)


@pytest.fixture(autouse=True)
def _isolated():
    """Fresh stores, metrics, and template store for every test."""
    import stores
    from services import edit_lock
    from services.feedback_service import InMemoryOutcomeStore, get_outcome_store, set_outcome_store
    from services.node_metrics_store import NodeMetricsStore
    from services.node_metrics_store import get_store as _get_metrics_store
    from services.node_metrics_store import set_store as _set_metrics_store
    from services.optimizer_candidates import set_template_store

    from maistro.graph.templates import InMemoryGraphTemplateStore
    from maistro.memory.exposure import MemoryExposureMode

    for target in (stores.audit_log, stores.eval_verdicts, stores.optimizer_proposals, stores.dags):
        _wipe(target)
    edit_lock.clear()
    prev_fb = get_outcome_store()
    set_outcome_store(InMemoryOutcomeStore(exposure_mode=MemoryExposureMode.AGENT_MANAGED))
    prev_m = _get_metrics_store()
    _set_metrics_store(NodeMetricsStore())
    template_store = InMemoryGraphTemplateStore()
    set_template_store(template_store)
    yield template_store
    set_template_store(None)
    for target in (stores.audit_log, stores.eval_verdicts, stores.optimizer_proposals, stores.dags):
        _wipe(target)
    edit_lock.clear()
    set_outcome_store(prev_fb)
    _set_metrics_store(prev_m)


@pytest.fixture
def client_b() -> Any:
    """A real second principal: coarse `dags.write`, no Workspace yet.

    Registered like `tests.test_hitl_door.reviewer_client`: the route
    permission is assigned AND elevated, so anything these tests prove is
    refused is refused by target authorization, not by the middleware.
    """
    import stores
    from fastapi.testclient import TestClient
    from main import app

    stores.users[_B_USER_ID] = stores.users["user"].model_copy(
        update={
            "id": _B_USER_ID,
            "username": _B_USER_ID,
            "permissions": ["dags.write"],
        }
    )
    client = TestClient(app)
    try:
        login = client.post("/v1/auth/login", json={"username": _B_USER_ID, "password": "testpass"})
        assert login.status_code == 200
        elevated = client.post(
            "/v1/auth/elevate",
            json={
                "password": "testpass",
                "permissions": ["dags.write"],
                "task_id": "optimizer-ownership-b",
            },
        )
        assert elevated.status_code == 200
        yield client
    finally:
        stores.users.pop(_B_USER_ID, None)


@pytest.fixture
def client_c() -> Any:
    """An authenticated principal with no permissions and no Workspaces."""
    import stores
    from fastapi.testclient import TestClient
    from main import app

    stores.users["optimizer-c"] = stores.users["user"].model_copy(
        update={"id": "optimizer-c", "username": "optimizer-c", "permissions": []}
    )
    client = TestClient(app)
    try:
        login = client.post(
            "/v1/auth/login", json={"username": "optimizer-c", "password": "testpass"}
        )
        assert login.status_code == 200
        yield client
    finally:
        stores.users.pop("optimizer-c", None)


def _seed_metrics(dag_id: str, node_id: str) -> None:
    from services.node_metrics_store import NodeObservation, get_store

    store = get_store()
    for i in range(10):
        store.append(
            NodeObservation(
                run_id=f"r-{i}",
                node_id=node_id,
                node_kind="worker",
                project_id="p",
                dag_id=dag_id,
                phase="FAILED" if i < 8 else "COMPLETED",
                latency_ms=100,
                tokens_in=0,
                tokens_out=0,
                cost_usd=0.0,
                model_used="",
            )
        )


def _workspace(client: Any, name: str) -> str:
    """A Workspace the calling principal owns (the creator becomes owner)."""
    response = client.post("/v1/workspaces", json={"persona_template_id": "pm_fleet", "name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _dag(client: Any, name: str) -> dict[str, Any]:
    response = client.post(
        "/v1/dags", json={"name": name, "description": "optimizer ownership test"}
    )
    assert response.status_code == 201, response.text
    return response.json()


def _seed_verdict(dag_id: str, node_id: str, run_id: str) -> None:
    """Eval evidence that becomes a topology (propose-only) proposal."""
    import stores

    stores.eval_verdicts[run_id] = {
        "run_id": run_id,
        "dag_id": dag_id,
        "score": 42,
        "rationale": f"B-authored rationale for {dag_id}",
        "status": "ok",
        "evaluator_version": "eval-judge/1",
        "topology_proposal": {
            "kind": "swap_model",
            "target_node_id": node_id,
            "from_value": "m-a",
            "to_value": "m-strong",
            "expected_improvement": "stronger model clears the failures",
        },
        "scored_at": "2026-09-01T12:00:00+00:00",
    }


def _proposals_via_route(
    client: Any, dag: dict[str, Any], workspace_id: str
) -> list[dict[str, Any]]:
    """One real optimizer pass over the caller's route — the write path that
    records the authorized Workspace onto every proposal it mints."""
    _seed_metrics(dag["id"], dag["nodes"][1]["id"])
    _seed_verdict(dag["id"], dag["nodes"][1]["id"], f"run-{dag['id']}")
    response = client.post(
        f"/v1/optimizer/{dag['id']}/run?validate=false&workspace_id={workspace_id}"
    )
    assert response.status_code == 200, response.text
    proposals = response.json()["proposals"]
    assert proposals
    return proposals


def _audit_actions() -> list[dict[str, Any]]:
    import stores

    return [entry for entry in stores.audit_log.values() if isinstance(entry, dict)]


def _audit_proposal_entries(proposal_id: str) -> list[dict[str, Any]]:
    return [
        entry
        for entry in _audit_actions()
        if isinstance(entry.get("detail"), dict)
        and entry["detail"].get("proposal_id") == proposal_id
    ]


# --- AC 1: reads disclose only the caller's membership universe -----------


def test_global_list_discloses_nothing_cross_tenant(
    admin_client: Any, client_b: Any, client_c: Any, _isolated: Any
) -> None:
    workspace_a = _workspace(admin_client, "Tenant A")
    workspace_b = _workspace(client_b, "Tenant B")
    dag_a = _dag(admin_client, "Tenant A DAG")
    dag_b = _dag(client_b, "Tenant B DAG")
    proposals_a = _proposals_via_route(admin_client, dag_a, workspace_a)
    proposals_b = _proposals_via_route(client_b, dag_b, workspace_b)

    seen_a = admin_client.get("/v1/optimizer/proposals")
    assert seen_a.status_code == 200
    rows = seen_a.json()
    ids_a = {row["id"] for row in rows}
    assert ids_a
    assert ids_a == {row["id"] for row in proposals_a}
    # B's proposal identity, rationale, and DAG identity appear nowhere.
    blob = str(rows)
    assert dag_b["id"] not in blob
    for proposal in proposals_b:
        assert proposal["id"] not in blob
    assert f"B-authored rationale for {dag_b['id']}" not in blob

    seen_b = client_b.get("/v1/optimizer/proposals")
    assert seen_b.status_code == 200
    assert {row["id"] for row in seen_b.json()} == {row["id"] for row in proposals_b}

    # An authenticated-but-unprivileged principal sees only its own
    # membership universe — which is empty, so nothing.
    seen_c = client_c.get("/v1/optimizer/proposals")
    assert seen_c.status_code == 200
    assert seen_c.json() == []


def test_dag_list_refuses_foreign_and_unknown_dags_identically(
    admin_client: Any, client_b: Any, _isolated: Any
) -> None:
    workspace_a = _workspace(admin_client, "Tenant A")
    workspace_b = _workspace(client_b, "Tenant B")
    _dag(admin_client, "Tenant A DAG")
    dag_b = _dag(client_b, "Tenant B DAG")
    _proposals_via_route(client_b, dag_b, workspace_b)
    _proposals_via_route(admin_client, _dag(admin_client, "Second A DAG"), workspace_a)

    foreign = admin_client.get(f"/v1/optimizer/{dag_b['id']}/proposals")
    assert foreign.status_code == 404
    unknown = admin_client.get("/v1/optimizer/does-not-exist/proposals")
    assert unknown.status_code == 404
    assert foreign.json()["detail"] == unknown.json()["detail"]

    own = client_b.get(f"/v1/optimizer/{dag_b['id']}/proposals")
    assert own.status_code == 200
    assert own.json()
    assert all(row["dag_id"] == dag_b["id"] for row in own.json())


# --- AC 2: a foreign actor's decision writes nothing -----------------------


def test_viewer_member_can_read_but_not_decide(
    admin_client: Any, client_b: Any, _isolated: Any
) -> None:
    """A member without write authority is forbidden, not foreign: the
    lists still disclose the member universe, but decisions answer 403."""
    from services import workspace_authority

    workspace = _workspace(admin_client, "Shared Tenant")
    asyncio.run(workspace_authority.set_member(workspace, user_id=_B_USER_ID, role="viewer"))
    dag = _dag(admin_client, "Shared Tenant DAG")
    proposals = _proposals_via_route(admin_client, dag, workspace)
    target = proposals[0]

    assert client_b.get(f"/v1/optimizer/{dag['id']}/proposals").status_code == 200
    response = client_b.post(f"/v1/optimizer/proposals/{target['id']}/accept")
    assert response.status_code == 403
    import stores

    assert stores.optimizer_proposals[target["id"]]["decision"] == "pending"


def test_foreign_decision_is_404_and_writes_nothing(
    admin_client: Any, client_b: Any, _isolated: Any
) -> None:
    import stores

    workspace_b = _workspace(client_b, "Tenant B")
    dag_b = _dag(client_b, "Tenant B DAG")
    proposals = _proposals_via_route(client_b, dag_b, workspace_b)
    target = next(p for p in proposals if p["kind"] == "topology_mutation")

    before = copy.deepcopy(dict(stores.optimizer_proposals.items()))
    versions_before = asyncio.run(_isolated.versions(dag_b["id"]))

    for action in ("accept", "reject"):
        response = admin_client.post(f"/v1/optimizer/proposals/{target['id']}/{action}")
        assert response.status_code == 404, response.text

    # Zero proposal modification.
    assert dict(stores.optimizer_proposals.items()) == before
    stored = stores.optimizer_proposals[target["id"]]
    assert stored["decision"] == "pending"
    assert not stored.get("decided_by")
    assert not stored.get("decided_at")
    # Zero audit as a successful decision.
    assert _audit_proposal_entries(target["id"]) == []
    # Zero candidate / promotion.
    assert asyncio.run(_isolated.versions(dag_b["id"])) == versions_before


def test_owner_decision_promotes_with_real_actor_and_canonical_tenant(
    client_b: Any, _isolated: Any
) -> None:
    import stores

    from maistro.graph.templates import GraphTemplateNotFound

    workspace_b = _workspace(client_b, "Tenant B")
    dag_b = _dag(client_b, "Tenant B DAG")
    proposals = _proposals_via_route(client_b, dag_b, workspace_b)
    target = next(p for p in proposals if p["kind"] == "topology_mutation")

    response = client_b.post(f"/v1/optimizer/proposals/{target['id']}/accept")
    assert response.status_code == 200, response.text
    decided = response.json()
    assert decided["decision"] == "accepted"
    assert decided["decided_by"] == _B_USER_ID
    # The immutable candidate promoted under the gate-resolved tenant.
    assert decided["workspace_id"] == workspace_b
    assert decided["applied"] is True
    assert decided["resulting_version"] == 1
    assert asyncio.run(_isolated.versions(dag_b["id"])) == [1]
    lifecycle = asyncio.run(_isolated.lifecycle_of(dag_b["id"], 1))
    assert lifecycle == "active"

    decisions = [
        entry
        for entry in _audit_actions()
        if entry.get("action") == "optimizer_decision" and entry.get("actor") == _B_USER_ID
    ]
    assert decisions, "the decision must be audited by the real actor"
    assert any(entry.get("detail", {}).get("proposal_id") == target["id"] for entry in decisions)
    promotions = [
        entry
        for entry in _audit_actions()
        if entry.get("actor") == _B_USER_ID and "promot" in str(entry.get("action", ""))
    ]
    assert promotions, "the promotion trail must name the accepting actor"
    # The descriptor surface synced to the promoted content (#861): the
    # accepted topology change is visible in the editable record.
    assert any(
        node["id"] == target["target_node_id"] and node.get("model") == "m-strong"
        for node in stores.dags[dag_b["id"]]["nodes"]
    )

    # And the decision is a real lifecycle fact, not a display value.
    with pytest.raises(GraphTemplateNotFound):
        asyncio.run(_isolated.lifecycle_of(dag_b["id"], 99))


# --- AC 3: revocation closes access though the session is still valid ------


def test_revoked_member_loses_access_with_valid_session(
    admin_client: Any, client_b: Any, _isolated: Any
) -> None:
    from services import workspace_authority

    workspace_b = _workspace(client_b, "Tenant B")
    dag_b = _dag(client_b, "Tenant B DAG")
    proposals = _proposals_via_route(client_b, dag_b, workspace_b)
    target = proposals[0]

    # Hand ownership to a neutral principal, then revoke B through the
    # canonical authority. B's session cookie and elevation stay valid.
    asyncio.run(
        workspace_authority.set_member(workspace_b, user_id="revocation-owner", role="owner")
    )
    asyncio.run(workspace_authority.remove_member(workspace_b, user_id=_B_USER_ID))

    assert client_b.post(f"/v1/optimizer/proposals/{target['id']}/accept").status_code == 404
    assert client_b.get(f"/v1/optimizer/{dag_b['id']}/proposals").status_code == 404
    assert client_b.get("/v1/optimizer/proposals").json() == []
    # The Workspace selection seam refuses a revoked member on sight (403,
    # its historical posture); the proposal surface answers the same events
    # with the non-disclosing 404 because there the target is named by id.
    run_again = client_b.post(
        f"/v1/optimizer/{dag_b['id']}/run?workspace_id={workspace_b}&validate=false"
    )
    assert run_again.status_code == 403


# --- AC 4: a run cannot execute, project, or mint across tenants -----------


def test_run_refuses_foreign_dag_without_execution_or_proposals(
    admin_client: Any, client_b: Any, _isolated: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import services.graph_runner as graph_runner
    import stores
    from services.optimizer import list_proposals

    executions: list[Any] = []

    async def _record_execution(*args: Any, **kwargs: Any) -> dict[str, Any]:
        executions.append(args)
        return {"status": "completed", "run_id": "should-not-exist", "node_results": {}}

    monkeypatch.setattr(graph_runner, "execute_dag", _record_execution)

    workspace_a = _workspace(admin_client, "Tenant A")
    workspace_b = _workspace(client_b, "Tenant B")
    dag_b = _dag(client_b, "Tenant B DAG")
    _proposals_via_route(client_b, dag_b, workspace_b)
    descriptor_before = copy.deepcopy(dict(stores.dags.get(dag_b["id"], {})))

    def _optimizer_run_facts() -> list[tuple[str, str]]:
        return sorted(
            (str(entry.get("actor", "")), str(entry.get("target", "")))
            for entry in _audit_actions()
            if entry.get("action") == "optimizer_run"
        )

    runs_before = _optimizer_run_facts()

    response = admin_client.post(
        f"/v1/optimizer/{dag_b['id']}/run?workspace_id={workspace_a}&validate=false"
    )
    assert response.status_code == 404

    # No baseline or variant execution, no new Run, no cross-tenant
    # mutation, and no proposals minted into the caller's Workspace.
    assert executions == []
    assert list_proposals(workspace_id=workspace_a) == []
    assert dict(stores.dags.get(dag_b["id"], {})) == descriptor_before
    assert _optimizer_run_facts() == runs_before

    # Missing registered ownership: no descriptor at all.
    absent = admin_client.post(
        f"/v1/optimizer/never-registered/run?workspace_id={workspace_a}&validate=false"
    )
    assert absent.status_code == 404
    assert absent.json()["detail"] == response.json()["detail"]


def test_run_rejects_a_project_from_another_tenant(
    admin_client: Any, client_b: Any, _isolated: Any
) -> None:
    from services.workspace_authority import canonical_store_for_tests

    workspace_a = _workspace(admin_client, "Tenant A")
    workspace_b = _workspace(client_b, "Tenant B")
    dag_b = _dag(client_b, "Tenant B DAG")
    _proposals_via_route(client_b, dag_b, workspace_b)

    store = canonical_store_for_tests()
    foreign_project = asyncio.run(store.project_store.root_for_workspace(workspace_b))

    response = admin_client.post(
        f"/v1/optimizer/{dag_b['id']}/run"
        f"?workspace_id={workspace_a}&project_id={foreign_project.project_id}&validate=false"
    )
    assert response.status_code == 403
    assert "not authorized" in response.json()["detail"]


def test_owner_run_still_execures_and_claims_the_dag(client_b: Any, _isolated: Any) -> None:
    workspace_b = _workspace(client_b, "Tenant B")
    dag_b = _dag(client_b, "Tenant B DAG")

    proposals = _proposals_via_route(client_b, dag_b, workspace_b)
    assert proposals
    assert all(row["workspace_id"] == workspace_b for row in proposals)


# --- AC 5: aliasing cannot redirect or bypass the target gate --------------


def test_forged_workspace_field_freezes_the_surface(
    admin_client: Any, client_b: Any, _isolated: Any
) -> None:
    import stores

    workspace_a = _workspace(admin_client, "Tenant A")
    workspace_b = _workspace(client_b, "Tenant B")
    dag_b = _dag(client_b, "Tenant B DAG")
    proposals = _proposals_via_route(client_b, dag_b, workspace_b)
    target = proposals[0]

    # A stale/forged copy of B's proposal, rebranded into A's tenant.
    forged = copy.deepcopy(stores.optimizer_proposals[target["id"]])
    forged["id"] = "forged-proposal-id"
    forged["workspace_id"] = workspace_a
    stores.optimizer_proposals[forged["id"]] = forged

    # A's lists disclose neither the forged row nor, while the conflict
    # stands, the frozen original surface.
    rows_a = admin_client.get("/v1/optimizer/proposals").json()
    assert target["id"] not in {row["id"] for row in rows_a}
    assert "forged-proposal-id" not in {row["id"] for row in rows_a}
    assert admin_client.post("/v1/optimizer/proposals/forged-proposal-id/accept").status_code == 404
    assert admin_client.post(f"/v1/optimizer/proposals/{target['id']}/accept").status_code == 404
    # B is frozen out too — the aliasing fault is fail-closed for everyone,
    # never silently rehomed onto an authorized but unrelated Workspace.
    assert client_b.post(f"/v1/optimizer/proposals/{target['id']}/accept").status_code == 404
    assert client_b.get(f"/v1/optimizer/{dag_b['id']}/proposals").status_code == 404

    # Remove the forgery and the honest surface resolves again.
    stores.optimizer_proposals.pop("forged-proposal-id")
    assert client_b.post(f"/v1/optimizer/proposals/{target['id']}/accept").status_code == 200


def test_registration_contradicting_the_recordings_is_refused(
    admin_client: Any, client_b: Any, _isolated: Any
) -> None:
    workspace_b = _workspace(client_b, "Tenant B")
    dag_b = _dag(client_b, "Tenant B DAG")
    proposals = _proposals_via_route(client_b, dag_b, workspace_b)
    target = proposals[0]

    import copy as _copy

    import stores
    from services.optimizer_candidates import template_store as _template_store

    from maistro.graph.template_adapter import snapshot_to_template

    descriptor = _copy.deepcopy(stores.dags[dag_b["id"]])
    foreign = snapshot_to_template(
        descriptor,
        workspace_id=_FOREIGN_TENANT,
        template_id=dag_b["id"],
        version=1,
    ).model_copy(update={"lifecycle": "candidate"})
    asyncio.run(_template_store().put(foreign))

    # The registration contradicts every proposal recording: nothing is
    # rehomed onto either tenant, and no decision can slip through.
    assert client_b.get(f"/v1/optimizer/{dag_b['id']}/proposals").status_code == 404
    assert client_b.post(f"/v1/optimizer/proposals/{target['id']}/accept").status_code == 404
    assert (
        client_b.post(
            f"/v1/optimizer/{dag_b['id']}/run?workspace_id={workspace_b}&validate=false"
        ).status_code
        == 404
    )
    foreign_view = admin_client.get(f"/v1/optimizer/{dag_b['id']}/proposals")
    assert foreign_view.status_code == 404


# --- Mutation control: removing the gate flips every endpoint --------------


@pytest.mark.parametrize(
    ("endpoint", "act"),
    [
        (
            "global-list",
            lambda admin_client, client_b, state: admin_client.get("/v1/optimizer/proposals"),
        ),
        (
            "dag-list",
            lambda admin_client, client_b, state: admin_client.get(
                f"/v1/optimizer/{state['dag_b']['id']}/proposals"
            ),
        ),
        (
            "accept",
            lambda admin_client, client_b, state: admin_client.post(
                f"/v1/optimizer/proposals/{state['target']['id']}/accept"
            ),
        ),
        (
            "reject",
            lambda admin_client, client_b, state: admin_client.post(
                f"/v1/optimizer/proposals/{state['target']['id']}/reject"
            ),
        ),
        (
            "run",
            lambda admin_client, client_b, state: admin_client.post(
                f"/v1/optimizer/{state['dag_b']['id']}/run"
                f"?workspace_id={state['workspace_a']}&validate=false"
            ),
        ),
    ],
)
def test_gate_removal_flips_the_refusal(
    endpoint: str,
    act: Any,
    admin_client: Any,
    client_b: Any,
    _isolated: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the target gate bypassed at its one seam, each of the five
    endpoints answers the cross-tenant request the gate refuses — so
    removing `services.optimizer_scope` authorization makes this suite
    fail, endpoint by endpoint."""
    import services.optimizer_scope as optimizer_scope
    from services.dag_execution_scope import DagExecutionScope

    workspace_a = _workspace(admin_client, "Tenant A")
    workspace_b = _workspace(client_b, "Tenant B")
    dag_b = _dag(client_b, "Tenant B DAG")
    proposals = _proposals_via_route(client_b, dag_b, workspace_b)
    target = proposals[0]
    state = {"workspace_a": workspace_a, "dag_b": dag_b, "target": target}

    if endpoint == "global-list":

        async def _unscoped_list(
            user_id: str, *, decision: str = "", limit: int = 50
        ) -> list[dict[str, Any]]:
            from services.optimizer import list_proposals

            return list_proposals(decision=decision, limit=limit)

        monkeypatch.setattr(optimizer_scope, "visible_proposals", _unscoped_list)
    elif endpoint == "dag-list":

        async def _unscoped_dag_list(
            user_id: str, dag_id: str, *, decision: str = "", limit: int = 50
        ) -> list[dict[str, Any]]:
            from services.optimizer import list_proposals

            return list_proposals(dag_id=dag_id, decision=decision, limit=limit)

        monkeypatch.setattr(optimizer_scope, "visible_dag_proposals", _unscoped_dag_list)
    elif endpoint in {"accept", "reject"}:

        async def _any_proposal(user_id: str, proposal_id: str) -> optimizer_scope.OptimizerTarget:
            import stores

            payload = stores.optimizer_proposals[proposal_id]
            return optimizer_scope.OptimizerTarget(
                dag_id=str(payload.get("dag_id", "")),
                workspace_id=str(payload.get("workspace_id", "")),
                proposal_id=proposal_id,
            )

        monkeypatch.setattr(optimizer_scope, "authorize_proposal_decision", _any_proposal)
    else:

        async def _any_scope(
            user_id: str, dag_id: str, *, workspace_id: str, project_id: str | None = None
        ) -> DagExecutionScope:
            from services.workspace_authority import canonical_store_for_tests

            project = await canonical_store_for_tests().project_store.root_for_workspace(
                workspace_id
            )
            return DagExecutionScope(
                workspace_id=workspace_id, project_id=project.project_id, user_id=user_id
            )

        monkeypatch.setattr(optimizer_scope, "authorize_dag_run", _any_scope)

    response = act(admin_client, client_b, state)
    assert response.status_code == 200, f"{endpoint} must leak once the gate is bypassed"
    body = response.json()
    if endpoint in {"global-list", "dag-list"}:
        assert target["id"] in {row["id"] for row in body}
    elif endpoint in {"accept", "reject"}:
        assert body["decided_by"] == _A_USER_ID
    else:
        assert all(row["workspace_id"] == workspace_a for row in body["proposals"])
