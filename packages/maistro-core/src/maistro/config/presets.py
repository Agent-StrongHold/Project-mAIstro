"""SPEC-009: Hardware presets for Setup Wizard.

Four tiers constrain conductor subsystems to fit the hardware envelope:

  potato  — Raspberry Pi / old laptop (1 vCPU, 1GB, SQLite, local-only)
  laptop  — Daily driver (2-4 vCPU, 4-8GB, SQLite, substrate networking)
  desktop — Gaming/workstation PC (4-8 vCPU, 16GB, PostgreSQL, federation)
  beast   — Production homelab (i9-13900K 32t, 125GB, PostgreSQL, full federation)
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class HardwarePreset(BaseModel):
    name: str
    label: str
    max_vcpu: int
    max_memory_gb: int
    db_backend: Literal["sqlite", "postgresql"]
    networking: Literal["local_only", "substrate", "federation"]
    gpu_available: bool
    reactor_enabled: bool
    max_agents: int
    description: str = ""

    def to_config(self) -> dict[str, Any]:
        """Render this preset as a conductor state-config dict."""
        return {
            "hardware_preset": self.name,
            "conductor_data_dir": "~/.conductor",
            "conductor_state_db": "~/.conductor/state.db",
            "db_backend": self.db_backend,
            "reactor_enabled": self.reactor_enabled,
            "max_agents": self.max_agents,
            "networking": self.networking,
            "gpu_available": self.gpu_available,
        }


HARDWARE_PRESETS: dict[str, HardwarePreset] = {
    "potato": HardwarePreset(
        name="potato",
        label="Potato",
        max_vcpu=2,
        max_memory_gb=2,
        db_backend="sqlite",
        networking="local_only",
        gpu_available=False,
        reactor_enabled=False,
        max_agents=1,
        description="Raspberry Pi or old laptop. Single agent, local-only, no reactor.",
    ),
    "laptop": HardwarePreset(
        name="laptop",
        label="Laptop",
        max_vcpu=8,
        max_memory_gb=16,
        db_backend="sqlite",
        networking="substrate",
        gpu_available=False,
        reactor_enabled=True,
        max_agents=4,
        description="Daily driver. SQLite, substrate networking, 4 agents.",
    ),
    "desktop": HardwarePreset(
        name="desktop",
        label="Desktop",
        max_vcpu=16,
        max_memory_gb=64,
        db_backend="postgresql",
        networking="federation",
        gpu_available=True,
        reactor_enabled=True,
        max_agents=8,
        description="Gaming/workstation PC. PostgreSQL, full federation, GPU optional.",
    ),
    "beast": HardwarePreset(
        name="beast",
        label="Beast",
        max_vcpu=32,
        max_memory_gb=128,
        db_backend="postgresql",
        networking="federation",
        gpu_available=True,
        reactor_enabled=True,
        max_agents=16,
        description="Production homelab. i9-13900K, 125GB RAM, P40 GPU, full federation.",
    ),
}

_RAM_THRESHOLDS = [
    (2, "potato"),
    (16, "laptop"),
    (64, "desktop"),
]


def resolve_preset(
    name: str = "laptop",
    total_memory_gb: float | None = None,
) -> HardwarePreset:
    if name != "auto":
        return HARDWARE_PRESETS.get(name, HARDWARE_PRESETS["laptop"])
    if total_memory_gb is not None:
        for threshold, tier in _RAM_THRESHOLDS:
            if total_memory_gb <= threshold:
                return HARDWARE_PRESETS[tier]
        return HARDWARE_PRESETS["beast"]
    return HARDWARE_PRESETS["laptop"]


def preset_to_config(preset: HardwarePreset) -> dict[str, Any]:
    return preset.to_config()
