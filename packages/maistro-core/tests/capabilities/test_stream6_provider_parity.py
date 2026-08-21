from __future__ import annotations

import pytest

from maistro.capabilities.registry import CapabilityRegistry
from maistro.capabilities.tests_fakes import FakeProvider
from maistro.capabilities.types import FallbackPolicy, SlotSpec


@pytest.mark.asyncio
async def test_explicit_active_provider_is_selected_when_healthy() -> None:
    registry = CapabilityRegistry()
    registry.define(SlotSpec(name="tool", fallback_policy=FallbackPolicy.SAFE_NOOP))
    lower_tier = FakeProvider("lower-tier", "tool", tier="t0")
    active = FakeProvider("active", "tool", tier="t2")
    registry.register(lower_tier)
    registry.register(active)
    registry.activate("tool", "active")

    assert await registry.resolve("tool") is active


@pytest.mark.asyncio
async def test_unhealthy_active_provider_falls_back_to_declared_baseline() -> None:
    registry = CapabilityRegistry()
    registry.define(
        SlotSpec(
            name="tool",
            fallback_policy=FallbackPolicy.BASELINE,
            baseline_provider="baseline",
        )
    )
    baseline = FakeProvider("baseline", "tool")
    unhealthy = FakeProvider("primary", "tool", healthy=False)
    registry.register(baseline)
    registry.register(unhealthy)
    registry.activate("tool", "primary")

    assert await registry.resolve("tool") is baseline


@pytest.mark.asyncio
async def test_disabled_slot_uses_declared_baseline_without_selecting_primary() -> None:
    registry = CapabilityRegistry()
    registry.define(
        SlotSpec(
            name="tool",
            fallback_policy=FallbackPolicy.BASELINE,
            baseline_provider="baseline",
        )
    )
    baseline = FakeProvider("baseline", "tool")
    primary = FakeProvider("primary", "tool")
    registry.register(baseline)
    registry.register(primary)
    registry.activate("tool", "primary")
    registry.set_enabled("tool", False)

    assert await registry.resolve("tool") is baseline


@pytest.mark.asyncio
async def test_safe_noop_returns_none_when_active_provider_is_unhealthy() -> None:
    registry = CapabilityRegistry()
    registry.define(SlotSpec(name="tool", fallback_policy=FallbackPolicy.SAFE_NOOP))
    unhealthy = FakeProvider("primary", "tool", healthy=False)
    registry.register(unhealthy)
    registry.activate("tool", "primary")

    assert await registry.resolve("tool") is None


@pytest.mark.asyncio
async def test_unpinned_provider_selection_prefers_lowest_trust_tier() -> None:
    registry = CapabilityRegistry()
    registry.define(SlotSpec(name="tool", fallback_policy=FallbackPolicy.SAFE_NOOP))
    higher_tier = FakeProvider("higher-tier", "tool", tier="t3")
    lower_tier = FakeProvider("lower-tier", "tool", tier="t1")
    registry.register(higher_tier)
    registry.register(lower_tier)

    assert await registry.resolve("tool") is lower_tier
