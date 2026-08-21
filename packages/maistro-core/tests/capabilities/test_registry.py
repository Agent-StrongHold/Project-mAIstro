from __future__ import annotations

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
