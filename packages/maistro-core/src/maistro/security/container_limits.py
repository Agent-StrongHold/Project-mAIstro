"""Effective container ceilings as the kernel enforces them (cgroup v2).

Application floors (`resource_policy.py`) say what the engine will accept;
these values say what the deployment actually granted the process. Reading
them at runtime lets an operator see when a container profile left memory,
PIDs or CPU unbounded. This module only observes: it never decides readiness.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

CGROUP_V2_ROOT = Path("/sys/fs/cgroup")

Unbounded = Literal["unbounded"]
Unknown = Literal["unknown"]
UNBOUNDED: Unbounded = "unbounded"
UNKNOWN: Unknown = "unknown"


@dataclass(frozen=True)
class EffectiveContainerLimits:
    """Ceilings from `memory.max`, `pids.max` and `cpu.max`."""

    memory_max_bytes: int | Unbounded | Unknown
    pids_max: int | Unbounded | Unknown
    cpu_max_cores: float | Unbounded | Unknown

    def as_dict(self) -> dict[str, int | float | str]:
        return {
            "memory_max_bytes": self.memory_max_bytes,
            "pids_max": self.pids_max,
            "cpu_max_cores": self.cpu_max_cores,
        }


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except (OSError, ValueError):
        return None


def _count(raw: str) -> int | None:
    # int() also accepts "+5", "1_000" and surrounding whitespace; the kernel
    # never writes those, so anything but plain digits is treated as corrupt.
    return int(raw) if raw.isascii() and raw.isdigit() else None


def _parse_count(raw: str | None) -> int | Unbounded | Unknown:
    if raw is None:
        return UNKNOWN
    if raw == "max":
        return UNBOUNDED
    value = _count(raw)
    return UNKNOWN if value is None else value


def _parse_cpu(raw: str | None) -> float | Unbounded | Unknown:
    parts = raw.split() if raw is not None else []
    if len(parts) != 2:
        return UNKNOWN
    quota, period = parts[0], _count(parts[1])
    if not period:
        return UNKNOWN
    if quota == "max":
        return UNBOUNDED
    value = _count(quota)
    if value is None:
        return UNKNOWN
    try:
        return value / period
    except OverflowError:
        return UNKNOWN


def read_effective_container_limits(root: Path = CGROUP_V2_ROOT) -> EffectiveContainerLimits:
    """Read this process's cgroup v2 ceilings; never raises.

    A missing hierarchy (cgroup v1, a non-Linux host, or a controller not
    delegated to this cgroup) reads as `unknown`, which is deliberately
    distinct from `unbounded`: only the latter proves the profile set no limit.
    """
    return EffectiveContainerLimits(
        memory_max_bytes=_parse_count(_read(root / "memory.max")),
        pids_max=_parse_count(_read(root / "pids.max")),
        cpu_max_cores=_parse_cpu(_read(root / "cpu.max")),
    )
