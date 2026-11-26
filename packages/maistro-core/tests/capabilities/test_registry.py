from __future__ import annotations

from typing import cast

import pytest

from maistro.capabilities.registry import CapabilityRegistry
from maistro.capabilities.tests_fakes import FakeProvider
from maistro.capabilities.types import FallbackPolicy, SlotSpec


@pytest.fixture()
def registry() -> CapabilityRegistry:
    reg = CapabilityRegistry()
    reg.define(SlotSpec(name="web_search", fallback_policy=FallbackPolicy.SAFE_NOOP))
    return reg


def test_register_is_installed_but_inactive(registry: CapabilityRegistry):
    registry.register(FakeProvider("tavily", "web_search"))
    assert "tavily" in registry.installed("web_search")
    assert registry.active_name("web_search") is None


def test_activate_sets_active(registry: CapabilityRegistry):
    registry.register(FakeProvider("tavily", "web_search"))
    registry.activate("web_search", "tavily")
    assert registry.active_name("web_search") == "tavily"


def test_activate_unknown_provider_raises(registry: CapabilityRegistry):
    with pytest.raises(KeyError):
        registry.activate("web_search", "nope")


def test_register_to_undefined_slot_raises(registry: CapabilityRegistry):
    with pytest.raises(KeyError):
        registry.register(FakeProvider("x", "no_such_slot"))


def test_enabled_defaults_true_and_toggles(registry: CapabilityRegistry):
    assert registry.is_enabled("web_search") is True
    registry.set_enabled("web_search", False)
    assert registry.is_enabled("web_search") is False


def test_provider_returns_the_installed_instance(registry: CapabilityRegistry):
    p = FakeProvider("tavily", "web_search")
    registry.register(p)
    assert registry.provider("web_search", "tavily") is p


def test_provider_returns_none_for_unknown_provider(registry: CapabilityRegistry):
    assert registry.provider("web_search", "nope") is None


def test_provider_unknown_slot_raises(registry: CapabilityRegistry):
    with pytest.raises(KeyError):
        registry.provider("no_such_slot", "x")


def test_slots_lists_defined_slot_names(registry: CapabilityRegistry):
    registry.define(SlotSpec(name="approval", fallback_policy=FallbackPolicy.SAFE_NOOP))
    assert set(registry.slots()) == {"web_search", "approval"}


def test_host_supplied_tier_and_provenance_are_the_authority(registry: CapabilityRegistry):
    # Only the host states a tier and names where a provider came from; a
    # provider's own metadata never reaches this record.
    registry.register(
        FakeProvider("tavily", "web_search"), trust_tier="t1", provenance="ops://tavily"
    )
    assert registry.provider_trust("web_search", "tavily") == ("t1", "ops://tavily")


def test_host_tier_the_host_does_not_recognize_lands_on_the_unvetted_floor(
    registry: CapabilityRegistry,
):
    registry.register(FakeProvider("tavily", "web_search"), trust_tier="t9")
    assert registry.provider_trust("web_search", "tavily")[0] == "t3"


def test_malformed_declared_tier_is_kept_verbatim_not_laundered(registry: CapabilityRegistry):
    # A declaration the host cannot read is evidence, not a promotion: it is
    # kept as declared, so the refusal stays visible instead of becoming a
    # usable tier.
    registry.register(FakeProvider("tavily", "web_search", tier=""))
    assert registry.provider_trust("web_search", "tavily")[0] == ""


def test_non_string_declared_tier_is_not_laundered_into_a_usable_tier(
    registry: CapabilityRegistry,
):
    # The built-in provider shape with a tier that is not a string at all:
    # metadata of an unknown shape is refused, never rounded to a tier.
    registry.register(FakeProvider("tavily", "web_search", tier=cast(str, None)))
    assert registry.provider_trust("web_search", "tavily")[0] == ""


async def test_missing_baseline_provider_resolves_to_none() -> None:
    # The declared baseline is a provider name, not a promise that the
    # provider is installed: an absent one is a typed absence, never a crash
    # and never a different provider in its place.
    registry = CapabilityRegistry()
    registry.define(
        SlotSpec(
            name="approval", fallback_policy=FallbackPolicy.BASELINE, baseline_provider="inbox"
        )
    )
    registry.register(FakeProvider("push", "approval", healthy=False))
    assert await registry.resolve("approval") is None
