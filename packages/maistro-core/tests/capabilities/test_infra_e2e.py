from __future__ import annotations

from typing import Any

import pytest

from maistro.capabilities.providers.host_health import HostHealthAction, HostHealthMonitor
from maistro.capabilities.registry import CapabilityRegistry
from maistro.capabilities.slots.infra import InfraAction, InfraMonitor
from maistro.capabilities.types import FallbackPolicy, SlotSpec


class FakeHttp:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def get_json(self, path: str) -> dict[str, Any]:
        return {"timestamp": "t", "gpu": {}, "storage": {}, "docker": {}, "vms": [], "services": {}}

    async def post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(path)
        return {"status": "ok"}


@pytest.fixture()
def reg() -> CapabilityRegistry:
    r = CapabilityRegistry()
    r.define(SlotSpec(name="infra_monitor", fallback_policy=FallbackPolicy.SAFE_NOOP))
    r.define(SlotSpec(name="infra_action", fallback_policy=FallbackPolicy.SAFE_NOOP))
    r.define(
        SlotSpec(
            name="approval", fallback_policy=FallbackPolicy.BASELINE, baseline_provider="inbox"
        )
    )
    return r


async def test_monitor_resolves_and_reads(reg: CapabilityRegistry):
    reg.register(HostHealthMonitor(http=FakeHttp()))
    reg.activate("infra_monitor", "host_health")
    mon = await reg.resolve("infra_monitor")
    assert isinstance(mon, InfraMonitor)
    health = await mon.snapshot()
    assert "gpu" in health.resources


async def test_reversible_auto_runs(reg: CapabilityRegistry):
    http = FakeHttp()
    reg.register(HostHealthAction(http=http, autonomy="auto_safe"))
    reg.activate("infra_action", "host_health")
    action = await reg.resolve("infra_action")
    assert isinstance(action, InfraAction)
    res = await action.act("restart_container", {"name": "x"})
    assert res.ok and http.calls


async def test_destructive_blocks_until_approved_flag(reg: CapabilityRegistry):
    """#2405: HostHealthAction no longer awaits InboxApproval; approved= is required."""
    http = FakeHttp()
    reg.register(HostHealthAction(http=http, autonomy="auto_safe"))
    reg.activate("infra_action", "host_health")
    action = await reg.resolve("infra_action")
    assert isinstance(action, InfraAction)

    blocked = await action.act("docker_prune", {})
    assert blocked.ok is False and blocked.blocked_pending_approval and not http.calls

    res = await action.act("docker_prune", {}, approved=True)
    assert res.ok and http.calls
