"""SPEC-009: Hardware presets for Setup Wizard.

Defines resource presets for potato/laptop/desktop/beast hardware tiers.
Each preset constrains conductor subsystems (state DB, reactor, agents, etc.)
to fit within the hardware envelope.
"""

from __future__ import annotations

from typing import Any, assert_type

import pytest


@pytest.fixture()
def presets_module():
    from maistro.config.presets import HARDWARE_PRESETS, HardwarePreset, resolve_preset

    return HARDWARE_PRESETS, HardwarePreset, resolve_preset


class TestHardwarePresets:
    def test_all_four_tiers_defined(self, presets_module) -> None:
        HARDWARE_PRESETS, _, _ = presets_module
        assert set(HARDWARE_PRESETS.keys()) == {"potato", "laptop", "desktop", "beast"}

    def test_potato_is_minimal(self, presets_module) -> None:
        HARDWARE_PRESETS, _, _ = presets_module
        p = HARDWARE_PRESETS["potato"]
        assert p.max_vcpu <= 2
        assert p.max_memory_gb <= 2
        assert p.db_backend == "sqlite"
        assert p.networking == "local_only"
        assert p.max_agents == 1
        assert p.reactor_enabled is False
        assert p.gpu_available is False

    def test_laptop_moderate(self, presets_module) -> None:
        HARDWARE_PRESETS, _, _ = presets_module
        p = HARDWARE_PRESETS["laptop"]
        assert p.max_vcpu <= 8
        assert p.max_memory_gb <= 16
        assert p.db_backend == "sqlite"
        assert p.networking == "substrate"
        assert p.max_agents >= 2
        assert p.reactor_enabled is True
        assert p.gpu_available is False

    def test_desktop_powerful(self, presets_module) -> None:
        HARDWARE_PRESETS, _, _ = presets_module
        p = HARDWARE_PRESETS["desktop"]
        assert p.max_vcpu <= 16
        assert p.max_memory_gb <= 64
        assert p.db_backend == "postgresql"
        assert p.networking == "federation"
        assert p.max_agents >= 4
        assert p.reactor_enabled is True

    def test_beast_maxed(self, presets_module) -> None:
        HARDWARE_PRESETS, _, _ = presets_module
        p = HARDWARE_PRESETS["beast"]
        assert p.max_vcpu >= 32
        assert p.max_memory_gb >= 128
        assert p.db_backend == "postgresql"
        assert p.networking == "federation"
        assert p.max_agents >= 8
        assert p.reactor_enabled is True
        assert p.gpu_available is True

    def test_progression_increases_resources(self, presets_module) -> None:
        HARDWARE_PRESETS, _, _ = presets_module
        tiers = ["potato", "laptop", "desktop", "beast"]
        for i in range(len(tiers) - 1):
            lo = HARDWARE_PRESETS[tiers[i]]
            hi = HARDWARE_PRESETS[tiers[i + 1]]
            assert hi.max_vcpu >= lo.max_vcpu
            assert hi.max_memory_gb >= lo.max_memory_gb
            assert hi.max_agents >= lo.max_agents


class TestResolvePreset:
    def test_resolve_by_name(self, presets_module) -> None:
        _, _, resolve_preset = presets_module
        p = resolve_preset("laptop")
        assert p.name == "laptop"

    def test_resolve_invalid_defaults_to_laptop(self, presets_module) -> None:
        _, _, resolve_preset = presets_module
        p = resolve_preset("nonexistent")
        assert p.name == "laptop"

    def test_resolve_detects_ram(self, presets_module) -> None:
        _, _, resolve_preset = presets_module
        p = resolve_preset("auto", total_memory_gb=4)
        assert p.name == "laptop"

    def test_resolve_auto_beast(self, presets_module) -> None:
        _, _, resolve_preset = presets_module
        p = resolve_preset("auto", total_memory_gb=128)
        assert p.name == "beast"

    def test_resolve_auto_potato(self, presets_module) -> None:
        _, _, resolve_preset = presets_module
        p = resolve_preset("auto", total_memory_gb=1)
        assert p.name == "potato"

    def test_resolve_auto_desktop(self, presets_module) -> None:
        _, _, resolve_preset = presets_module
        p = resolve_preset("auto", total_memory_gb=32)
        assert p.name == "desktop"


class TestPresetToConfig:
    def test_preset_generates_state_config(self, presets_module) -> None:
        _, _, resolve_preset = presets_module
        p = resolve_preset("laptop")
        cfg = p.to_config()
        assert "conductor_state_db" in cfg
        assert "conductor_data_dir" in cfg

    def test_preset_config_includes_reactor_settings(self, presets_module) -> None:
        _, _, resolve_preset = presets_module
        p = resolve_preset("desktop")
        cfg = p.to_config()
        assert cfg["reactor_enabled"] is True

    def test_potato_disables_reactor_in_config(self, presets_module) -> None:
        _, _, resolve_preset = presets_module
        p = resolve_preset("potato")
        cfg = p.to_config()
        assert cfg["reactor_enabled"] is False

    def test_to_config_is_a_statically_known_method(self) -> None:
        # Regression: to_config used to be monkey-patched onto the class with a
        # ``# type: ignore[attr-defined]``, so it was invisible to the type
        # checker at every call site. It must be a real method on the class
        # whose return type mypy --strict statically infers as dict[str, Any].
        # Imported directly (not via the untyped fixture) so the type flows.
        from maistro.config.presets import HARDWARE_PRESETS, HardwarePreset

        assert "to_config" in vars(HardwarePreset)
        cfg = HARDWARE_PRESETS["laptop"].to_config()
        assert_type(cfg, dict[str, Any])
        assert set(cfg) == {
            "hardware_preset",
            "conductor_data_dir",
            "conductor_state_db",
            "db_backend",
            "reactor_enabled",
            "max_agents",
            "networking",
            "gpu_available",
        }
