"""Gap-filling coverage for RuleBasedRepair not exercised by
test_self_repair_provider.py: name/trust_tier/requires properties,
healthcheck's no-monitor branch, governor_state, monitor.snapshot's
exception-swallowing branch, _auto_run's action-exception branch, and
_dispatch_async's action-exception branch."""

from __future__ import annotations

import asyncio

from maistro.capabilities.providers.self_repair import RuleBasedRepair
from maistro.capabilities.slots.infra import ActionResult, InfraHealth, ResourceHealth
from maistro.capabilities.types import ProviderHealth


class _FakeMonitor:
    def __init__(self, *, raises: bool = False) -> None:
        self._raises = raises

    name = "fake_monitor"
    slot = "infra_monitor"
    trust_tier = "t0"

    def requires(self) -> tuple[str, ...]:
        return ()

    async def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(healthy=True)

    async def snapshot(self) -> InfraHealth:
        if self._raises:
            raise RuntimeError("monitor exploded")
        return InfraHealth(
            ts="2026-05-30T00:00:00Z",
            resources={
                "docker": ResourceHealth(
                    "degraded", {"containers": [{"name": "litellm", "state": "unhealthy"}]}
                )
            },
        )


class _RaisingAction:
    name = "fake_action"
    slot = "infra_action"
    trust_tier = "t0"

    def requires(self) -> tuple[str, ...]:
        return ()

    async def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(healthy=True)

    def allowed_actions(self) -> tuple[str, ...]:
        return ("restart_container",)

    async def act(self, action: str, params: dict) -> ActionResult:
        raise RuntimeError("action exploded")


class TestProviderMetadata:
    def test_name_is_rule_based_repair(self) -> None:
        p = RuleBasedRepair(infra_monitor=None, infra_action=None)
        assert p.name == "rule_based_repair"

    def test_trust_tier_is_t0(self) -> None:
        p = RuleBasedRepair(infra_monitor=None, infra_action=None)
        assert p.trust_tier == "t0"

    def test_requires_is_empty(self) -> None:
        p = RuleBasedRepair(infra_monitor=None, infra_action=None)
        assert p.requires() == ()


class TestHealthcheck:
    async def test_no_monitor_is_unhealthy(self) -> None:
        p = RuleBasedRepair(infra_monitor=None, infra_action=None)
        health = await p.healthcheck()
        assert health.healthy is False
        assert "no infra_monitor" in (health.detail or "")

    async def test_with_monitor_is_healthy(self) -> None:
        p = RuleBasedRepair(infra_monitor=_FakeMonitor(), infra_action=None)
        health = await p.healthcheck()
        assert health.healthy is True


class TestGovernorState:
    def test_exposes_governor_state_summary(self) -> None:
        p = RuleBasedRepair(infra_monitor=None, infra_action=None)
        assert p.governor_state() == p._governor.state_summary()


class TestMonitorSnapshotFailure:
    async def test_snapshot_exception_yields_empty_cycle(self) -> None:
        p = RuleBasedRepair(infra_monitor=_FakeMonitor(raises=True), infra_action=None)
        result = await p.run_once()
        assert result.results == []
        assert p.last_cycle is result


class TestAutoRunFailure:
    async def test_action_exception_yields_failed_result(self) -> None:
        p = RuleBasedRepair(
            infra_monitor=_FakeMonitor(),
            infra_action=_RaisingAction(),
            autonomy="auto_safe",
        )
        result = await p.run_once()
        (r,) = result.results
        assert r.detail == "action exploded"


class TestDispatchAsyncFailure:
    async def test_dispatch_async_exception_is_logged_and_swallowed(self) -> None:
        p = RuleBasedRepair(
            infra_monitor=_FakeMonitor(),
            infra_action=_RaisingAction(),
            autonomy="approve_all",
        )
        result = await p.run_once()
        (r,) = result.results
        assert r.decision.value == "pending_approval"
        await asyncio.gather(*list(p._tasks))  # drain — must not raise
