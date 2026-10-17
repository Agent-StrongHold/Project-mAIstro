"""The pressure soak driver must fail closed and prove containment (#862)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "soak-compose-pressure.py"
GiB = 1024 * 1024 * 1024


@pytest.fixture(scope="module")
def driver() -> Any:
    spec = importlib.util.spec_from_file_location("soak_compose_pressure", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_load_ceiling_reads_the_shipped_engine_profile(driver: Any) -> None:
    ceiling = driver.load_ceiling(ROOT / "docker-compose.yml", "maistro-engine")

    assert ceiling == driver.Ceiling(2 * GiB, 2 * GiB, 512, 2.0)


def test_load_ceiling_fails_closed_when_limits_missing_or_unbounded(
    driver: Any, tmp_path: Path
) -> None:
    profile = tmp_path / "compose.yml"
    profile.write_text(
        yaml.safe_dump(
            {
                "services": {
                    "engine": {"image": "example/engine"},
                    "unbounded": {
                        "mem_limit": "unlimited",
                        "memswap_limit": "4g",
                        "pids_limit": 0,
                        "cpus": 0,
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(driver.PolicyError, match="engine"):
        driver.load_ceiling(profile, "engine")
    with pytest.raises(driver.PolicyError, match="out of policy"):
        driver.load_ceiling(profile, "unbounded")
    with pytest.raises(driver.PolicyError, match="not found"):
        driver.load_ceiling(profile, "absent")


def test_docker_run_args_replay_the_profile_ceiling(driver: Any) -> None:
    ceiling = driver.Ceiling(2 * GiB, 2 * GiB, 512, 2.0)

    args = driver.docker_run_args(
        "maistro-soak-check",
        ceiling,
        "python:3.12-alpine",
        ["python", "-c", "pass"],
        restart="on-failure",
        detach=True,
        rm=True,
    )

    assert args[:2] == ["docker", "run"]
    # Flags must precede the image so the daemon actually applies them.
    image_index = args.index("python:3.12-alpine")
    assert "--memory" in args[:image_index]
    assert args[args.index("--memory") + 1] == str(2 * GiB)
    assert args[args.index("--memory-swap") + 1] == str(2 * GiB)
    assert args[args.index("--pids-limit") + 1] == "512"
    assert args[args.index("--cpus") + 1] == "2.0"
    assert args[args.index("--restart") + 1] == "on-failure"
    assert "-d" in args[:image_index] and "--rm" in args[:image_index]
    # Fractional CPU quotas must not lose their nano-CPU precision.
    applied = driver.applied_matches_profile(
        {
            "Memory": 512 * 1024 * 1024,
            "MemorySwap": 512 * 1024 * 1024,
            "PidsLimit": 128,
            "NanoCpus": 50_000_000,
        },
        driver.Ceiling(512 * 1024 * 1024, 512 * 1024 * 1024, 128, 0.05),
    )
    assert applied


def test_parse_spawned_reads_the_fork_count(driver: Any) -> None:
    assert driver.parse_spawned("noise\nSPAWNED 511\n") == 511
    assert driver.parse_spawned("SPAWNED 0") == 0
    assert driver.parse_spawned("python: can't fork\n") is None
    assert driver.parse_spawned("SPAWNED many") is None


def test_evaluate_flags_containment_failures(driver: Any) -> None:
    ceiling = driver.Ceiling(2 * GiB, 2 * GiB, 512, 2.0)

    proven = driver.PressureResult(
        oom_killed=True,
        exit_code=137,
        restart_count=1,
        spawned=510,
        host_pid_delta=4,
        applied_matches_profile=True,
        daemon_responsive=True,
    )
    assert driver.evaluate(proven, ceiling) == []

    leaked = driver.PressureResult(
        oom_killed=False,
        exit_code=0,
        restart_count=0,
        spawned=driver.SPAWN_ATTEMPTS,
        host_pid_delta=driver.SPAWN_ATTEMPTS,
        applied_matches_profile=False,
        daemon_responsive=False,
    )
    failures = driver.evaluate(leaked, ceiling)
    assert any("OOM" in failure for failure in failures)
    assert any("restart" in failure for failure in failures)
    assert any("attempt bound" in failure for failure in failures)
    assert any("leaked" in failure for failure in failures)
    assert any("ceiling verbatim" in failure for failure in failures)
    assert any("daemon" in failure for failure in failures)

    starved = driver.PressureResult(
        oom_killed=True,
        exit_code=137,
        restart_count=1,
        spawned=7,
        host_pid_delta=1,
        applied_matches_profile=True,
        daemon_responsive=True,
    )
    assert any("binding constraint" in failure for failure in driver.evaluate(starved, ceiling))
