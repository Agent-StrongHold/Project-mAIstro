from __future__ import annotations

import pytest

from maistro.capabilities.registry import CapabilityRegistry
from maistro.capabilities.tests_fakes import FakeProvider
from maistro.capabilities.types import FallbackPolicy, SlotSpec


@pytest.fixture()
def reg() -> CapabilityRegistry:
    r = CapabilityRegistry()
    r.define(SlotSpec(name="search", fallback_policy=FallbackPolicy.SAFE_NOOP))
    r.define(
        SlotSpec(
            name="approval", fallback_policy=FallbackPolicy.BASELINE, baseline_provider="inbox"
        )
    )
    r.define(SlotSpec(name="llm", fallback_policy=FallbackPolicy.HARD_REQUIRED))
    return r


async def test_disabled_slot_resolves_to_fallback_none(reg: CapabilityRegistry):
    reg.register(FakeProvider("tavily", "search"))
    reg.activate("search", "tavily")
    reg.set_enabled("search", False)
    assert await reg.resolve("search") is None


async def test_active_healthy_resolves(reg: CapabilityRegistry):
    reg.register(FakeProvider("tavily", "search"))
    reg.activate("search", "tavily")
    chosen = await reg.resolve("search")
    assert chosen is not None and chosen.name == "tavily"


async def test_unhealthy_active_falls_through_to_baseline(reg: CapabilityRegistry):
    reg.register(FakeProvider("ha_push", "approval", healthy=False))
    reg.register(FakeProvider("inbox", "approval"))
    reg.activate("approval", "ha_push")
    chosen = await reg.resolve("approval")
    assert chosen is not None and chosen.name == "inbox"


async def test_safe_noop_no_provider_returns_none(reg: CapabilityRegistry):
    assert await reg.resolve("search") is None


def test_validate_boot_raises_when_hard_required_unfilled(reg: CapabilityRegistry):
    with pytest.raises(RuntimeError, match="llm"):
        reg.validate_boot()


async def test_baseline_equals_unhealthy_active_returns_none(reg: CapabilityRegistry):
    # approval slot's baseline is "inbox"; if inbox itself is active AND unhealthy,
    # the self-baseline guard must return None (not the failed provider).
    reg.register(FakeProvider("inbox", "approval", healthy=False))
    reg.activate("approval", "inbox")
    assert await reg.resolve("approval") is None


async def test_auto_selects_lowest_trust_tier_when_no_active(reg: CapabilityRegistry):
    reg.register(FakeProvider("hi", "search", tier="t5"))
    reg.register(FakeProvider("lo", "search", tier="t0"))
    chosen = await reg.resolve("search")  # no activate() — auto-select by trust tier
    assert chosen is not None and chosen.name == "lo"


def test_validate_boot_passes_when_hard_required_has_provider(reg: CapabilityRegistry):
    reg.register(FakeProvider("litellm", "llm"))
    reg.validate_boot()  # must not raise


def test_validate_boot_raises_when_hard_required_disabled(reg: CapabilityRegistry):
    reg.register(FakeProvider("litellm", "llm"))
    reg.set_enabled("llm", False)
    with pytest.raises(RuntimeError, match="disabled"):
        reg.validate_boot()
