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
    chained_episode_token,
    episode_effect_key,
    incident_claim,
    incident_episode_token,
    incident_run_effect_key,
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

    for _ in range(2):
        # A distinct proposal object per "process": equal durable facts, fresh
        # allocation. ``id(proposal)`` differs across the two objects, so only
        # the stable digest keeps both admissions on one incident. This is the
        # #2405 mutation oracle for restoring ``id(proposal)`` — sharing one
        # proposal object made the two identities coincide and the old key
        # derivation passed for the wrong reason.
        proposal = RepairProposal(
            resource="docker:litellm",
            symptom="container unhealthy",
            action="restart_container",
            params={"name": "litellm"},
        )
        repair = RuleBasedRepair(
            infra_monitor=None,
            effect_invoker=None,
            approval_admittor=admit,
            autonomy="approve_all",
        )
        await repair._admit_approval(proposal)
    assert len(keys) == 2
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


def test_episode_effect_key_is_stable_for_episode_zero_and_moves_after() -> None:
    """The key rides the generation: episode 0 keeps the caller's key;
    a chained token derives a different, still-deterministic key."""
    base = stable_effect_key("docker:litellm", "restart_container", {"name": "litellm"})
    base_token = incident_episode_token("docker:litellm", "restart_container", {"name": "litellm"})

    # Episode 0: the identity the caller (RuleBasedRepair) computed.
    assert episode_effect_key(base, base_token, base_token=base_token) == base

    # A settled successor derives from durable facts alone — the previous key
    # and the chained token — so a restart and a second replica agree.
    chained_token = chained_episode_token(base_token, "settled-run")
    next_key = episode_effect_key(base, chained_token, base_token=base_token)
    assert next_key != base
    assert episode_effect_key(base, chained_token, base_token=base_token) == next_key
    # Same prefix family, so ledger/observability grouping survives.
    assert next_key.startswith("self_repair:docker:litellm:restart_container:")
    # A different settled Run chains to a different key: incidents never alias.
    other = episode_effect_key(
        base, chained_episode_token(base_token, "other-run"), base_token=base_token
    )
    assert other != next_key


def test_incident_run_effect_key_scopes_the_provider_key_per_workspace() -> None:
    """Migration 034's effect index is global across Workspaces; the admitted
    Run's identity therefore re-digests the workspace-independent provider key
    under the admission scope."""
    provider_key = stable_effect_key("docker:litellm", "restart_container", {"name": "litellm"})

    scoped_a = incident_run_effect_key("ws-a", "proj-a", provider_key)
    scoped_b = incident_run_effect_key("ws-b", "proj-b", provider_key)

    # Distinct tenants never collide on the global index.
    assert scoped_a != scoped_b
    assert scoped_a != provider_key
    # Deterministic for the same scope.
    assert incident_run_effect_key("ws-a", "proj-a", provider_key) == scoped_a
    # The readable provider family survives for observability.
    assert scoped_a.startswith("self_repair:docker:litellm:restart_container:")


# --- one incident, one Run ---------------------------------------------------


async def test_continuation_collision_converges_to_the_winner_s_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two replicas re-enter the same claimed Run before the winner publishes
    its first checkpoint: the continuation store's uniqueness is the fence and
    the loser returns the winner's parked wait — one Run, one approval, zero
    duplicate effects (#2405 two-replica race)."""
    from types import SimpleNamespace

    import maistro.capabilities.durable_hitl_approval as dha

    winner_record = SimpleNamespace(
        run=SimpleNamespace(status=RunStatus.PAUSED, run_id="winner-run")
    )

    async def colliding_launch(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("run_id collision: 'winner-run'")

    async def get_published(run_id: str) -> Any:
        # The winner publishes between the loser's refusal and this read.
        return winner_record if run_id == "winner-run" else None

    monkeypatch.setattr(dha, "run_durable_graph", colliding_launch)
    record = await dha._launch_admitted_wait(
        store=SimpleNamespace(get=get_published),
        run_store=object(),
        resolver=lambda node_id, graph: None,
        graph_for=lambda key: None,
        inputs_for=lambda key: {},
        base_provenance={},
        actor="loser",
        run_id="winner-run",
        resolved_effect_key="self_repair:x:1",
    )
    assert record is winner_record

    # With no published wait the truth surfaces: the claim's winner died
    # before publishing, and guessing at a replacer is refused.
    async def never_published(run_id: str) -> Any:
        return None

    monkeypatch.setattr(dha, "run_durable_graph", colliding_launch)
    with pytest.raises(ValueError, match="run_id collision"):
        await dha._launch_admitted_wait(
            store=SimpleNamespace(get=never_published),
            run_store=object(),
            resolver=lambda node_id, graph: None,
            graph_for=lambda key: None,
            inputs_for=lambda key: {},
            base_provenance={},
            actor="loser",
            run_id="winner-run",
            resolved_effect_key="self_repair:x:1",
        )


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


async def test_duplicate_occurrence_loser_reconciles_to_winner() -> None:
    """A true cross-process race is decided by the claim, never the probe.

    The loser's probe misses (the winner commits between probe and insert),
    the loser's ``create_run`` raises ``DuplicateOccurrence``, and the loser
    must reconcile to the winner's Run: one insert, no replacement Run, no
    chained claim for a live winner. The in-memory gather above cannot reach
    this branch (its probe always sees the winner), and check-then-insert
    alone is explicitly not the authority (#2405 slice 1).
    """
    from types import SimpleNamespace

    from maistro.capabilities.durable_hitl_approval import _resolve_incident_claim
    from maistro.graph.definitions import Graph, Node
    from maistro.runs.store import DuplicateOccurrence

    resource = "docker:litellm"
    action = "restart_container"
    params = {"name": "litellm"}
    effect_key = incident_run_effect_key(
        "ws-2405",
        "project-2405",
        stable_effect_key(resource, action, params),
    )
    workspace_id = "ws-2405"
    project_id = "project-2405"
    graph = Graph(
        graph_id="self-repair-approval:race",
        workspace_id=workspace_id,
        project_id=project_id,
        name="race fixture",
        nodes=[
            Node(
                node_id="self_repair_action",
                node_type="infra.approval_gated_action",
                inputs={},
                parameters={},
                metadata={},
            )
        ],
        edges=[],
        metadata={},
    )
    winner = SimpleNamespace(
        run_id="winner-run",
        status=RunStatus.PAUSED,
        provenance={"effect_key": effect_key},
    )

    class _WinnerCommitsBetweenProbeAndInsert:
        """Two independent connections: the loser's probe misses, its insert loses."""

        def __init__(self) -> None:
            self.probes: list[dict[str, str]] = []
            self.inserts: list[dict[str, str]] = []

        async def find_occurrence_run(self, claim: Any) -> Any:
            self.probes.append(dict(claim))
            # The winner's claim resolves only once it has committed — i.e.
            # not for the loser's first probe, which ran before the commit.
            if len(self.probes) > 1 and claim.get(SCHEDULE_FIRE_ID_KEY) == episode_token:
                return winner
            return None

        async def create_run(self, _graph: Any, **kwargs: Any) -> Any:
            self.inserts.append(dict(kwargs.get("provenance") or {}))
            if len(self.inserts) == 1:
                raise DuplicateOccurrence(claim_scope, episode_token)
            # A mutant that mints a replacement claim instead of reconciling
            # gets its second insert through — and fails the assertions below.
            return SimpleNamespace(run_id="loser-replacement-run")

    claim = incident_claim(
        workspace_id=workspace_id,
        project_id=project_id,
        resource=resource,
        action=action,
        params=params,
    )
    episode_token = claim[SCHEDULE_FIRE_ID_KEY]
    claim_scope = claim[SCHEDULE_ID_KEY]
    store = _WinnerCommitsBetweenProbeAndInsert()

    run_id, created, resolved_key = await _resolve_incident_claim(
        run_store=store,
        graph_for=lambda key: graph,
        inputs_for=lambda key: {"effect_key": key},
        base_provenance={},
        base_effect_key=effect_key,
        base_token=episode_token,
        claim=claim,
        actor="loser",
    )

    assert created is False
    assert run_id == winner.run_id
    assert resolved_key == effect_key
    # The loser's refused insert carried the episode-0 identity: the key does
    # not move for a live winner, only past a terminal one.
    assert store.inserts[0]["effect_key"] == effect_key
    # The loser never minted a replacement Run for the live claim.
    assert len(store.inserts) == 1
    # The loser never chained the episode: the winner's claim is still live.
    assert all(p[SCHEDULE_FIRE_ID_KEY] == episode_token for p in store.probes)


async def test_cross_process_race_is_decided_by_the_claim_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both replicas probe before either claims: the unique claim still picks one.

    In-memory ``asyncio.gather`` serializes admissions (the loser's probe
    always sees the winner), so this test forces the real two-connection
    interleaving: both probes complete before either claim, and the loser's
    insert hits ``DuplicateOccurrence``. The assertion on the fence counter
    keeps the test honest — a pass reached through check-then-insert alone
    proves nothing (#2405 slice 1).
    """
    from maistro.runs.store import DuplicateOccurrence

    durable, run_store, workspace_id, project_id = await _run_store()
    approvals = InMemoryApprovalStore()
    http = _FakeHttp()

    dup_seen = {"count": 0}
    original_find = type(run_store).find_occurrence_run
    original_create = type(run_store).create_run

    async def slow_find(self: Any, claim: Any) -> Any:
        # Cross-process latency: both replicas probe before either commits.
        await asyncio.sleep(0)
        return await original_find(self, claim)

    async def racing_create(self: Any, graph: Any, **kwargs: Any) -> Any:
        # The probe→insert window: the loser's insert lands after the winner's
        # claim and is refused by the claim (the durable backends' unique
        # index), never by a re-probe.
        await asyncio.sleep(0)
        try:
            return await original_create(self, graph, **kwargs)
        except DuplicateOccurrence:
            dup_seen["count"] += 1
            raise

    monkeypatch.setattr(type(run_store), "find_occurrence_run", slow_find)
    monkeypatch.setattr(type(run_store), "create_run", racing_create)

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

    # The fence, not a lucky probe, resolved the race.
    assert dup_seen["count"] >= 1
    assert record_a.run.run_id == record_b.run.run_id
    final = await durable.get(record_a.run.run_id)
    assert final is not None
    assert final.run.status is RunStatus.PAUSED
    canonical = await run_store.get_run(record_a.run.run_id)
    assert canonical is not None
    assert is_incident_claim(canonical.provenance)
    assert http.calls == []


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
    # The seeded Run mirrors what production admission stamps: the Run-store
    # identity is the scope-digested key, not the workspace-independent
    # provider key (migration 034's index is global across Workspaces).
    provider_key = stable_effect_key(resource, "restart_container", params)
    effect_key = incident_run_effect_key(workspace_id, project_id, provider_key)
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
    # The effect identity moves with the generation: one logical effect is one
    # Run forever (migration 034), so a settled episode's successor must not
    # reuse its key — on PostgreSQL the settled row's key would refuse the
    # insert outright (raw ``ix_canonical_runs_effect`` violation). The
    # episode-0 identity is the scope-digested run key, not the raw provider
    # key (034's index is global across Workspaces).
    base_key = incident_run_effect_key(
        workspace_id,
        project_id,
        stable_effect_key("docker:litellm", "restart_container", {"name": "litellm"}),
    )
    first_canonical = await run_store.get_run(first.run.run_id)
    assert first_canonical is not None
    assert first_canonical.provenance.get("effect_key") == base_key
    chained_key = episode_effect_key(
        base_key,
        chained[SCHEDULE_FIRE_ID_KEY],
        base_token=first_claim[SCHEDULE_FIRE_ID_KEY],
    )
    assert chained_key != base_key
    assert second_canonical.provenance.get("effect_key") == chained_key
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


async def test_in_flight_scan_does_not_stomp_a_wait_admitted_under_it() -> None:
    """A wait admitted while a hydration scan is suspended at its loader await
    survives the scan: the resuming loop skips the resource that already has a
    live wait and hydrates only the rest. The `continue` arm is reachable
    exactly under this interleaving — a concurrent `_admit_approval` lands in
    the process-local dict between the empty-pending guard and the loop body
    (asyncio tasks interleave at the loader's await, within one replica or
    across a second replica's first cycle)."""
    release = asyncio.Event()
    started = asyncio.Event()

    async def slow_loader() -> dict[str, str]:
        started.set()
        await release.wait()
        return {"docker:litellm": "run-from-scan", "docker:api": "run-api"}

    async def must_not_admit(*_args: Any, **_kwargs: Any) -> str:
        raise AssertionError("hydration must never admit")

    repair = RuleBasedRepair(
        infra_monitor=None,
        effect_invoker=None,
        approval_admittor=must_not_admit,
        pending_approvals_loader=slow_loader,
        autonomy="approve_all",
    )
    scan = asyncio.ensure_future(repair._hydrate_pending_approvals())
    await started.wait()
    # The concurrent admission of the same incident lands mid-scan.
    repair._pending_approval_runs["docker:litellm"] = "run-live"
    release.set()
    assert await scan is True
    # The live wait wins; the scan's stale row for it is skipped...
    assert repair._pending_approval_runs["docker:litellm"] == "run-live"
    # ...and the scan's other resource still hydrates with its guard raised.
    # (The live wait's own guard belongs to its admission path, not to the
    # scan — the scan only marks resources it actually hydrates.)
    assert repair._pending_approval_runs["docker:api"] == "run-api"
    assert repair.governor_state()["docker:api"]["in_flight"] is True
    assert "docker:litellm" not in repair.governor_state()


async def test_status_lookup_failure_keeps_the_wait_pending() -> None:
    """A failing durable status lookup never settles the wait (fail closed):
    the resource stays in-flight and no auto-run may dispatch over blindness.
    With no status authority at all, a lookup is `None` by contract."""

    async def broken_status(_run_id: str) -> str | None:
        raise RuntimeError("durable store unavailable")

    async def must_not_invoke(*_args: Any, **_kwargs: Any) -> ActionResult:
        raise AssertionError("no dispatch while a wait's status is unknowable")

    repair = RuleBasedRepair(
        infra_monitor=None,
        effect_invoker=must_not_invoke,
        approval_admittor=None,
        approval_run_status=broken_status,
        autonomy="approve_all",
    )
    repair._pending_approval_runs["docker:litellm"] = "run-1"
    repair._governor.mark_in_flight("docker:litellm")
    await repair._release_settled_approvals()
    assert repair._pending_approval_runs["docker:litellm"] == "run-1"
    assert repair.governor_state()["docker:litellm"]["in_flight"] is True

    # No status authority wired: the lookup contract answers None (never
    # settles) rather than guessing a terminal status.
    bare = RuleBasedRepair(
        infra_monitor=None,
        effect_invoker=None,
        approval_admittor=None,
        approval_run_status=None,
        autonomy="approve_all",
    )
    assert await bare._pending_run_status("docker:litellm", "run-1") is None
