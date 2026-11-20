"""self_repair end-to-end with durable waiting-human approval (#2405 / SPEC-188).

Proves approval-gated remediation parks a durable Run rather than awaiting an
in-process InboxApproval Event, and only hits the host after approved=True.
"""

from __future__ import annotations

from typing import Any

import httpx

from maistro.capabilities.approval_store import InMemoryApprovalStore
from maistro.capabilities.binding import Binding
from maistro.capabilities.durable_hitl_approval import admit_self_repair_approval
from maistro.capabilities.effect_context import new_effect_context
from maistro.capabilities.http_client import HttpxAsyncHttp
from maistro.capabilities.providers.host_health import HostHealthAction
from maistro.capabilities.providers.self_repair import RuleBasedRepair
from maistro.capabilities.slots.infra import InfraAction, InfraHealth, ResourceHealth
from maistro.capabilities.slots.self_repair import RepairDecision, RepairProposal
from maistro.capabilities.types import ProviderHealth
from maistro.graph.durable_runs import InMemoryDurableRunStore, RunStatus, pending_hitl_node_ids


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
        workspace_id="ws-sr",
        project_id="project-sr",
        node_id="self-repair",
        capability="infra_action",
    )


async def test_remediation_parks_durable_run_until_approved() -> None:
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.url.path)
        return httpx.Response(200, json={"status": "ok", "detail": "restarted"})

    http = HttpxAsyncHttp("http://h:8150", transport=httpx.MockTransport(handler))
    action = HostHealthAction(http, autonomy="approve_all")
    store = InMemoryDurableRunStore()
    effects = new_effect_context(approval_store=InMemoryApprovalStore())
    await effects.bindings.put(_binding())

    async def resolve_provider(_candidate: Binding) -> InfraAction:
        return action

    async def admit(proposal: RepairProposal, effect_key: str) -> str:
        record = await admit_self_repair_approval(
            store=store,
            effect_context=effects,
            binding=_binding(),
            action=proposal.action or "",
            params=proposal.params,
            effect_key=effect_key,
            resolve_provider=resolve_provider,
        )
        return record.run.run_id

    async def must_not_auto(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("gated path must not auto-invoke")

    repair = RuleBasedRepair(
        infra_monitor=_Monitor(),
        effect_invoker=must_not_auto,
        approval_admittor=admit,
        autonomy="approve_all",
    )

    cycle = await repair.run_once()
    (r,) = cycle.results
    assert r.decision is RepairDecision.PENDING_APPROVAL
    assert sent == []
    run_id = repair._pending_approval_runs["docker:litellm"]
    parked = await store.get(run_id)
    assert parked is not None
    assert parked.run.status is RunStatus.PAUSED
    assert pending_hitl_node_ids(parked)


async def test_denied_style_gate_never_hits_host_without_approved_flag() -> None:
    sent: list[str] = []
    http = HttpxAsyncHttp(
        "http://h:8150",
        transport=httpx.MockTransport(
            lambda r: (sent.append(r.url.path), httpx.Response(200, json={}))[1]
        ),
    )
    action = HostHealthAction(http, autonomy="approve_all")
    # Direct act without approved= must refuse, matching the durable-gate contract.
    result = await action.act("restart_container", {"name": "x"})
    assert result.blocked_pending_approval is True
    assert sent == []
