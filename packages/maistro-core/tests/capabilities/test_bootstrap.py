"""Canonical capability-slot bootstrap: the slots + baselines every engine gets (SPEC-184)."""

from __future__ import annotations

from importlib.metadata import EntryPoint

from maistro.capabilities.bootstrap import default_capability_registry
from maistro.capabilities.registry import CapabilityRegistry
from maistro.capabilities.tests_fakes import FakeProvider


def test_returns_a_capability_registry() -> None:
    assert isinstance(default_capability_registry(), CapabilityRegistry)


def test_defines_canonical_slots() -> None:
    reg = default_capability_registry()
    # The Phase-1b + self_repair slots must exist, enabled, per SPEC-184/188.
    assert reg.is_enabled("infra_monitor") is True
    assert reg.is_enabled("infra_action") is True
    assert reg.is_enabled("approval") is True
    assert reg.is_enabled("self_repair") is True


def test_self_repair_slot_has_no_core_provider() -> None:
    # self_repair is SAFE_NOOP: core defines the slot; the app supplies the
    # provider (it needs the app-wired infra_monitor/infra_action).
    reg = default_capability_registry()
    assert reg.installed("self_repair") == []


def test_approval_baseline_inbox_is_installed() -> None:
    reg = default_capability_registry()
    assert "inbox" in reg.installed("approval")


def test_infra_slots_have_no_provider_until_app_registers_one() -> None:
    # infra_* are SAFE_NOOP: core ships no baseline; the app registers the host-health provider.
    reg = default_capability_registry()
    assert reg.installed("infra_monitor") == []
    assert reg.installed("infra_action") == []


async def test_approval_resolves_to_inbox_baseline() -> None:
    reg = default_capability_registry()
    provider = await reg.resolve("approval")
    assert provider is not None
    assert provider.name == "inbox"


async def test_approval_disabled_still_falls_back_to_inbox_baseline() -> None:
    # approval is BASELINE policy: a disabled slot resolves to its baseline, not None.
    reg = default_capability_registry()
    reg.set_enabled("approval", False)
    provider = await reg.resolve("approval")
    assert provider is not None
    assert provider.name == "inbox"


def test_discovers_entry_point_providers() -> None:
    # An app/plugin can late-add a provider via the entry-point sweep without core changes.
    captured: dict[str, object] = {}

    def _factory() -> FakeProvider:
        return FakeProvider("plugin_infra", "infra_monitor")

    class _EP(EntryPoint):  # type: ignore[misc]
        def load(self) -> object:
            captured["loaded"] = True
            return _factory

    ep = _EP(name="plugin_infra", value="x:y", group="maistro.capabilities")
    reg = default_capability_registry(entry_points=[ep])
    assert "plugin_infra" in reg.installed("infra_monitor")
    assert captured.get("loaded") is True
