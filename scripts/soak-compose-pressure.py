#!/usr/bin/env python3
"""Drive a real memory/PID pressure case under a shipped profile ceiling (#862).

The release soak (#860) must prove that a runaway service is contained by the
Compose resource policy and that the host survives the breach. This driver
makes that case repeatable instead of narrative: it reads the containment
ceiling of a service from a shipped Compose profile (failing closed when the
profile is out of policy), replays that exact ceiling onto a disposable
container on the real Docker/Podman daemon, then

* drives memory pressure until the cgroup kills the container and records
  ``OOMKilled`` plus the exit code,
* restarts under ``--restart on-failure`` and records that the policy
  recreates the killed container, and
* drives PID fan-out until the fork budget is exhausted and records the
  contained spawn count.

It also verifies the daemon applied the profile ceiling verbatim
(``--memory/--memory-swap/--pids-limit/--cpus``) and that the host's process
count and the Docker daemon stayed healthy. Evidence is printed as JSON and
can be saved with ``--output`` for the release soak record.

Exit codes: ``0`` containment proven, ``1`` policy or containment failure,
``77`` no Docker/Podman daemon (skipped, not failed).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
GATE_SCRIPT = ROOT / "scripts" / "check-compose-resources.py"
DEFAULT_PROFILE = ROOT / "docker-compose.yml"
DEFAULT_SERVICE = "maistro-engine"
DEFAULT_IMAGE = "python:3.12-alpine"

#: Upper bound on PID fan-out attempts; the pids cgroup controller must stop
#: the tree well before this number for the phase to pass.
SPAWN_ATTEMPTS = 4000
#: Headroom between the observed spawn count and the pids ceiling (PID 1 and
#: a few runtime processes also live in the cgroup).
SPAWN_SLACK = 32
#: A contained run must not move the host process count by anything close to
#: the attempted fan-out.
HOST_PID_DELTA_MAX = SPAWN_ATTEMPTS // 2
POLL_SECONDS = 120

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_SKIP = 77

MEM_KILL_CONTAINER = "maistro-soak-mem-kill"
MEM_RESTART_CONTAINER = "maistro-soak-mem-restart"
PIDS_CONTAINER = "maistro-soak-pids"

MEMORY_HOG = "b = []\nwhile True:\n    b.append(b'x' * 8 * 1024 * 1024)"
FORK_BOMB = (
    "import subprocess\n"
    "n = 0\n"
    "try:\n"
    f"    for _ in range({SPAWN_ATTEMPTS}):\n"
    "        subprocess.Popen(['sleep', '300'])\n"
    "        n += 1\n"
    "except OSError:\n"
    "    pass\n"
    "print(f'SPAWNED {n}')\n"
)


class PolicyError(Exception):
    """The requested service does not carry a finite, in-policy ceiling."""


@dataclass(frozen=True)
class Ceiling:
    """The four enforceable containment values replayed onto the daemon."""

    memory_bytes: int
    swap_bytes: int
    pids_limit: int
    cpus: float


@dataclass(frozen=True)
class PressureResult:
    """Evidence collected from the three pressure phases."""

    oom_killed: bool
    exit_code: int | None
    restart_count: int
    spawned: int | None
    host_pid_delta: int | None
    applied_matches_profile: bool
    daemon_responsive: bool


def _load_gate() -> Any:
    spec = importlib.util.spec_from_file_location("check_compose_resources", GATE_SCRIPT)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging failure
        raise PolicyError(f"cannot load gate module from {GATE_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_ceiling(profile: Path, service: str) -> Ceiling:
    """Return the enforceable ceiling of ``service`` or fail closed.

    Reuses the CI gate's parser and safety policy so the soak driver refuses
    to certify a profile whose limits are missing, unbounded, or outside the
    declared safety ranges.
    """
    gate = _load_gate()
    if not profile.is_file():
        raise PolicyError(f"profile {profile} does not exist")
    document = yaml.safe_load(profile.read_text(encoding="utf-8"))
    services = document.get("services", {}) if isinstance(document, dict) else {}
    raw = services.get(service)
    if not isinstance(raw, dict):
        raise PolicyError(f"{profile}: service {service!r} not found")
    findings = [finding.render() for finding in gate._check_service(service, raw, profile)]
    if findings:
        raise PolicyError(f"{profile}: {service} is out of policy: " + "; ".join(findings))
    memory = gate.parse_memory(raw.get("mem_limit"))
    swap = gate.parse_memory(raw.get("memswap_limit"))
    pids = gate._integer(raw.get("pids_limit"))
    cpus = gate._finite_number(raw.get("cpus"))
    assert memory and swap and pids and cpus  # guaranteed by the gate check above
    return Ceiling(memory_bytes=memory, swap_bytes=swap, pids_limit=pids, cpus=cpus)


def docker_run_args(
    name: str,
    ceiling: Ceiling,
    image: str,
    command: list[str],
    *,
    restart: str | None = None,
    detach: bool = False,
    rm: bool = False,
) -> list[str]:
    """Build the ``docker run`` invocation that replays the profile ceiling."""
    args = [
        "docker",
        "run",
        "--name",
        name,
        "--label",
        "maistro.soak-pressure=true",
        "--memory",
        str(ceiling.memory_bytes),
        "--memory-swap",
        str(ceiling.swap_bytes),
        "--pids-limit",
        str(ceiling.pids_limit),
        "--cpus",
        str(ceiling.cpus),
    ]
    if restart is not None:
        args += ["--restart", restart]
    if detach:
        args.append("-d")
    if rm:
        args.append("--rm")
    args.append(image)
    return args + command


def parse_spawned(log: str) -> int | None:
    """Return the successful fork count reported by the fan-out phase."""
    for line in reversed(log.splitlines()):
        stripped = line.strip()
        if stripped.startswith("SPAWNED "):
            digits = stripped.removeprefix("SPAWNED ")
            if digits.isdigit():
                return int(digits)
    return None


def applied_matches_profile(host_config: dict[str, Any], ceiling: Ceiling) -> bool:
    """Confirm the daemon applied the ceiling verbatim, not approximately."""
    return (
        host_config.get("Memory") == ceiling.memory_bytes
        and host_config.get("MemorySwap") == ceiling.swap_bytes
        and host_config.get("PidsLimit") == ceiling.pids_limit
        and host_config.get("NanoCpus") == round(ceiling.cpus * 1_000_000_000)
    )


def evaluate(result: PressureResult, ceiling: Ceiling) -> list[str]:
    """Return containment failures; an empty list means the case is proven."""
    failures: list[str] = []
    if not result.applied_matches_profile:
        failures.append("daemon did not apply the profile ceiling verbatim")
    if not result.oom_killed:
        failures.append("memory pressure did not produce a contained OOM kill")
    if result.exit_code != 137:
        failures.append(f"memory hog exited with {result.exit_code}, expected kill signal (137)")
    if result.restart_count < 1:
        failures.append("restart policy did not recreate the killed container")
    if result.spawned is None:
        failures.append("PID fan-out phase produced no spawn count")
    else:
        if result.spawned >= SPAWN_ATTEMPTS:
            failures.append(
                f"PID fan-out reached the attempt bound ({result.spawned}); the ceiling did not bind"
            )
        elif result.spawned < ceiling.pids_limit - SPAWN_SLACK:
            failures.append(
                f"only {result.spawned} processes spawned under a pids ceiling of "
                f"{ceiling.pids_limit}; the ceiling was not the binding constraint"
            )
    if result.host_pid_delta is not None and result.host_pid_delta >= HOST_PID_DELTA_MAX:
        failures.append(f"host process count moved by {result.host_pid_delta}; containment leaked")
    if not result.daemon_responsive:
        failures.append("Docker daemon stopped responding after pressure")
    return failures


def _run(cmd: list[str], *, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def _inspect(name: str) -> list[dict[str, Any]]:
    completed = _run(["docker", "inspect", name])
    if completed.returncode != 0:
        return []
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        return []


def _inspect_state(name: str) -> dict[str, Any]:
    entries = _inspect(name)
    if not entries:
        return {}
    state = entries[0].get("State", {})
    return state if isinstance(state, dict) else {}


def _restart_count(name: str) -> int:
    """Read ``RestartCount``; it is a container-level field, not in ``State``."""
    entries = _inspect(name)
    if not entries:
        return 0
    count = entries[0].get("RestartCount", 0)
    return int(count) if isinstance(count, (int, float)) else 0


def _inspect_host_config(name: str) -> dict[str, Any]:
    entries = _inspect(name)
    if not entries:
        return {}
    host_config = entries[0].get("HostConfig", {})
    return host_config if isinstance(host_config, dict) else {}


def host_pid_count() -> int | None:
    """Count host processes from ``/proc``; ``None`` where unavailable."""
    proc = Path("/proc")
    if not proc.is_dir():
        return None
    return sum(1 for entry in proc.iterdir() if entry.name.isdigit())


def docker_version() -> str | None:
    completed = _run(["docker", "version", "--format", "{{.Server.Version}}"], timeout=60)
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def _force_remove(name: str) -> None:
    _run(["docker", "rm", "-f", name], timeout=60)


def memory_kill_phase(ceiling: Ceiling, image: str) -> dict[str, Any]:
    """Run the hog until the cgroup kills it; return the kill evidence."""
    _force_remove(MEM_KILL_CONTAINER)
    started = _run(
        docker_run_args(
            MEM_KILL_CONTAINER,
            ceiling,
            image,
            ["python", "-c", MEMORY_HOG],
            detach=True,
        )
    )
    if started.returncode != 0:
        return {"error": started.stderr.strip() or "docker run failed"}
    applied = applied_matches_profile(_inspect_host_config(MEM_KILL_CONTAINER), ceiling)
    deadline = time.monotonic() + POLL_SECONDS
    state: dict[str, Any] = {}
    while time.monotonic() < deadline:
        state = _inspect_state(MEM_KILL_CONTAINER)
        if state.get("Running") is False and state.get("Status") != "created":
            break
        time.sleep(1)
    _force_remove(MEM_KILL_CONTAINER)
    return {
        "container": MEM_KILL_CONTAINER,
        "oom_killed": bool(state.get("OOMKilled")),
        "exit_code": state.get("ExitCode"),
        "applied_matches_profile": applied,
    }


def memory_restart_phase(ceiling: Ceiling, image: str) -> dict[str, Any]:
    """Prove the restart policy recreates a container killed for OOM."""
    _force_remove(MEM_RESTART_CONTAINER)
    started = _run(
        docker_run_args(
            MEM_RESTART_CONTAINER,
            ceiling,
            image,
            ["python", "-c", MEMORY_HOG],
            detach=True,
            restart="on-failure",
        )
    )
    if started.returncode != 0:
        return {"error": started.stderr.strip() or "docker run failed"}
    deadline = time.monotonic() + POLL_SECONDS
    restart_count = 0
    running = False
    oom_observed = False
    while time.monotonic() < deadline:
        state = _inspect_state(MEM_RESTART_CONTAINER)
        restart_count = _restart_count(MEM_RESTART_CONTAINER)
        running = bool(state.get("Running"))
        oom_observed = oom_observed or bool(state.get("OOMKilled"))
        if restart_count >= 1 and running:
            break
        time.sleep(1)
    _force_remove(MEM_RESTART_CONTAINER)
    return {
        "container": MEM_RESTART_CONTAINER,
        "restart_count": restart_count,
        "running_after_restart": running,
        "oom_killed": oom_observed,
    }


def pid_fanout_phase(ceiling: Ceiling, image: str) -> dict[str, Any]:
    """Attempt to exceed the fork budget; return the contained spawn count."""
    _force_remove(PIDS_CONTAINER)
    completed = _run(
        docker_run_args(
            PIDS_CONTAINER,
            ceiling,
            image,
            ["python", "-c", FORK_BOMB],
            rm=True,
        ),
        timeout=300,
    )
    spawned = parse_spawned(completed.stdout)
    return {
        "container": PIDS_CONTAINER,
        "spawned": spawned,
        "attempts": SPAWN_ATTEMPTS,
        "exit_code": completed.returncode,
        "stdout_tail": completed.stdout.strip().splitlines()[-1:] if completed.stdout else [],
    }


def build_result(
    mem_kill: dict[str, Any],
    mem_restart: dict[str, Any],
    fanout: dict[str, Any],
    host_pid_delta: int | None,
    daemon_responsive: bool,
) -> PressureResult:
    return PressureResult(
        oom_killed=bool(mem_kill.get("oom_killed")),
        exit_code=mem_kill.get("exit_code"),
        restart_count=int(mem_restart.get("restart_count", 0) or 0),
        spawned=fanout.get("spawned"),
        host_pid_delta=host_pid_delta,
        applied_matches_profile=bool(mem_kill.get("applied_matches_profile")),
        daemon_responsive=daemon_responsive,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--service", default=DEFAULT_SERVICE)
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--output", type=Path, default=None, help="write evidence JSON here")
    args = parser.parse_args(argv)

    version = docker_version()
    if version is None:
        print(
            json.dumps(
                {
                    "result": "skipped",
                    "reason": "no Docker/Podman daemon reachable; pressure case not run",
                }
            )
        )
        return EXIT_SKIP

    try:
        ceiling = load_ceiling(args.profile.resolve(), args.service)
    except PolicyError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return EXIT_FAIL

    if _run(["docker", "image", "inspect", args.image]).returncode != 0:
        pulled = _run(["docker", "pull", args.image], timeout=600)
        if pulled.returncode != 0:
            print(f"FAIL: cannot obtain pressure image {args.image}: {pulled.stderr.strip()}")
            return EXIT_FAIL

    record: dict[str, Any] = {
        "profile": str(args.profile),
        "service": args.service,
        "image": args.image,
        "docker_server_version": version,
        "ceiling": {
            "memory_bytes": ceiling.memory_bytes,
            "memory_swap_bytes": ceiling.swap_bytes,
            "pids_limit": ceiling.pids_limit,
            "cpus": ceiling.cpus,
        },
    }

    host_pids_start = host_pid_count()
    try:
        record["memory_kill"] = memory_kill_phase(ceiling, args.image)
        record["memory_restart"] = memory_restart_phase(ceiling, args.image)
        record["pid_fanout"] = pid_fanout_phase(ceiling, args.image)
    finally:
        for name in (MEM_KILL_CONTAINER, MEM_RESTART_CONTAINER, PIDS_CONTAINER):
            _force_remove(name)
    host_pids_end = host_pid_count()
    record["host_pid_count"] = {"start": host_pids_start, "end": host_pids_end}
    host_delta = (
        abs(host_pids_end - host_pids_start)
        if host_pids_start is not None and host_pids_end is not None
        else None
    )

    daemon_responsive = docker_version() is not None
    record["daemon_responsive_after_pressure"] = daemon_responsive

    result = build_result(
        record["memory_kill"],
        record["memory_restart"],
        record["pid_fanout"],
        host_delta,
        daemon_responsive,
    )
    failures = evaluate(result, ceiling)
    record["failures"] = failures
    record["result"] = "contained" if not failures else "containment-failure"

    print(json.dumps(record, indent=2, sort_keys=True))
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    if record["failures"]:
        print("FAIL: pressure case was not contained:", file=sys.stderr)
        for failure in record["failures"]:
            print(f"  - {failure}", file=sys.stderr)
        return EXIT_FAIL
    print("OK: pressure case contained; evidence recorded above", file=sys.stderr)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
