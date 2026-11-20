"""Self-repair approval waits are durable waiting-human NodeRuns (#2405)."""

from __future__ import annotations

from typing import Any

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

    def requires(self) -> tuple[str, ...]:
        return ()

    async def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(healthy=True)

    async def snapshot(self) -> InfraHealth:
        return InfraHealth(
            ts="t",
            resources={
                "docker": ResourceHealth(
                    "degraded", {"containers": [{"name": "litellm", "state": "unhealthy"}]}
                )
            },
        )


def _binding() -> Binding:
    return Binding(
        binding_id="builtin:self-repair:infra-action",
        workspace_id="ws-2405",
        project_id="project-2405",
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
        action="restart_container",
        params={"name": "litellm"},
        effect_key="self_repair:docker:restart_container:1",
        resolve_provider=resolve_provider,
    )

    assert record.run.status is RunStatus.PAUSED
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
