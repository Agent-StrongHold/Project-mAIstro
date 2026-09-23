"""Effective cgroup v2 container ceilings are read from a real cgroup tree."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from maistro.security.container_limits import (
    EffectiveContainerLimits,
    read_effective_container_limits,
)


def _cgroup(root: Path, **files: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (root / name.replace("_", ".")).write_text(content)
    return root


def test_parses_bounded_and_unbounded_ceilings(tmp_path: Path) -> None:
    root = _cgroup(
        tmp_path / "cgroup",
        memory_max="536870912\n",
        pids_max="max\n",
        cpu_max="200000 100000\n",
    )

    limits = read_effective_container_limits(root)

    assert limits == EffectiveContainerLimits(
        memory_max_bytes=512 * 1024 * 1024,
        pids_max="unbounded",
        cpu_max_cores=2.0,
    )
    assert limits.as_dict() == {
        "memory_max_bytes": 536870912,
        "pids_max": "unbounded",
        "cpu_max_cores": 2.0,
    }


def test_bounded_pids_and_unbounded_memory_and_cpu(tmp_path: Path) -> None:
    root = _cgroup(
        tmp_path / "cgroup",
        memory_max="max",
        pids_max="256",
        cpu_max="max 100000",
    )

    limits = read_effective_container_limits(root)

    assert limits.memory_max_bytes == "unbounded"
    assert limits.pids_max == 256
    assert limits.cpu_max_cores == "unbounded"


def test_fractional_cpu_quota(tmp_path: Path) -> None:
    root = _cgroup(tmp_path / "cgroup", cpu_max="50000 100000")

    assert read_effective_container_limits(root).cpu_max_cores == 0.5


def test_missing_hierarchy_reports_unknown(tmp_path: Path) -> None:
    limits = read_effective_container_limits(tmp_path / "no-cgroup-here")

    assert limits.as_dict() == {
        "memory_max_bytes": "unknown",
        "pids_max": "unknown",
        "cpu_max_cores": "unknown",
    }


def test_controller_file_absent_reports_unknown_for_that_ceiling(tmp_path: Path) -> None:
    root = _cgroup(tmp_path / "cgroup", memory_max="1073741824")

    limits = read_effective_container_limits(root)

    assert limits.memory_max_bytes == 1073741824
    assert limits.pids_max == "unknown"
    assert limits.cpu_max_cores == "unknown"


@pytest.mark.parametrize(
    ("memory_max", "pids_max", "cpu_max"),
    [
        ("lots", "many", "fast"),
        ("", "", ""),
        ("-1", "-5", "-100000 100000"),
        ("0x10", "1.5", "200000 0"),
        ("12 34", "7 8", "200000 100000 extra"),
        ("nan", "inf", "nan 100000"),
        ("\x00\xff", "\x00", "max max"),
        ("max 1", "max 1", "100000 -1"),
        ("1.5", "+5", "1" * 400 + " 1"),
    ],
)
def test_malformed_content_reports_unknown_without_raising(
    tmp_path: Path, memory_max: str, pids_max: str, cpu_max: str
) -> None:
    root = _cgroup(tmp_path / "cgroup", memory_max=memory_max, pids_max=pids_max, cpu_max=cpu_max)

    limits = read_effective_container_limits(root)

    assert limits.as_dict() == {
        "memory_max_bytes": "unknown",
        "pids_max": "unknown",
        "cpu_max_cores": "unknown",
    }


def test_unreadable_entry_reports_unknown(tmp_path: Path) -> None:
    root = tmp_path / "cgroup"
    (root / "memory.max").mkdir(parents=True)

    assert read_effective_container_limits(root).memory_max_bytes == "unknown"


def test_default_root_is_the_cgroup_v2_mount() -> None:
    default = inspect.signature(read_effective_container_limits).parameters["root"].default
    assert default == Path("/sys/fs/cgroup")
