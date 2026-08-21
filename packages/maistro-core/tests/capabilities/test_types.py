from __future__ import annotations

from maistro.capabilities.types import FallbackPolicy, ProviderHealth, SlotSpec, Unavailable


def test_slotspec_baseline_requires_provider_name():
    spec = SlotSpec(
        name="web_search", fallback_policy=FallbackPolicy.BASELINE, baseline_provider="ddg"
    )
    assert spec.baseline_provider == "ddg"


def test_unavailable_is_typed_result():
    u = Unavailable(slot="smart_home", reason="no provider enabled")
    assert u.slot == "smart_home"
    assert "no provider" in u.reason


def test_provider_health_defaults():
    assert ProviderHealth(healthy=True).detail == ""
