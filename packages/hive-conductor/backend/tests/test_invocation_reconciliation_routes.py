"""The operator HTTP door uses real SQLite effect state and canonical scope."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import aiosqlite
import httpx
import pytest
from fastapi import FastAPI
from middleware.auth import AuthMiddleware
from routes import invocations

from maistro.capabilities.binding import Binding
from maistro.capabilities.effect_context import binding_scope_policy, new_effect_context
from maistro.capabilities.invocation import Invocation, InvocationStatus, UnsafeEffectRetry
from maistro.capabilities.invocation_store import SqliteInvocationStore
from maistro.capabilities.operator_reconciliation import (
    INVOCATIONS_INSPECT,
    INVOCATIONS_RECONCILE,
    OperatorInvocationReconciliation,
)
from maistro.graph import Graph, Node
from maistro.projects.scope import ProjectMembership
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.quota.invocation_quota import QuotaBudget, QuotaEstimate
from maistro.quota.sqlite_invocation_quota import SqliteInvocationQuota
from maistro.runs import InMemoryRunStore, RunExecutionService, RunStatus
from maistro.runs.store import RunIntegrityError
from maistro.runtime import PythonExecutionRuntime
from maistro.workspaces.store import InMemoryWorkspaceStore


@dataclass(frozen=True)
class Provider:
    name: str = "provider"
    slot: str = "external_write"
    trust_tier: str = "trusted"


async def resolver(_binding: Binding) -> Provider:
    return Provider()


async def estimate(_invocation, _binding):
    return QuotaEstimate(principal_id="operator")


@pytest.fixture
async def door(tmp_path, monkeypatch):
    path = tmp_path / "effects.sqlite"
    async with aiosqlite.connect(path) as connection:
        store = SqliteInvocationStore(connection)
        await store.ensure_schema()
        quota = SqliteInvocationQuota(path, estimate=estimate, clock=lambda: 100)
        await quota.ensure_schema()
        await quota.register_budget(
            QuotaBudget(
                budget_id="requests",
                unit="requests",
                limit=100,
                period_start=0,
                period_end=1000,
                provider_name="provider",
                opening_spend=0,
                coverage_ref="fixture-fresh-period",
            )
        )
        effects = new_effect_context(
            invocation_store=store, policy_evaluator=binding_scope_policy, quota=quota
        )
        projects = InMemoryProjectScopeStore()
        workspaces = InMemoryWorkspaceStore(project_store=projects)
        await workspaces.create(creator_user_id="operator", name="One", workspace_id="ws")
        root = await projects.root_for_workspace("ws")
        project = await projects.create(
            workspace_id="ws", parent_project_id=root.project_id, name="P"
        )
        sibling = await projects.create(
            workspace_id="ws", parent_project_id=root.project_id, name="Q"
        )
        await projects.set_membership(
            ProjectMembership(
                workspace_id="ws",
                project_id=project.project_id,
                principal_id="operator",
                grants={INVOCATIONS_INSPECT, INVOCATIONS_RECONCILE},
            )
        )
        service = OperatorInvocationReconciliation(effects, workspaces, projects)
        app = FastAPI()
        app.include_router(invocations.router, prefix="/v1/invocations")
        app.dependency_overrides[invocations.operator_service] = lambda: service
        app.add_middleware(AuthMiddleware)
        users = {
            "operator": {
                "id": "operator",
                "role": "user",
                "permissions": [INVOCATIONS_INSPECT, INVOCATIONS_RECONCILE],
                "elevated_permissions": [INVOCATIONS_INSPECT, INVOCATIONS_RECONCILE],
            },
            "config": {
                "id": "operator",
                "role": "user",
                "permissions": ["config.write"],
                "elevated_permissions": ["config.write"],
            },
            "foreign": {
                "id": "foreign",
                "role": "admin",
                "permissions": [INVOCATIONS_INSPECT, INVOCATIONS_RECONCILE],
                "elevated_permissions": [INVOCATIONS_INSPECT, INVOCATIONS_RECONCILE],
            },
            "admin": {"id": "operator", "role": "admin"},
        }
        monkeypatch.setattr(
            AuthMiddleware,
            "_get_user",
            lambda _self, request: users.get(request.headers.get("authorization")),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"authorization": "operator"},
        ) as client:
            yield SimpleNamespace(
                client=client,
                effects=effects,
                store=store,
                service=service,
                app=app,
                projects=projects,
                workspaces=workspaces,
                project=project,
                root=root,
                sibling=sibling,
                path=path,
                binding=Binding(
                    binding_id="binding",
                    workspace_id="ws",
                    project_id=project.project_id,
                    capability="external_write",
                    config={"api_key": "sk-secret-test-value"},
                ),
            )


async def invoke(door, executor, *, attempt="attempt-1", run="run-1", binding=None):
    return await door.effects.invocations.invoke(
        binding=binding or door.binding,
        run_id=run,
        node_run_id="node-run-1",
        attempt_id=attempt,
        effect_key="write:1",
        request={"name": "remote-item"},
        resolver=resolver,
        executor=executor,
    )


async def unknown(door):
    async def lost(_provider, _request):
        raise ConnectionError("lost response")

    with pytest.raises(ConnectionError):
        await invoke(door, lost)
    return (await door.effects.invocations.discover_ambiguous(stale_before=datetime.now(UTC)))[0]


def resolution(door, item, **changes):
    body = {
        "workspace_id": "ws",
        "project_id": door.project.project_id,
        "expected_revision": item.revision,
        "disposition": "not_applied",
        "reason": "Provider status lookup confirmed absence",
        "evidence": {"lookup": "absent"},
    }
    body.update(changes)
    return body


def scope(door):
    return {"workspace_id": "ws", "project_id": door.project.project_id}


async def test_applied_resolution_is_durable_and_replays_without_dispatch(door):
    item = await unknown(door)
    assert (await door.effects.quota.balance("requests")).held == 1
    listing = await door.client.get(
        "/v1/invocations", params={**scope(door), "stale_before": datetime.now(UTC).isoformat()}
    )
    assert listing.status_code == 200
    assert [row["invocation_id"] for row in listing.json()["items"]] == [item.invocation_id]
    assert "api_key" not in listing.text and "sk-secret" not in listing.text
    response = await door.client.post(
        f"/v1/invocations/{item.invocation_id}/reconcile",
        json=resolution(
            door,
            item,
            disposition="applied",
            evidence={"remote_id": "remote-1"},
            result={"id": "remote-1"},
            usage={"input_units": 2},
        ),
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed"
    balance = await door.effects.quota.balance("requests")
    assert balance.held == 0 and balance.spent == 1

    async def forbidden(_provider, _request):
        pytest.fail("confirmed applied effect must not be dispatched again")

    replay = await invoke(door, forbidden, attempt="attempt-2")
    assert replay.invocation_id == item.invocation_id
    assert replay.result == {"id": "remote-1"}
    assert replay.usage.input_units == 2
    async with aiosqlite.connect(door.path) as reopened:
        saved = await SqliteInvocationStore(reopened).get(item.invocation_id)
    assert saved.reconciliation_history[-1].actor == "operator"
    assert saved.reconciliation_history[-1].source == "operator-api"
    assert saved.reconciliation_history[-1].evidence == {"remote_id": "remote-1"}


async def test_not_applied_allows_one_governed_dispatch_and_stale_form_is_conflict(door):
    item = await unknown(door)
    url = f"/v1/invocations/{item.invocation_id}/reconcile"
    body = resolution(door, item)
    response = await door.client.post(url, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "failed"
    balance = await door.effects.quota.balance("requests")
    assert balance.held == balance.spent == 0
    assert (await door.client.post(url, json=body)).status_code == 409
    calls = 0
    started, finish = asyncio.Event(), asyncio.Event()

    async def provider(_provider, _request):
        nonlocal calls
        calls += 1
        started.set()
        await finish.wait()
        return "done"

    retry = asyncio.create_task(invoke(door, provider, attempt="attempt-2"))
    await started.wait()
    try:
        with pytest.raises(UnsafeEffectRetry):
            await invoke(door, provider, attempt="attempt-3")
    finally:
        finish.set()
    assert (await retry).status is InvocationStatus.COMPLETED
    assert calls == 1
    assert (await door.effects.quota.balance("requests")).spent == 1


async def test_indeterminate_stays_blocked_and_requires_new_revision_for_new_evidence(door):
    item = await unknown(door)
    url = f"/v1/invocations/{item.invocation_id}/reconcile"
    response = await door.client.post(
        url, json=resolution(door, item, disposition="indeterminate", evidence=None)
    )
    assert response.status_code == 200
    assert response.json()["status"] == "unknown"
    assert (await door.effects.quota.balance("requests")).held == 1
    assert (await door.client.post(url, json=resolution(door, item))).status_code == 409
    with pytest.raises(UnsafeEffectRetry):
        await invoke(
            door, lambda *_: pytest.fail("ambiguous effect dispatched"), attempt="attempt-2"
        )


@pytest.mark.parametrize("identity,status", [("", 401), ("config", 403), ("foreign", 404)])
async def test_authentication_and_both_authority_layers_refuse(door, identity, status):
    item = await unknown(door)
    response = await door.client.post(
        f"/v1/invocations/{item.invocation_id}/reconcile",
        headers={"authorization": identity},
        json=resolution(door, item),
    )
    assert response.status_code == status
    assert (await door.store.get(item.invocation_id)).reconciliation_history == ()


async def test_exact_scope_revocation_and_inherited_denies_refuse_without_disclosure(door):
    item = await unknown(door)
    url = f"/v1/invocations/{item.invocation_id}/reconcile"
    # A grant in P does not authorize its sibling Q, even for the Workspace owner.
    assert (
        await door.client.post(url, json=resolution(door, item, project_id=door.sibling.project_id))
    ).status_code == 404
    await door.projects.set_membership(
        ProjectMembership(
            workspace_id="ws",
            project_id=door.root.project_id,
            principal_id="operator",
            denies={INVOCATIONS_INSPECT, INVOCATIONS_RECONCILE},
        )
    )
    assert (
        await door.client.get(f"/v1/invocations/{item.invocation_id}", params=scope(door))
    ).status_code == 404
    assert (await door.client.post(url, json=resolution(door, item))).status_code == 404
    assert (await door.store.get(item.invocation_id)).reconciliation_history == ()


async def test_live_dispatch_cannot_be_released_by_operator_evidence(door):
    entered, finish = asyncio.Event(), asyncio.Event()

    async def provider(_provider, _request):
        entered.set()
        await finish.wait()
        return "done"

    running = asyncio.create_task(invoke(door, provider))
    await entered.wait()
    try:
        item = (
            await door.store.list_effect(
                run_id="run-1", node_run_id="node-run-1", binding_id="binding", effect_key="write:1"
            )
        )[0]
        response = await door.client.post(
            f"/v1/invocations/{item.invocation_id}/reconcile",
            json=resolution(door, item, stale_before=datetime.now(UTC).isoformat()),
        )
        assert response.status_code == 409
        assert (await door.store.get(item.invocation_id)).status is InvocationStatus.RUNNING
    finally:
        finish.set()
        await running


@pytest.mark.parametrize(
    "change",
    [
        {"actor": "forged"},
        {"source": "provider"},
        {"expected_revision": True},
        {"evidence": {}},
        {"evidence": {"api_key": "secret-value"}},
        {"stale_before": (datetime.now(UTC) + timedelta(days=1)).isoformat()},
        {"stale_before": "2020-01-01T00:00:00"},
        {"result": "pretend success"},
    ],
)
async def test_invalid_or_spoofed_evidence_never_mutates(door, change):
    item = await unknown(door)
    response = await door.client.post(
        f"/v1/invocations/{item.invocation_id}/reconcile", json=resolution(door, item, **change)
    )
    assert response.status_code == 422, response.text
    assert "secret-value" not in response.text
    assert (await door.store.get(item.invocation_id)).revision == item.revision


@pytest.mark.parametrize("terminal", [False, True])
async def test_resolution_preserves_run_history_and_only_eligible_work_can_reattempt(
    door, terminal
):
    runs = InMemoryRunStore(project_store=door.projects)
    execution = RunExecutionService(store=runs, runtime=PythonExecutionRuntime())
    run = await execution.create_run(
        Graph(
            graph_id="graph",
            workspace_id="ws",
            project_id=door.project.project_id,
            name="Recovery",
            nodes=[Node(node_id="node", node_type="agent")],
        ),
        actor_principal_id="operator",
    )
    physical_calls = 0

    async def provider(_provider, _request):
        nonlocal physical_calls
        physical_calls += 1
        if physical_calls == 1:
            raise ConnectionError("lost response")
        return "done"

    async def executor(_work, attempt):
        outcome = await door.effects.invocations.invoke(
            binding=door.binding,
            run_id=run.run_id,
            node_run_id=attempt.node_run_id,
            attempt_id=attempt.attempt_id,
            effect_key="write:1",
            request={},
            resolver=resolver,
            executor=provider,
        )
        return outcome.result

    with pytest.raises(ConnectionError):
        await execution.execute_node(
            run.run_id,
            "node",
            None,
            None,
            executor=executor,
            context_factory=lambda attempt, _base: attempt,
        )
    node = (await runs.list_node_runs(run.run_id))[0]
    assert node.status is RunStatus.WAITING
    if terminal:
        await runs.transition_run(run.run_id, RunStatus.RUNNING)
        await runs.transition_run(run.run_id, RunStatus.FAILED, error="chat turn failed")
    before = await runs.get_run(run.run_id)
    item = (await door.effects.invocations.discover_ambiguous(stale_before=datetime.now(UTC)))[0]
    response = await door.client.post(
        f"/v1/invocations/{item.invocation_id}/reconcile", json=resolution(door, item)
    )
    assert response.status_code == 200
    assert await runs.get_run(run.run_id) == before
    if terminal:
        with pytest.raises(RunIntegrityError, match="terminal"):
            await execution.retry_node(
                node.node_run_id,
                None,
                None,
                executor=executor,
                context_factory=lambda attempt, _base: attempt,
            )
        assert physical_calls == 1
        assert len(await runs.list_attempts(node.node_run_id)) == 1
    else:
        retry = await execution.retry_node(
            node.node_run_id,
            None,
            None,
            executor=executor,
            context_factory=lambda attempt, _base: attempt,
        )
        assert retry.ordinal == 2 and retry.node_run_id == node.node_run_id
        assert (await runs.get_run(run.run_id)).status is RunStatus.COMPLETED
        assert physical_calls == 2


async def test_owner_has_no_implicit_project_permission_and_foreign_rows_are_hidden(door):
    item = await unknown(door)
    own = f"/v1/invocations/{item.invocation_id}"
    missing = await door.client.get("/v1/invocations/missing", params=scope(door))
    foreign = await door.client.get(
        own, params={"workspace_id": "foreign", "project_id": door.project.project_id}
    )
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    await door.projects.set_membership(
        ProjectMembership(
            workspace_id="ws", project_id=door.project.project_id, principal_id="operator"
        )
    )
    assert (await door.client.get(own, params=scope(door))).status_code == 404
    assert (
        await door.client.post(f"{own}/reconcile", json=resolution(door, item))
    ).status_code == 404


async def test_legacy_unscoped_row_cannot_be_claimed_by_http_scope(door):
    legacy = await door.store.create(
        Invocation.model_validate(
            {
                "invocation_id": "legacy",
                "run_id": "legacy-run",
                "node_run_id": "legacy-node",
                "attempt_id": "legacy-attempt",
                "effect_key": "legacy-effect",
                "status": "unknown",
                "binding": {
                    "binding_id": "legacy-binding",
                    "capability": "external_write",
                    "provider_name": "provider",
                    "provider_trust_tier": "trusted",
                },
                "finished_at": datetime.now(UTC),
            }
        )
    )
    listing = await door.client.get(
        "/v1/invocations", params={**scope(door), "stale_before": datetime.now(UTC).isoformat()}
    )
    assert listing.status_code == 200 and listing.json()["items"] == []
    assert (await door.client.get("/v1/invocations/legacy", params=scope(door))).status_code == 404
    response = await door.client.post(
        "/v1/invocations/legacy/reconcile", json=resolution(door, legacy)
    )
    assert response.status_code == 404
    persisted = await door.store.get(legacy.invocation_id)
    assert persisted.workspace_id == persisted.project_id == ""
    assert persisted.reconciliation_history == ()


async def test_body_and_list_bounds_apply_before_evidence_is_processed(door):
    item = await unknown(door)
    url = f"/v1/invocations/{item.invocation_id}/reconcile"
    response = await door.client.post(
        url, content=b" " * 65537, headers={"content-type": "application/json"}
    )
    assert response.status_code == 413

    async def chunks():
        yield b" " * 40000
        yield b" " * 40000

    response = await door.client.post(
        url, content=chunks(), headers={"content-type": "application/json"}
    )
    assert response.status_code == 413
    for extra in ({"limit": 101}, {"after_invocation_id": "without-time"}):
        response = await door.client.get(
            "/v1/invocations",
            params={**scope(door), "stale_before": datetime.now(UTC).isoformat(), **extra},
        )
        assert response.status_code == 422
    assert (await door.store.get(item.invocation_id)).revision == item.revision


@pytest.mark.parametrize("disposition", ["applied", "not_applied"])
@pytest.mark.parametrize("failure", [RuntimeError, ValueError, KeyError])
async def test_http_retry_repairs_partial_settlement_after_inspecting_revision(
    door, monkeypatch, disposition, failure
):
    item = await unknown(door)
    url = f"/v1/invocations/{item.invocation_id}/reconcile"
    body = resolution(door, item, disposition=disposition)
    original_observe = door.effects.quota.observe

    async def unavailable(_invocation):
        raise failure("backend unavailable with secret-value")

    monkeypatch.setattr(door.effects.quota, "observe", unavailable)
    response = await door.client.post(url, json=body)
    assert response.status_code == 503
    assert "secret-value" not in response.text
    assert (await door.effects.quota.balance("requests")).held == 1
    assert (await door.client.post(url, json=body)).status_code == 409
    inspected = await door.client.get(f"/v1/invocations/{item.invocation_id}", params=scope(door))
    assert inspected.status_code == 200
    body["expected_revision"] = inspected.json()["revision"]
    monkeypatch.setattr(door.effects.quota, "observe", original_observe)
    response = await door.client.post(url, json=body)
    assert response.status_code == 200
    assert response.json()["revision"] == inspected.json()["revision"]
    assert len(response.json()["reconciliation_history"]) == 1
    balance = await door.effects.quota.balance("requests")
    assert balance.held == 0
    assert balance.spent == (1 if disposition == "applied" else 0)


async def test_operator_cas_race_does_not_report_its_rejected_evidence_as_accepted(
    door, monkeypatch
):
    from maistro.capabilities.invocation import ReconciliationDisposition

    item = await unknown(door)
    original_save = door.store.save
    competitor = new_effect_context(
        invocation_store=door.store, quota=door.effects.quota, policy_evaluator=binding_scope_policy
    )
    raced = False

    async def racing_save(candidate):
        nonlocal raced
        if not raced:
            raced = True
            await competitor.invocations.reconcile(
                item.invocation_id,
                disposition=ReconciliationDisposition.INDETERMINATE,
                source="operator",
                actor="other-operator",
                reason="new lookup still unknown",
                evidence=None,
                workspace_id="ws",
                project_id=door.project.project_id,
            )
        return await original_save(candidate)

    monkeypatch.setattr(door.store, "save", racing_save)
    response = await door.client.post(
        f"/v1/invocations/{item.invocation_id}/reconcile", json=resolution(door, item)
    )
    assert response.status_code == 409
    persisted = await door.store.get(item.invocation_id)
    assert persisted.status is InvocationStatus.UNKNOWN
    assert [record.actor for record in persisted.reconciliation_history] == ["other-operator"]
    assert (await door.effects.quota.balance("requests")).held == 1


async def test_missing_project_and_unrelated_permission_do_not_gain_authority(door):
    response = await door.client.get(
        "/v1/invocations",
        params={
            "workspace_id": "ws",
            "project_id": "missing-project",
            "stale_before": datetime.now(UTC).isoformat(),
        },
    )
    assert response.status_code == 404
    with pytest.raises(ValueError, match="unknown Invocation permission"):
        await door.service.authorize(
            principal_id="operator",
            workspace_id="ws",
            project_id=door.project.project_id,
            permission="config.write",
        )


async def test_unreadable_persisted_scope_does_not_disclose_record(door):
    import json

    item = await unknown(door)
    payload = item.model_dump(mode="json")
    payload["binding"]["workspace_id"] = "foreign-workspace"
    await door.store._conn.execute(
        "UPDATE capability_invocations SET payload_json = ? WHERE invocation_id = ?",
        (json.dumps(payload), item.invocation_id),
    )
    await door.store._conn.commit()
    response = await door.client.get(f"/v1/invocations/{item.invocation_id}", params=scope(door))
    missing = await door.client.get("/v1/invocations/missing", params=scope(door))
    assert response.status_code == missing.status_code == 404
    assert response.json() == missing.json()


async def test_product_dependency_uses_canonical_container_and_missing_authority_is_unavailable(
    door, monkeypatch
):
    from services import dag_agents

    item = await unknown(door)
    door.app.dependency_overrides.clear()
    monkeypatch.setattr(
        dag_agents,
        "_container",
        lambda: SimpleNamespace(
            capability_effects=door.effects,
            workspace_store=door.workspaces,
            project_scope_store=door.projects,
        ),
    )
    response = await door.client.get(f"/v1/invocations/{item.invocation_id}", params=scope(door))
    assert response.status_code == 200
    assert response.json()["invocation_id"] == item.invocation_id
    monkeypatch.setattr(dag_agents, "_container", lambda: None)
    response = await door.client.get(f"/v1/invocations/{item.invocation_id}", params=scope(door))
    assert response.status_code == 503


async def test_reconciled_not_applied_still_requires_ordinary_policy_authority(door):
    from maistro.capabilities.governed_invocation import InvocationDenied
    from maistro.policy.types import Decision, PolicyVerdict

    item = await unknown(door)
    response = await door.client.post(
        f"/v1/invocations/{item.invocation_id}/reconcile", json=resolution(door, item)
    )
    assert response.status_code == 200

    async def deny(_binding, _request, _context):
        return PolicyVerdict(Decision.DENY, reason="permission revoked")

    guarded = door.effects.with_policy_evaluator(deny)
    with pytest.raises(InvocationDenied, match="revoked"):
        await guarded.invocations.invoke(
            binding=door.binding,
            run_id=item.run_id,
            node_run_id=item.node_run_id,
            attempt_id="attempt-next",
            effect_key=item.effect_key,
            request={},
            resolver=resolver,
            executor=lambda *_: pytest.fail("denied provider dispatch"),
        )
    assert (await door.effects.quota.balance("requests")).held == 0


async def test_global_admin_keeps_existing_policy_but_requires_project_authority(door):
    item = await unknown(door)
    headers = {"authorization": "admin"}
    response = await door.client.get(
        f"/v1/invocations/{item.invocation_id}", params=scope(door), headers=headers
    )
    assert response.status_code == 200
    await door.projects.set_membership(
        ProjectMembership(
            workspace_id="ws", project_id=door.project.project_id, principal_id="operator"
        )
    )
    assert (
        await door.client.get(
            f"/v1/invocations/{item.invocation_id}", params=scope(door), headers=headers
        )
    ).status_code == 404
    assert (
        await door.client.post(
            f"/v1/invocations/{item.invocation_id}/reconcile",
            json=resolution(door, item),
            headers=headers,
        )
    ).status_code == 404
    assert (await door.store.get(item.invocation_id)).reconciliation_history == ()


async def test_scoped_discovery_returns_cursor_without_global_scan(door, monkeypatch):
    item = await unknown(door)
    await door.store.create(
        item.model_copy(
            update={
                "invocation_id": "second",
                "run_id": "second-run",
                "created_at": item.created_at + timedelta(seconds=1),
            }
        )
    )

    async def forbidden_global(**_kwargs):
        pytest.fail("HTTP discovery must use a scoped database page")

    monkeypatch.setattr(door.store, "list_ambiguous", forbidden_global)
    params = {**scope(door), "stale_before": datetime.now(UTC).isoformat(), "limit": 1}
    first = await door.client.get("/v1/invocations", params=params)
    assert first.status_code == 200
    assert [record["invocation_id"] for record in first.json()["items"]] == [item.invocation_id]
    second = await door.client.get(
        "/v1/invocations", params={**params, **first.json()["next_cursor"]}
    )
    assert second.status_code == 200
    assert [record["invocation_id"] for record in second.json()["items"]] == ["second"]
    assert second.json()["next_cursor"] is None


@pytest.mark.parametrize("field", ["evidence", "result"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
async def test_nonfinite_evidence_is_not_lossily_persisted(door, field, value):
    import json

    item = await unknown(door)
    body = resolution(door, item, disposition="applied", **{field: {"measurement": value}})
    response = await door.client.post(
        f"/v1/invocations/{item.invocation_id}/reconcile",
        content=json.dumps(body),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422
    assert (await door.store.get(item.invocation_id)).revision == item.revision
    assert (await door.effects.quota.balance("requests")).held == 1


@pytest.mark.parametrize(
    "usage",
    [
        {"input_units": 2**63},
        {"input_units": 2**62, "output_units": 2**62},
        {"cost_cents": 1e308},
    ],
)
async def test_unrepresentable_usage_refuses_before_operator_settlement(door, usage):
    item = await unknown(door)
    response = await door.client.post(
        f"/v1/invocations/{item.invocation_id}/reconcile",
        json=resolution(door, item, disposition="applied", usage=usage),
    )
    assert response.status_code == 422
    assert await door.store.get(item.invocation_id) == item
    assert (await door.effects.quota.balance("requests")).held == 1


async def test_historical_usage_is_visible_but_requires_valid_acceptance_evidence(door):
    from maistro.capabilities.invocation import InvocationUsage

    item = await unknown(door)
    item = await door.store.save(
        item.model_copy(update={"usage": InvocationUsage(input_units=2**63)})
    )
    detail = await door.client.get(f"/v1/invocations/{item.invocation_id}", params=scope(door))
    assert detail.status_code == 200 and detail.json()["usage"]["input_units"] == 2**63
    response = await door.client.post(
        f"/v1/invocations/{item.invocation_id}/reconcile",
        json=resolution(door, item, disposition="applied"),
    )
    assert response.status_code == 422
    assert await door.store.get(item.invocation_id) == item
    response = await door.client.post(
        f"/v1/invocations/{item.invocation_id}/reconcile",
        json=resolution(door, item, disposition="applied", usage={"input_units": 2}),
    )
    assert response.status_code == 200
    assert response.json()["usage"]["input_units"] == 2


@pytest.fixture
async def production_client(door, monkeypatch):
    from main import app

    monkeypatch.setitem(
        app.dependency_overrides, invocations.operator_service, lambda: door.service
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"authorization": "operator"},
    ) as client:
        yield client


@pytest.mark.parametrize("chunked", [False, True])
async def test_production_ingress_bounds_before_version_json_parser(
    door, production_client, monkeypatch, chunked
):
    import json

    from maistro import api_versioning

    parsed = []
    original = api_versioning._selector_from_body

    def spy(body):
        parsed.append(len(body))
        return original(body)

    monkeypatch.setattr(api_versioning, "_selector_from_body", spy)
    item = await unknown(door)
    raw = json.dumps(resolution(door, item, evidence={"blob": "x" * 70000})).encode()

    async def pieces():
        yield raw[:40000]
        yield raw[40000:]

    response = await production_client.post(
        f"/v1/invocations/{item.invocation_id}/reconcile",
        content=pieces() if chunked else raw,
        headers={"content-type": "application/json", "accept": "application/vnd.maistro.v1+json"},
    )
    assert response.status_code == 413
    assert parsed == []
    assert (await door.store.get(item.invocation_id)).revision == item.revision


@pytest.mark.parametrize("selector", ["body", "query", "accept"])
async def test_production_negotiation_errors_never_reflect_selectors(
    door, production_client, selector
):
    item = await unknown(door)
    body, params, headers = resolution(door, item), {}, {}
    if selector == "body":
        body["api_version"] = {"api_key": "version-secret-value"}
    elif selector == "query":
        params["api_version"] = "version-secret-value"
    else:
        headers["accept"] = "application/vnd.maistro.vversion-secret-value"
    response = await production_client.post(
        f"/v1/invocations/{item.invocation_id}/reconcile", json=body, params=params, headers=headers
    )
    assert response.status_code == (406 if selector == "accept" else 400)
    assert "version-secret-value" not in response.text
    assert int(response.headers["content-length"]) == len(response.content)
    assert (await door.store.get(item.invocation_id)).revision == item.revision


@pytest.mark.parametrize("selector", ["body", "query", "accept"])
async def test_production_negotiation_forms_keep_the_same_authorized_operation(
    door, production_client, selector
):
    item = await unknown(door)
    body, params, headers = resolution(door, item), {}, {}
    if selector == "body":
        body["api_version"] = 1
    elif selector == "query":
        params["api_version"] = "1"
    else:
        headers["accept"] = "application/vnd.maistro.v1+json"
    response = await production_client.post(
        f"/v1/invocations/{item.invocation_id}/reconcile", json=body, params=params, headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.headers["maistro-api-version"] == "1"
    assert response.json()["status"] == "failed"
    assert "api_version" not in response.json()["reconciliation_history"][0]
