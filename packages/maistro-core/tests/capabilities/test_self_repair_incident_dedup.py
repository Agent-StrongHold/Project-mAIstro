"""Restart/replica coordination for durable self-repair approval waits (#2405).

The 2026-11-22 audits under #2405 proved two source-level defects:

1. **Restart duplicates approval Runs.** The effect key used ``id(proposal)``
   (process-local allocation identity), the provider held pending waits in an
   in-memory dict, and admission called ``create_run`` unconditionally — so a
   restart or a second replica observing the same unresolved incident admitted
   a second PAUSED Run for it.
2. **An approved Run was never resumed.** Nothing owned the ``self_repair``
   admission source, the node kind was not reconstructible from durable facts,
   and an answered Run stayed queued forever.

These tests pin the convergence contract: same incident → one canonical Run,
one DurableApproval, one physical effect; terminal settlement → the next
episode admits; reconstruction failure fails closed.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from maistro.capabilities.approval_store import InMemoryApprovalStore
from maistro.capabilities.binding import Binding
from maistro.capabilities.durable_hitl_approval import (
    SELF_REPAIR_APPROVAL_NODE_ID,
    admit_self_repair_approval,
)
from maistro.capabilities.effect_context import new_effect_context
from maistro.capabilities.providers.host_health import HostHealthAction
from maistro.capabilities.providers.self_repair import RuleBasedRepair
from maistro.capabilities.self_repair_incident import (
    INCIDENT_RESOURCE_KEY,
    SELF_REPAIR_ADMISSION_SOURCE,
    chain_incident_claim,
    incident_claim,
    is_incident_claim,
    stable_effect_key,
)
from maistro.capabilities.slots.infra import ActionResult, InfraAction
from maistro.capabilities.slots.self_repair import RepairDecision, RepairProposal
from maistro.graph.durable_runs import (
    CanonicalDurableRunStore,
    HitlAuthorization,
    InMemoryDurableRunStore,
    InMemoryGraphContinuationStore,
    RunStatus,
)
from maistro.graph.durable_runs.fair_scan import ScanPage
from maistro.graph.nodes import NodeCompositionError, compose_node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore
from maistro.runs.model import TERMINAL_RUN_STATUSES
from maistro.runs.sources import SCHEDULE_FIRE_ID_KEY, SCHEDULE_ID_KEY
from maistro.runs.store import RunIntegrityError
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID
from maistro.workspaces import InMemoryWorkspaceStore


class _FakeHttp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def get_json(self, path: str) -> dict[str, Any]:
        return {}

    async def post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((path, body))
        return {"status": "ok", "detail": "restarted"}


class _Registry:
    """Minimal capability-slot registry stand-in for authority composition."""

    def __init__(self, provider: Any) -> None:
        self._provider = provider

    async def resolve(self, slot: str) -> Any:
        if slot != "infra_action":
            return None
        return self._provider


def _binding() -> Binding:
    return Binding(
        binding_id="builtin:self-repair:infra-action",
        workspace_id="default",
        project_id="default",
        node_id="self-repair",
        capability="infra_action",
    )


def _action(http: _FakeHttp) -> HostHealthAction:
    return HostHealthAction(http, autonomy="approve_all")


async def _resolve_provider(_candidate: Binding) -> InfraAction:
    return _provider_ref[0]


_provider_ref: list[InfraAction] = []


async def _admit(
    *,
    store: InMemoryDurableRunStore,
    run_store: InMemoryRunStore | None = None,
    approvals: InMemoryApprovalStore | None = None,
    http: _FakeHttp | None = None,
    resource: str = "docker:litellm",
    params: dict[str, Any] | None = None,
    effect_key: str | None = None,
    workspace_id: str = "ws-2405",
    project_id: str = "project-2405",
):
    http = http or _FakeHttp()
    provider = _action(http)
    _provider_ref.clear()
    _provider_ref.append(provider)
    effects = new_effect_context(approval_store=approvals or InMemoryApprovalStore())
    await effects.bindings.put(_binding())
    return await admit_self_repair_approval(
        store=store,
        effect_context=effects,
        binding=_binding(),
        workspace_id=workspace_id,
        project_id=project_id,
        action="restart_container",
        params=params or {"name": "litellm"},
        effect_key=effect_key
        or stable_effect_key(resource, "restart_container", params or {"name": "litellm"}),
        resolve_provider=_resolve_provider,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        run_store=run_store,
        resource=resource,
    )


async def _run_store() -> tuple[CanonicalDurableRunStore, InMemoryRunStore, str]:
    """The production durable-store shape: canonical spine + continuation wrapper.

    Hive wires ``graph_run_store`` as ``CanonicalDurableRunStore`` over the
    RunStore and the continuation store, so a HITL answer mirrors to both
    stores; these tests exercise the same composition.
    """
    projects = InMemoryProjectScopeStore()
    workspaces = InMemoryWorkspaceStore(project_store=projects)
    projects.bind_workspace_store(workspaces)
    run_store = InMemoryRunStore(project_store=projects, workspace_store=workspaces)
    workspace = await workspaces.create(
        creator_user_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID, name="WS-2405"
    )
    root = await projects.root_for_workspace(workspace.workspace_id)
    durable = CanonicalDurableRunStore(run_store, InMemoryGraphContinuationStore())
    return durable, run_store, workspace.workspace_id, root.project_id


def _pause_request_id(record: Any) -> str:
    from maistro.graph.execution_state import thaw_json_value

    metadata = thaw_json_value(record.graph_state.metadata)
    pause = metadata.get("pause") if isinstance(metadata, dict) else None
    if not isinstance(pause, dict):
        return ""
    pause_body = pause.get("metadata") if isinstance(pause.get("metadata"), dict) else {}
    return str((pause_body or {}).get("approval_request_id") or "")


# --- stable identity -------------------------------------------------------


def test_effect_key_is_stable_and_process_independent() -> None:
    """Same incident, two 'processes': identical key; no object-id ingredient."""
    a = stable_effect_key("docker:litellm", "restart_container", {"name": "litellm"})
    b = stable_effect_key("docker:litellm", "restart_container", {"name": "litellm"})
    assert a == b
    assert a.startswith("self_repair:docker:litellm:restart_container:")
    assert str(id(a)) not in a
    different_params = stable_effect_key("docker:litellm", "restart_container", {"name": "other"})
    different_action = stable_effect_key("docker:litellm", "docker_logs", {"name": "litellm"})
    different_resource = stable_effect_key("docker:api", "restart_container", {"name": "litellm"})
    assert len({a, different_params, different_action, different_resource}) == 4


async def test_rule_based_repair_admits_stable_effect_key() -> None:
    """Two fresh provider instances derive the same key for the same incident."""
    keys: list[str] = []

    async def admit(proposal: RepairProposal, effect_key: str) -> str:
        keys.append(effect_key)
        return f"run-{len(keys)}"

    monitor_proposal = RepairProposal(
        resource="docker:litellm",
        symptom="container unhealthy",
        action="restart_container",
        params={"name": "litellm"},
    )
    for _ in range(2):
        repair = RuleBasedRepair(
            infra_monitor=None,
            effect_invoker=None,
            approval_admittor=admit,
            autonomy="approve_all",
        )
        await repair._admit_approval(monitor_proposal)
    assert keys[0] == keys[1]


def test_incident_claim_uses_scoped_namespace_and_manual_token() -> None:
    claim = incident_claim(
        workspace_id="ws",
        project_id="proj",
        resource="docker:litellm",
        action="restart_container",
        params={"name": "litellm"},
    )
    assert claim[SCHEDULE_ID_KEY].startswith("self-repair-approval:ws:proj:docker:litellm")
    # The store claims fire tokens as `manual:<token>`, disjoint from cron instants.
    assert claim[SCHEDULE_FIRE_ID_KEY]
    assert is_incident_claim(claim)
    assert not is_incident_claim({"schedule_id": "some-real-schedule"})
    assert claim[INCIDENT_RESOURCE_KEY] == "docker:litellm"


def test_chained_claim_is_deterministic_from_durable_facts() -> None:
    claim = incident_claim(
        workspace_id="ws",
        project_id="proj",
        resource="r",
        action="a",
        params={},
    )
    chained_a = chain_incident_claim(claim, "run-1")
    chained_b = chain_incident_claim(claim, "run-1")
    assert chained_a == chained_b
    assert chained_a[SCHEDULE_FIRE_ID_KEY] != claim[SCHEDULE_FIRE_ID_KEY]
    with pytest.raises(ValueError):
        chain_incident_claim(claim, "")


# --- one incident, one Run ---------------------------------------------------


async def test_concurrent_admission_of_same_incident_converges_on_one_run() -> None:
    """Two admissions racing the same incident: one Run, one approval, zero effects."""
    durable, run_store, workspace_id, project_id = await _run_store()
    approvals = InMemoryApprovalStore()
    http = _FakeHttp()

    record_a, record_b = await asyncio.gather(
        _admit(
            store=durable,
            run_store=run_store,
            approvals=approvals,
            http=http,
            project_id=project_id,
            workspace_id=workspace_id,
        ),
        _admit(
            store=durable,
            run_store=run_store,
            approvals=approvals,
            http=http,
            project_id=project_id,
            workspace_id=workspace_id,
        ),
    )
    assert record_a.run.run_id == record_b.run.run_id
    final = await durable.get(record_a.run.run_id)
    assert final is not None
    assert final.run.status is RunStatus.PAUSED
    canonical = await run_store.get_run(record_a.run.run_id)
    assert canonical is not None
    assert is_incident_claim(canonical.provenance)
    assert http.calls == []
    scoped = [
        approval for approval in approvals._items.values() if approval.run_id == record_a.run.run_id
    ]
    assert len(scoped) == 1


async def test_restart_admission_reuses_parked_wait_without_second_run() -> None:
    """A restart (fresh everything) observing the same incident reconciles, not duplicates."""
    durable, run_store, workspace_id, project_id = await _run_store()
    approvals = InMemoryApprovalStore()
    http = _FakeHttp()

    first = await _admit(
        store=durable,
        run_store=run_store,
        approvals=approvals,
        http=http,
        project_id=project_id,
        workspace_id=workspace_id,
    )
    before = len(await run_store.list_by_status(RunStatus.QUEUED, limit=100))

    second = await _admit(
        store=durable,
        run_store=run_store,
        approvals=approvals,
        http=http,
        project_id=project_id,
        workspace_id=workspace_id,
    )
    assert second.run.run_id == first.run.run_id
    after = len(await run_store.list_by_status(RunStatus.QUEUED, limit=100))
    assert after == before
    scoped = [
        approval for approval in approvals._items.values() if approval.run_id == first.run.run_id
    ]
    assert len(scoped) == 1
    assert http.calls == []


async def test_crash_window_reenters_the_claimed_run() -> None:
    """Killed between create_run and the durable checkpoint: same Run re-parks."""
    from maistro.capabilities.durable_hitl_approval import _approval_graph
    from maistro.graph.durable_runs import durable_graph_launch_provenance
    from maistro.graph.nodes.infra_approval_action import binding_reference_of

    durable, run_store, workspace_id, project_id = await _run_store()
    approvals = InMemoryApprovalStore()
    http = _FakeHttp()

    resource = "docker:litellm"
    params = {"name": "litellm"}
    effect_key = stable_effect_key(resource, "restart_container", params)
    claim = incident_claim(
        workspace_id=workspace_id,
        project_id=project_id,
        resource=resource,
        action="restart_container",
        params=params,
    )
    synthetic = Binding(
        binding_id="builtin:self-repair:infra-action",
        workspace_id="default",
        project_id="default",
        node_id="self-repair",
        capability="infra_action",
    )
    crash_graph = _approval_graph(
        workspace_id=workspace_id,
        project_id=project_id,
        action="restart_container",
        params=params,
        effect_key=effect_key,
        binding=synthetic,
    )
    inputs = {
        "action": "restart_container",
        "params": params,
        "effect_key": effect_key,
        "binding_reference": binding_reference_of(synthetic),
    }
    await run_store.create_run(
        crash_graph,
        initial_status=RunStatus.QUEUED,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        provenance={
            "admission_source": SELF_REPAIR_ADMISSION_SOURCE,
            "executor": "durable_graph",
            "effect_key": effect_key,
            "action": "restart_container",
            INCIDENT_RESOURCE_KEY: resource,
            **durable_graph_launch_provenance(inputs=inputs),
            **claim,
        },
    )
    # The durable continuation never got written: admission must re-enter the
    # SAME Run, not mint a second one.
    record = await _admit(
        store=durable,
        run_store=run_store,
        approvals=approvals,
        http=http,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    runs = await run_store.list_by_status(RunStatus.QUEUED, limit=100)
    # The re-entry consumed the claim: the SAME Run re-parked (the re-entry
    # moved it past QUEUED), and no second Run was minted for the incident.
    assert len(runs) == 0
    reentered = await run_store.get_run(record.run.run_id)
    assert reentered is not None
    assert record.run.status is RunStatus.PAUSED
    assert http.calls == []


async def test_mismatched_effect_on_live_claim_refuses_closed() -> None:
    """A claim held for a different effect is an integrity failure, not an alias."""
    from maistro.graph.definitions import Graph, Node
    from maistro.graph.durable_runs import durable_graph_launch_provenance

    durable, run_store, workspace_id, project_id = await _run_store()
    approvals = InMemoryApprovalStore()
    http = _FakeHttp()

    resource = "docker:litellm"
    params = {"name": "litellm"}
    claim = incident_claim(
        workspace_id=workspace_id,
        project_id=project_id,
        resource=resource,
        action="restart_container",
        params=params,
    )
    foreign_graph = Graph(
        graph_id="self-repair-approval:foreign",
        workspace_id=workspace_id,
        project_id=project_id,
        name="foreign claim holder",
        nodes=[
            Node(
                node_id=SELF_REPAIR_APPROVAL_NODE_ID,
                node_type="infra.approval_gated_action",
                inputs={"action": "restart_container", "params": params, "effect_key": "other-key"},
                parameters={},
                metadata={},
            )
        ],
        edges=[],
        metadata={"entry_node": SELF_REPAIR_APPROVAL_NODE_ID},
    )
    await run_store.create_run(
        foreign_graph,
        initial_status=RunStatus.QUEUED,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        provenance={
            "admission_source": SELF_REPAIR_ADMISSION_SOURCE,
            "effect_key": "other-key",
            **durable_graph_launch_provenance(inputs={}),
            **claim,
        },
    )
    with pytest.raises(RunIntegrityError, match="different effect"):
        await _admit(
            store=durable,
            run_store=run_store,
            approvals=approvals,
            http=http,
            project_id=project_id,
            workspace_id=workspace_id,
        )


async def test_distinct_incidents_do_not_alias() -> None:
    durable, run_store, workspace_id, project_id = await _run_store()
    approvals = InMemoryApprovalStore()

    litellm = await _admit(
        store=durable,
        project_id=project_id,
        workspace_id=workspace_id,
        run_store=run_store,
        approvals=approvals,
        resource="docker:litellm",
    )
    api = await _admit(
        store=durable,
        run_store=run_store,
        approvals=approvals,
        workspace_id=workspace_id,
        project_id=project_id,
        resource="docker:api",
        params={"name": "api"},
    )
    assert litellm.run.run_id != api.run.run_id


async def test_terminal_settlement_chains_a_new_episode() -> None:
    """A settled incident's claim is superseded; the next episode admits fresh."""
    durable, run_store, workspace_id, project_id = await _run_store()
    approvals = InMemoryApprovalStore()
    http = _FakeHttp()

    first = await _admit(
        store=durable,
        run_store=run_store,
        approvals=approvals,
        http=http,
        workspace_id=workspace_id,
        project_id=project_id,
    )

    async def allow_all(_principal: str, _workspace: str) -> bool:
        return True

    settled = await durable.cancel_hitl(
        first.run.run_id,
        SELF_REPAIR_APPROVAL_NODE_ID,
        authorization=HitlAuthorization(
            effective_principal="human-2405",
            workspace_ids=frozenset({workspace_id}),
            membership_check=allow_all,
        ),
        workspace_id=workspace_id,
    )
    assert settled.run.status in TERMINAL_RUN_STATUSES

    second = await _admit(
        store=durable,
        run_store=run_store,
        approvals=approvals,
        http=http,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    assert second.run.run_id != first.run.run_id
    assert second.run.status is RunStatus.PAUSED
    second_canonical = await run_store.get_run(second.run.run_id)
    assert second_canonical is not None
    first_claim = incident_claim(
        workspace_id=workspace_id,
        project_id=project_id,
        resource="docker:litellm",
        action="restart_container",
        params={"name": "litellm"},
    )
    chained = chain_incident_claim(first_claim, first.run.run_id)
    assert second_canonical.provenance.get(SCHEDULE_FIRE_ID_KEY) == chained[SCHEDULE_FIRE_ID_KEY]
    assert http.calls == []


# --- hydration: restart / replica reconcile ----------------------------------


class _DegradedMonitor:
    name = "m"
    slot = "infra_monitor"
    trust_tier = "t0"

    def requires(self) -> tuple[str, ...]:
        return ()

    async def healthcheck(self):  # type: ignore[no-untyped-def]
        from maistro.capabilities.types import ProviderHealth

        return ProviderHealth(healthy=True)

    async def snapshot(self):  # type: ignore[no-untyped-def]
        from maistro.capabilities.slots.infra import InfraHealth, ResourceHealth

        return InfraHealth(
            ts="t",
            resources={
                "docker": ResourceHealth(
                    "unhealthy",
                    {"containers": [{"name": "litellm", "state": "unhealthy"}]},
                )
            },
        )


async def test_replica_hydration_blocks_duplicate_admission() -> None:
    """A fresh provider (restart/replica) reconciles the parked wait: no second Run."""
    durable, run_store, workspace_id, project_id = await _run_store()
    approvals = InMemoryApprovalStore()
    http = _FakeHttp()

    record = await _admit(
        store=durable,
        run_store=run_store,
        approvals=approvals,
        http=http,
        project_id=project_id,
        workspace_id=workspace_id,
    )
    resource = record.run.provenance[INCIDENT_RESOURCE_KEY]

    async def load_pending() -> dict[str, str]:
        # The shipped loader's shape: durable truth, not process-local state.
        return {resource: record.run.run_id}

    replica_admits: list[str] = []

    async def must_not_admit(proposal: RepairProposal, effect_key: str) -> str:
        replica_admits.append(effect_key)
        return "run-should-not-exist"

    async def must_not_invoke(*_args: Any, **_kwargs: Any) -> ActionResult:
        raise AssertionError("in-flight incident must not be re-dispatched")

    replica = RuleBasedRepair(
        infra_monitor=_DegradedMonitor(),
        effect_invoker=must_not_invoke,
        approval_admittor=must_not_admit,
        approval_run_status=None,
        pending_approvals_loader=load_pending,
        autonomy="approve_all",
    )
    cycle = await replica.run_once()
    (result,) = cycle.results
    assert result.decision is RepairDecision.SUPPRESSED
    assert replica_admits == []
    assert replica.governor_state()["docker:litellm"]["in_flight"] is True
    assert replica._pending_approval_runs["docker:litellm"] == record.run.run_id


async def test_replica_without_hydration_claim_still_converges() -> None:
    """Even without hydration, the canonical claim refuses the duplicate Run."""
    durable, run_store, workspace_id, project_id = await _run_store()
    approvals = InMemoryApprovalStore()
    http = _FakeHttp()

    record = await _admit(
        store=durable,
        run_store=run_store,
        approvals=approvals,
        http=http,
        project_id=project_id,
        workspace_id=workspace_id,
    )

    # A second replica whose provider has no loader still derives the same
    # effect key and hits the same claim through its admittor.
    second = await _admit(
        store=durable,
        run_store=run_store,
        approvals=approvals,
        http=http,
        project_id=project_id,
        workspace_id=workspace_id,
    )
    assert second.run.run_id == record.run.run_id


async def test_hydration_failure_fails_the_cycle_closed() -> None:
    """Loader outage: no admission, no auto-run — never admit on blindness."""

    async def broken_loader() -> dict[str, str]:
        raise RuntimeError("durable store unavailable")

    async def must_not_invoke(*_args: Any, **_kwargs: Any) -> ActionResult:
        raise AssertionError("cycle must be refused when hydration fails")

    async def must_not_admit(*_args: Any, **_kwargs: Any) -> str:
        raise AssertionError("cycle must be refused when hydration fails")

    repair = RuleBasedRepair(
        infra_monitor=_DegradedMonitor(),
        effect_invoker=must_not_invoke,
        approval_admittor=must_not_admit,
        pending_approvals_loader=broken_loader,
        autonomy="approve_all",
    )
    cycle = await repair.run_once()
    assert cycle.results == []
    assert cycle.ts == ""


# --- reconstructible resume --------------------------------------------------


async def test_registered_kind_resumes_answered_run_through_recovery() -> None:
    """Answer → recovery resume dispatches exactly one approved effect."""
    from maistro.graph.durable_runs import resume_durable_graph

    durable, run_store, workspace_id, project_id = await _run_store()
    approvals = InMemoryApprovalStore()
    http = _FakeHttp()

    record = await _admit(
        store=durable,
        run_store=run_store,
        approvals=approvals,
        http=http,
        project_id=project_id,
        workspace_id=workspace_id,
    )
    request_id = _pause_request_id(record)
    assert request_id

    async def allow_all(_principal: str, _workspace_id: str) -> bool:
        return True

    await approvals.resolve(request_id, approved=True, actor="human-2405")
    await durable.submit_hitl_answer(
        record.run.run_id,
        SELF_REPAIR_APPROVAL_NODE_ID,
        {"approved": True},
        authorization=HitlAuthorization(
            effective_principal="human-2405",
            workspace_ids=frozenset({workspace_id}),
            membership_check=allow_all,
        ),
        workspace_id=workspace_id,
    )
    answered = await durable.get(record.run.run_id)
    assert answered is not None
    assert answered.run.status is RunStatus.QUEUED

    # Missing authorities fail composition closed (nothing is constructed).
    with pytest.raises(NodeCompositionError):
        compose_node(
            "infra.approval_gated_action",
            {"effect_context": None, "capability_registry": None},
        )

    # Compose from authorities: the node must rebuild collaborators from the
    # durable Binding reference persisted with the Run, not from closures.
    provider = _action(http)
    effects = new_effect_context(approval_store=approvals)
    await effects.bindings.put(_binding())
    composed = compose_node(
        "infra.approval_gated_action",
        {"effect_context": effects, "capability_registry": _Registry(provider)},
    )

    def recovery_resolver(_node_id: str, _graph: Any) -> Any:
        return composed

    result = await resume_durable_graph(
        record.run.run_id,
        store=durable,
        node_resolver=recovery_resolver,
        run_store=run_store,
    )
    assert result.run.status is RunStatus.COMPLETED
    assert len(http.calls) == 1

    # A second recovery tick (at-least-once delivery) must not re-dispatch:
    # the Run is terminal, so re-entry either refuses or lands unchanged.
    try:
        again = await resume_durable_graph(
            record.run.run_id,
            store=durable,
            node_resolver=recovery_resolver,
            run_store=run_store,
        )
    except (ValueError, KeyError):
        again = None
    assert again is None or again.run.status is RunStatus.COMPLETED
    assert len(http.calls) == 1


async def test_resume_refuses_revoked_binding() -> None:
    """A revoked durable Binding fails the resume closed: no physical dispatch."""
    from maistro.capabilities.binding_store import InMemoryBindingStore
    from maistro.graph.durable_runs import resume_durable_graph

    durable, run_store, workspace_id, project_id = await _run_store()
    approvals = InMemoryApprovalStore()
    http = _FakeHttp()

    effects = new_effect_context(approval_store=approvals)
    await effects.bindings.put(_binding())
    provider = _action(http)
    _provider_ref.clear()
    _provider_ref.append(provider)
    record = await admit_self_repair_approval(
        store=durable,
        effect_context=effects,
        binding=_binding(),
        workspace_id=workspace_id,
        project_id=project_id,
        action="restart_container",
        params={"name": "litellm"},
        effect_key=stable_effect_key("docker:litellm", "restart_container", {"name": "litellm"}),
        resolve_provider=_resolve_provider,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        run_store=run_store,
        resource="docker:litellm",
    )
    request_id = _pause_request_id(record)

    async def allow_all(_principal: str, _workspace_id: str) -> bool:
        return True

    await approvals.resolve(request_id, approved=True, actor="human-2405")
    await durable.submit_hitl_answer(
        record.run.run_id,
        SELF_REPAIR_APPROVAL_NODE_ID,
        {"approved": True},
        authorization=HitlAuthorization(
            effective_principal="human-2405",
            workspace_ids=frozenset({workspace_id}),
            membership_check=allow_all,
        ),
        workspace_id=workspace_id,
    )

    # Revoke the Binding, then rebuild a fresh effect context (restart shape):
    # the durable reference resolves against a store where the binding is gone.
    fresh = new_effect_context(
        approval_store=approvals,
        binding_store=InMemoryBindingStore(),
    )
    composed = compose_node(
        "infra.approval_gated_action",
        {"effect_context": fresh, "capability_registry": _Registry(provider)},
    )

    def recovery_resolver(_node_id: str, _graph: Any) -> Any:
        return composed

    result = await resume_durable_graph(
        record.run.run_id,
        store=durable,
        node_resolver=recovery_resolver,
        run_store=run_store,
    )
    assert result.run.status is RunStatus.FAILED
    assert http.calls == []


async def test_hitl_paused_scan_pages_for_hydration() -> None:
    """The hydration scan shape: PAUSED self-repair waits are page-visible."""
    durable, run_store, workspace_id, project_id = await _run_store()
    approvals = InMemoryApprovalStore()

    record = await _admit(
        store=durable,
        run_store=run_store,
        approvals=approvals,
        project_id=project_id,
        workspace_id=workspace_id,
    )
    page: ScanPage[Any, Any] = await durable.list_hitl_paused(limit=100)
    assert any(item.run_id == record.run.run_id for item in page.items)
    graph = record.run.graph.materialize()
    assert graph.metadata.get("admission_source") == SELF_REPAIR_ADMISSION_SOURCE


def test_terminal_statuses_cover_settlement_paths() -> None:
    assert {"completed", "failed", "cancelled", "timed_out"} <= {
        status.value for status in TERMINAL_RUN_STATUSES
    }
