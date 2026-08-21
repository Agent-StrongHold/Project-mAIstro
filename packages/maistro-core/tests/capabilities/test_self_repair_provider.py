"""RuleBasedRepair provider — the detect→diagnose→govern→act orchestrator (SPEC-188)."""

from __future__ import annotations

import asyncio

from maistro.capabilities.protocols import CapabilityProvider
from maistro.capabilities.providers.self_repair import RuleBasedRepair
from maistro.capabilities.slots.infra import ActionResult, InfraHealth, ResourceHealth
from maistro.capabilities.slots.self_repair import RepairDecision, SelfRepair
from maistro.capabilities.types import ProviderHealth


class _FakeMonitor:
    def __init__(self, health: InfraHealth | None) -> None:
        self._health = health
        self.calls = 0

    name = "fake_monitor"
    slot = "infra_monitor"
    trust_tier = "t0"

    def requires(self) -> tuple[str, ...]:
        return ()

    async def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(healthy=True)

    async def snapshot(self) -> InfraHealth:
        self.calls += 1
        assert self._health is not None
        return self._health


class _FakeAction:
    def __init__(self, *, block: asyncio.Event | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._block = block

    name = "fake_action"
    slot = "infra_action"
    trust_tier = "t0"

    def requires(self) -> tuple[str, ...]:
        return ()

    async def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(healthy=True)

    def allowed_actions(self) -> tuple[str, ...]:
        return ("restart_container", "restart_stack", "restart_service", "vm_control")

    async def act(self, action: str, params: dict) -> ActionResult:
        self.calls.append((action, params))
        if self._block is not None:
            await self._block.wait()  # simulate an action parked awaiting approval
        return ActionResult(ok=True, detail="done")


def _health(**sections: ResourceHealth) -> InfraHealth:
    return InfraHealth(ts="2026-05-30T00:00:00Z", resources=dict(sections))


def _unhealthy_container(name: str = "litellm") -> InfraHealth:
    return _health(
        docker=ResourceHealth("degraded", {"containers": [{"name": name, "state": "unhealthy"}]})
    )


async def _drain(provider: RuleBasedRepair) -> None:
    if provider._tasks:  # test drains background dispatch tasks
        await asyncio.gather(*list(provider._tasks))


def test_provider_satisfies_protocols() -> None:
    p = RuleBasedRepair(infra_monitor=_FakeMonitor(None), infra_action=_FakeAction())
    assert isinstance(p, SelfRepair)
    assert isinstance(p, CapabilityProvider)
    assert p.slot == "self_repair"


async def test_no_monitor_returns_empty_cycle() -> None:
    p = RuleBasedRepair(infra_monitor=None, infra_action=_FakeAction())
    result = await p.run_once()
    assert result.results == []


async def test_healthy_snapshot_acts_on_nothing() -> None:
    action = _FakeAction()
    mon = _FakeMonitor(
        _health(docker=ResourceHealth("ok", {"containers": [{"name": "x", "state": "healthy"}]}))
    )
    result = await RuleBasedRepair(infra_monitor=mon, infra_action=action).run_once()
    assert result.results == []
    assert action.calls == []


async def test_auto_safe_reversible_is_acted_inline() -> None:
    action = _FakeAction()
    p = RuleBasedRepair(
        infra_monitor=_FakeMonitor(_unhealthy_container()),
        infra_action=action,
        autonomy="auto_safe",
    )
    result = await p.run_once()
    (r,) = result.results
    assert r.decision is RepairDecision.ACTED
    assert action.calls == [("restart_container", {"name": "litellm"})]


async def test_reversible_needs_approval_under_approve_all_not_blocking() -> None:
    # Under approve_all, even a reversible fix routes through approval; run_once
    # must dispatch it as a tracked task and return without blocking.
    action = _FakeAction()
    p = RuleBasedRepair(
        infra_monitor=_FakeMonitor(_unhealthy_container()),
        infra_action=action,
        autonomy="approve_all",
    )
    result = await p.run_once()
    (r,) = result.results
    assert r.decision is RepairDecision.PENDING_APPROVAL
    await _drain(p)
    assert action.calls == [("restart_container", {"name": "litellm"})]


async def test_detect_only_dispatches_nothing() -> None:
    action = _FakeAction()
    p = RuleBasedRepair(
        infra_monitor=_FakeMonitor(_unhealthy_container()),
        infra_action=action,
        autonomy="detect_only",
    )
    result = await p.run_once()
    (r,) = result.results
    assert r.decision is RepairDecision.SUPPRESSED
    assert "detect_only" in r.detail
    assert action.calls == []


async def test_storage_is_propose_only() -> None:
    action = _FakeAction()
    health = _health(
        storage=ResourceHealth("degraded", {"pools": [{"name": "dbpool", "healthy": False}]})
    )
    result = await RuleBasedRepair(
        infra_monitor=_FakeMonitor(health), infra_action=action
    ).run_once()
    (r,) = result.results
    assert r.decision is RepairDecision.PROPOSE_ONLY
    assert action.calls == []


async def test_undiagnosed_is_recorded_not_acted() -> None:
    action = _FakeAction()
    health = _health(docker=ResourceHealth("down", {"mystery": 1}))
    result = await RuleBasedRepair(
        infra_monitor=_FakeMonitor(health), infra_action=action
    ).run_once()
    (r,) = result.results
    assert r.decision is RepairDecision.UNDIAGNOSED
    assert action.calls == []


async def test_per_cycle_action_cap() -> None:
    action = _FakeAction()
    health = _health(
        docker=ResourceHealth(
            "degraded",
            {
                "containers": [
                    {"name": "a", "state": "unhealthy"},
                    {"name": "b", "state": "unhealthy"},
                    {"name": "c", "state": "unhealthy"},
                ]
            },
        )
    )
    p = RuleBasedRepair(
        infra_monitor=_FakeMonitor(health),
        infra_action=action,
        autonomy="auto_safe",
        max_actions_per_cycle=2,
    )
    result = await p.run_once()
    await _drain(p)
    acted = [r for r in result.results if r.decision is RepairDecision.ACTED]
    suppressed = [r for r in result.results if r.decision is RepairDecision.SUPPRESSED]
    assert len(acted) == 2
    assert len(suppressed) == 1
    assert "cap" in suppressed[0].detail.lower()
    assert len(action.calls) == 2


async def test_in_flight_guard_across_cycles() -> None:
    # A resource still pending approval is not re-dispatched next cycle.
    block = asyncio.Event()
    action = _FakeAction(block=block)  # restart parks until released (approval-gated)
    p = RuleBasedRepair(
        infra_monitor=_FakeMonitor(_unhealthy_container()),
        infra_action=action,
        autonomy="approve_all",
    )
    await p.run_once()  # dispatches restart_container as a parked pending task (in_flight)
    await asyncio.sleep(0)  # let the task start (and block)
    result2 = await p.run_once()  # same resource still in flight
    (r,) = result2.results
    assert r.decision is RepairDecision.SUPPRESSED
    assert r.detail == "in_flight"
    block.set()  # release so the task can finish and clear in-flight
    await _drain(p)


async def test_last_cycle_is_exposed_for_the_api() -> None:
    p = RuleBasedRepair(
        infra_monitor=_FakeMonitor(_unhealthy_container()), infra_action=_FakeAction()
    )
    assert p.last_cycle is None
    await p.run_once()
    assert p.last_cycle is not None
    assert len(p.last_cycle.results) == 1
