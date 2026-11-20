"""Self-repair approval waits are durable waiting-human NodeRuns (#2405)."""

from __future__ import annotations

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
from maistro.capabilities.slots.infra import ActionResult, InfraAction, InfraHealth, ResourceHealth
from maistro.capabilities.slots.self_repair import RepairDecision, RepairProposal
from maistro.capabilities.types import ProviderHealth
from maistro.graph.durable_runs import InMemoryDurableRunStore, RunStatus, pending_hitl_node_ids
from maistro.graph.execution_state import thaw_json_value
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID


class _FakeHttp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def get_json(self, path: str) -> dict[str, Any]:
        return {}

    async def post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((path, body))
        return {"status": "ok", "detail": "restarted"}


class _Monitor:
    name = "m"
    slot = "infra_monitor"
    trust_tier = "t0"

    def __init__(self, *, degraded: bool = True) -> None:
        self.degraded = degraded

    def requires(self) -> tuple[str, ...]:
        return ()

    async def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(healthy=True)

    async def snapshot(self) -> InfraHealth:
        state = "unhealthy" if self.degraded else "healthy"
        status = "degraded" if self.degraded else "ok"
        return InfraHealth(
            ts="t",
            resources={
                "docker": ResourceHealth(
                    status, {"containers": [{"name": "litellm", "state": state}]}
                )
            },
        )


def _binding() -> Binding:
    # Synthetic effect-Binding scope — must not become the Run's HITL scope.
    return Binding(
        binding_id="builtin:self-repair:infra-action",
        workspace_id="default",
        project_id="default",
        node_id="self-repair",
        capability="infra_action",
    )


async def test_admit_self_repair_approval_parks_paused_waiting_human() -> None:
    store = InMemoryDurableRunStore()
    approvals = InMemoryApprovalStore()
    effects = new_effect_context(approval_store=approvals)
    await effects.bindings.put(_binding())
    http = _FakeHttp()
    action = HostHealthAction(http, autonomy="approve_all")

    async def resolve_provider(_candidate: Binding) -> InfraAction:
        return action

    record = await admit_self_repair_approval(
        store=store,
        effect_context=effects,
        binding=_binding(),
        workspace_id="ws-2405",
        project_id="project-2405",
        action="restart_container",
        params={"name": "litellm"},
        effect_key="self_repair:docker:restart_container:1",
        resolve_provider=resolve_provider,
    )

    assert record.run.status is RunStatus.PAUSED
    assert record.run.workspace_id == "ws-2405"
    assert record.run.project_id == "project-2405"
    assert SELF_REPAIR_APPROVAL_NODE_ID in pending_hitl_node_ids(record)
    pause = thaw_json_value(record.graph_state.metadata)["pause"]
    assert pause["metadata"]["paused_reason"] == "awaiting_human_approval"
    assert pause["metadata"]["action"] == "restart_container"
    assert http.calls == []

    # Restart survival: a fresh store view still sees the paused human work.
    reloaded = await store.get(record.run.run_id)
    assert reloaded is not None
    assert reloaded.run.status is RunStatus.PAUSED
    assert SELF_REPAIR_APPROVAL_NODE_ID in pending_hitl_node_ids(reloaded)
    assert http.calls == []


async def test_admit_with_run_store_admits_canonical_run_before_executor() -> None:
    """Hive passes run_store; admission must create_run before run_durable_graph."""
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-2405-spine")
    run_store = InMemoryRunStore(project_store=projects)
    store = InMemoryDurableRunStore()
    approvals = InMemoryApprovalStore()
    effects = new_effect_context(approval_store=approvals)
    await effects.bindings.put(_binding())
    http = _FakeHttp()
    action = HostHealthAction(http, autonomy="approve_all")

    async def resolve_provider(_candidate: Binding) -> InfraAction:
        return action

    record = await admit_self_repair_approval(
        store=store,
        effect_context=effects,
        binding=_binding(),
        workspace_id="ws-2405-spine",
        project_id=root.project_id,
        action="restart_container",
        params={"name": "litellm"},
        effect_key="self_repair:docker:restart_container:spine",
        resolve_provider=resolve_provider,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        run_store=run_store,
    )

    assert record.run.status is RunStatus.PAUSED
    canonical = await run_store.get_run(record.run.run_id)
    assert canonical is not None
    assert canonical.workspace_id == "ws-2405-spine"
    assert canonical.project_id == root.project_id
    assert canonical.workspace_id != _binding().workspace_id
    assert SELF_REPAIR_APPROVAL_NODE_ID in pending_hitl_node_ids(record)
    assert http.calls == []


async def test_rule_based_repair_uses_durable_admittor_not_inbox_event() -> None:
    admitted: list[str] = []

    async def admit(proposal: RepairProposal, effect_key: str) -> str:
        admitted.append(effect_key)
        assert proposal.action == "restart_container"
        return "run-durable-1"

    async def must_not_invoke(*_args: Any, **_kwargs: Any) -> ActionResult:
        raise AssertionError("gated actions must not auto-invoke through effect_invoker")

    repair = RuleBasedRepair(
        infra_monitor=_Monitor(),
        effect_invoker=must_not_invoke,
        approval_admittor=admit,
        autonomy="approve_all",
    )
    cycle = await repair.run_once()
    (result,) = cycle.results
    assert result.decision is RepairDecision.PENDING_APPROVAL
    assert "run_id=run-durable-1" in result.detail
    assert admitted and admitted[0].startswith("self_repair:")
    assert repair._pending_approval_runs["docker:litellm"] == "run-durable-1"
    assert repair.governor_state()["docker:litellm"]["in_flight"] is True


async def test_rule_based_repair_releases_governor_when_approval_run_settles() -> None:
    statuses: dict[str, str] = {}
    monitor = _Monitor(degraded=True)

    async def admit(proposal: RepairProposal, effect_key: str) -> str:
        statuses["run-cancel-1"] = "paused"
        return "run-cancel-1"

    async def status_of(run_id: str) -> str | None:
        return statuses.get(run_id)

    async def must_not_invoke(*_args: Any, **_kwargs: Any) -> ActionResult:
        raise AssertionError("gated actions must not auto-invoke through effect_invoker")

    repair = RuleBasedRepair(
        infra_monitor=monitor,
        effect_invoker=must_not_invoke,
        approval_admittor=admit,
        approval_run_status=status_of,
        autonomy="approve_all",
    )
    await repair.run_once()
    assert repair.governor_state()["docker:litellm"]["in_flight"] is True

    # cancel_hitl (or timeout) settles the Run; next cycle must clear in_flight.
    # Healthy snapshot avoids re-admitting in the same cycle after reconcile.
    statuses["run-cancel-1"] = "cancelled"
    monitor.degraded = False
    await repair.run_once()
    assert repair.governor_state()["docker:litellm"]["in_flight"] is False
    assert "docker:litellm" not in repair._pending_approval_runs


async def test_rule_based_repair_suppresses_without_durable_admittor() -> None:
    """No InboxApproval fallback: missing admittor must not spawn an Event wait."""

    async def must_not_invoke(*_args: Any, **_kwargs: Any) -> ActionResult:
        raise AssertionError("gated actions must not fall through to effect_invoker")

    repair = RuleBasedRepair(
        infra_monitor=_Monitor(),
        effect_invoker=must_not_invoke,
        approval_admittor=None,
        autonomy="approve_all",
    )
    cycle = await repair.run_once()
    (result,) = cycle.results
    assert result.decision is RepairDecision.SUPPRESSED
    assert "durable approval admittor" in result.detail


async def test_admit_rejects_read_tier_actions() -> None:
    store = InMemoryDurableRunStore()
    effects = new_effect_context(approval_store=InMemoryApprovalStore())
    await effects.bindings.put(_binding())

    async def resolve_provider(_candidate: Binding) -> InfraAction:
        return HostHealthAction(_FakeHttp(), autonomy="approve_all")

    with pytest.raises(ValueError, match="does not require durable approval"):
        await admit_self_repair_approval(
            store=store,
            effect_context=effects,
            binding=_binding(),
            workspace_id="ws",
            project_id="proj",
            action="docker_logs",
            params={"name": "x"},
            effect_key="ek-read",
            resolve_provider=resolve_provider,
        )


async def test_admit_rejects_blank_hitl_scope() -> None:
    store = InMemoryDurableRunStore()
    effects = new_effect_context(approval_store=InMemoryApprovalStore())
    await effects.bindings.put(_binding())

    async def resolve_provider(_candidate: Binding) -> InfraAction:
        return HostHealthAction(_FakeHttp(), autonomy="approve_all")

    with pytest.raises(ValueError, match="workspace_id and project_id are required"):
        await admit_self_repair_approval(
            store=store,
            effect_context=effects,
            binding=_binding(),
            workspace_id="  ",
            project_id="proj",
            action="restart_container",
            params={"name": "x"},
            effect_key="ek-blank",
            resolve_provider=resolve_provider,
        )


async def test_admit_requires_approval_store() -> None:
    store = InMemoryDurableRunStore()
    effects = new_effect_context()  # no ApprovalStore
    await effects.bindings.put(_binding())

    async def resolve_provider(_candidate: Binding) -> InfraAction:
        return HostHealthAction(_FakeHttp(), autonomy="approve_all")

    with pytest.raises(RuntimeError, match="no ApprovalStore"):
        await admit_self_repair_approval(
            store=store,
            effect_context=effects,
            binding=_binding(),
            workspace_id="ws",
            project_id="proj",
            action="restart_container",
            params={"name": "x"},
            effect_key="ek-no-store",
            resolve_provider=resolve_provider,
        )


async def test_require_approval_policy_allows_when_already_approved() -> None:
    from maistro.capabilities.durable_hitl_approval import _require_approval_policy
    from maistro.capabilities.governed_invocation import InvocationPolicyContext
    from maistro.policy.types import Decision

    ctx = InvocationPolicyContext(
        run_id="r",
        node_run_id="nr",
        attempt_id="a",
        effect_key="ek",
        approved=True,
    )
    verdict = await _require_approval_policy(_binding(), {"action": "restart_container"}, ctx)
    assert verdict.decision is Decision.ALLOW
    assert verdict.rule == "self-repair-hitl"

    pending = await _require_approval_policy(
        _binding(),
        {"action": "restart_container"},
        InvocationPolicyContext(run_id="r", node_run_id="nr", attempt_id="a", effect_key="ek"),
    )
    assert pending.decision is Decision.REQUIRE_APPROVAL


async def test_infra_approval_node_executes_approved_provider() -> None:
    """Post-approval path: resolver + executor + result mapping (#2405)."""
    from types import SimpleNamespace

    from maistro.capabilities.durable_hitl_approval import (
        _InfraActionIn,
        _InfraApprovalNode,
    )
    from maistro.graph.nodes.base import NodeContext

    http = _FakeHttp()
    action = HostHealthAction(http, autonomy="approve_all")

    class _Service:
        async def invoke(self, **kwargs: Any) -> SimpleNamespace:
            provider = await kwargs["resolver"](_binding())
            result = await kwargs["executor"](provider, kwargs["request"])
            return SimpleNamespace(result=result)

    async def resolve_ok(_c: Binding) -> InfraAction:
        return action

    async def execute_approved(
        provider: InfraAction, approved_action: str, approved_params: dict[str, Any]
    ) -> ActionResult:
        return await provider.act(approved_action, approved_params, approved=True)

    node = _InfraApprovalNode(
        service=_Service(),  # type: ignore[arg-type]
        binding=_binding(),
        resolve_provider=resolve_ok,
        execute_approved=execute_approved,
    )
    out = await node._execute(
        _InfraActionIn(action="restart_container", params={"name": "x"}, effect_key="ek"),
        NodeContext(run_id="r", dag_id="d", node_id="n", node_run_id="nr", attempt_id="a"),
    )
    assert out.ok is True
    assert out.detail == "restarted"
    assert out.blocked_pending_approval is False
    assert http.calls

    async def bad_provider(_c: Binding) -> Any:
        return object()

    bad_node = _InfraApprovalNode(
        service=_Service(),  # type: ignore[arg-type]
        binding=_binding(),
        resolve_provider=bad_provider,
        execute_approved=execute_approved,
    )
    with pytest.raises(TypeError, match="non-infra provider"):
        await bad_node._execute(
            _InfraActionIn(action="restart_container", params={}, effect_key="ek"),
            NodeContext(run_id="r", dag_id="d", node_id="n"),
        )

    class _EmptyService:
        async def invoke(self, **kwargs: Any) -> SimpleNamespace:
            await kwargs["resolver"](_binding())
            return SimpleNamespace(result="not-a-mapping")

    empty_node = _InfraApprovalNode(
        service=_EmptyService(),  # type: ignore[arg-type]
        binding=_binding(),
        resolve_provider=resolve_ok,
        execute_approved=execute_approved,
    )
    empty_out = await empty_node._execute(
        _InfraActionIn(action="restart_container", params={}, effect_key="ek"),
        NodeContext(run_id="r", dag_id="d", node_id="n"),
    )
    assert empty_out.ok is False
    assert empty_out.detail == ""


async def test_admit_execute_approved_supports_legacy_act(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production execute_approved: approved=True, plus TypeError fallback."""
    from maistro.capabilities import durable_hitl_approval as mod
    from maistro.graph.durable_runs import DurableRunRecord
    from maistro.graph.execution_state import GraphExecutionState
    from maistro.runs.model import GraphSnapshot, Run

    store = InMemoryDurableRunStore()
    effects = new_effect_context(approval_store=InMemoryApprovalStore())
    await effects.bindings.put(_binding())
    http = _FakeHttp()
    modern = HostHealthAction(http, autonomy="approve_all")
    legacy_calls: list[tuple[str, dict[str, Any]]] = []

    class _LegacyAction:
        name = "legacy"
        slot = "infra_action"
        trust_tier = "t0"

        def requires(self) -> tuple[str, ...]:
            return ()

        async def healthcheck(self) -> ProviderHealth:
            return ProviderHealth(healthy=True)

        def allowed_actions(self) -> tuple[str, ...]:
            return ("restart_container",)

        async def act(self, action: str, params: dict[str, Any]) -> ActionResult:
            legacy_calls.append((action, params))
            return ActionResult(ok=True, detail="legacy-ok")

    captured: list[Any] = []

    async def fake_run_durable_graph(graph, *, node_resolver, **kwargs):
        node = node_resolver(SELF_REPAIR_APPROVAL_NODE_ID, graph)
        captured.append(node)
        # Exercise the nested execute_approved closed over by admit.
        modern_result = await node._execute_approved(
            modern, "restart_container", {"name": "modern"}
        )
        assert modern_result.ok is True
        legacy_result = await node._execute_approved(
            _LegacyAction(),  # type: ignore[arg-type]
            "restart_container",
            {"name": "legacy"},
        )
        assert legacy_result.detail == "legacy-ok"
        run = Run(
            run_id="run-exec",
            workspace_id=graph.workspace_id,
            project_id=graph.project_id,
            graph=GraphSnapshot.from_graph(graph),
            actor_principal_id="self-repair",
            status=RunStatus.PAUSED,
        )
        return DurableRunRecord(
            run=run,
            graph_state=GraphExecutionState(
                run_id=run.run_id,
                active_node_ids=(SELF_REPAIR_APPROVAL_NODE_ID,),
                blackboard_snapshot={},
                metadata={},
            ),
            node_runs=(),
            version=1,
        )

    async def resolve_provider(_candidate: Binding) -> InfraAction:
        return modern

    monkeypatch.setattr(mod, "run_durable_graph", fake_run_durable_graph)
    record = await admit_self_repair_approval(
        store=store,
        effect_context=effects,
        binding=_binding(),
        workspace_id="ws",
        project_id="proj",
        action="restart_container",
        params={"name": "x"},
        effect_key="ek-exec",
        resolve_provider=resolve_provider,
    )
    assert record.run.status is RunStatus.PAUSED
    assert captured and http.calls
    assert legacy_calls == [("restart_container", {"name": "legacy"})]


async def test_admit_resolver_rejects_unknown_node_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from maistro.capabilities import durable_hitl_approval as mod
    from maistro.graph.durable_runs import DurableRunRecord
    from maistro.graph.execution_state import GraphExecutionState
    from maistro.runs.model import GraphSnapshot, Run

    store = InMemoryDurableRunStore()
    effects = new_effect_context(approval_store=InMemoryApprovalStore())
    await effects.bindings.put(_binding())

    async def resolve_provider(_candidate: Binding) -> InfraAction:
        return HostHealthAction(_FakeHttp(), autonomy="approve_all")

    async def fake_run_durable_graph(graph, *, node_resolver, **kwargs):
        with pytest.raises(KeyError, match="not-the-approval-node"):
            node_resolver("not-the-approval-node", graph)
        run = Run(
            run_id="run-keyerr",
            workspace_id=graph.workspace_id,
            project_id=graph.project_id,
            graph=GraphSnapshot.from_graph(graph),
            actor_principal_id="self-repair",
            status=RunStatus.PAUSED,
        )
        return DurableRunRecord(
            run=run,
            graph_state=GraphExecutionState(
                run_id=run.run_id,
                active_node_ids=(SELF_REPAIR_APPROVAL_NODE_ID,),
                blackboard_snapshot={},
                metadata={},
            ),
            node_runs=(),
            version=1,
        )

    monkeypatch.setattr(mod, "run_durable_graph", fake_run_durable_graph)
    record = await admit_self_repair_approval(
        store=store,
        effect_context=effects,
        binding=_binding(),
        workspace_id="ws",
        project_id="proj",
        action="restart_container",
        params={"name": "x"},
        effect_key="ek-key",
        resolve_provider=resolve_provider,
    )
    assert record.run.status is RunStatus.PAUSED


async def test_admit_raises_when_executor_does_not_pause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from maistro.capabilities import durable_hitl_approval as mod
    from maistro.graph.durable_runs import DurableRunRecord
    from maistro.graph.execution_state import GraphExecutionState
    from maistro.runs.model import GraphSnapshot, Run

    store = InMemoryDurableRunStore()
    effects = new_effect_context(approval_store=InMemoryApprovalStore())
    await effects.bindings.put(_binding())

    async def resolve_provider(_candidate: Binding) -> InfraAction:
        return HostHealthAction(_FakeHttp(), autonomy="approve_all")

    async def running_run(graph, **kwargs):
        run = Run(
            run_id="run-running",
            workspace_id=graph.workspace_id,
            project_id=graph.project_id,
            graph=GraphSnapshot.from_graph(graph),
            actor_principal_id="self-repair",
            status=RunStatus.RUNNING,
        )
        return DurableRunRecord(
            run=run,
            graph_state=GraphExecutionState(
                run_id=run.run_id,
                active_node_ids=(),
                blackboard_snapshot={},
                metadata={},
            ),
            node_runs=(),
            version=1,
        )

    monkeypatch.setattr(mod, "run_durable_graph", running_run)
    with pytest.raises(RuntimeError, match="expected PAUSED"):
        await admit_self_repair_approval(
            store=store,
            effect_context=effects,
            binding=_binding(),
            workspace_id="ws",
            project_id="proj",
            action="restart_container",
            params={"name": "x"},
            effect_key="ek-completed",
            resolve_provider=resolve_provider,
        )
