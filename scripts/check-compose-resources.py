#!/usr/bin/env python3
"""Reject Compose services without bounded, enforceable host resources (#862).

The supported Docker/Podman Compose profiles use service-level ``mem_limit``,
``memswap_limit``, ``pids_limit`` and ``cpus``.  ``deploy.resources`` is not
used here: it is a Swarm deployment key and is ignored by ordinary Compose.
This gate checks the concrete profiles and add-on fragments that this
repository ships, including test profiles so a copied profile cannot silently
lose its containment contract.
"""

from __future__ import annotations

import argparse
import math
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

# Overlays repeat the limits from their base file so they remain safe when
# reviewed or rendered separately. Every standalone service file and supported
# add-on is listed so adding a new profile is a deliberate policy change.
COMPOSE_RELATIVE_FILES = (
    Path("docker-compose.yml"),
    Path("docker-compose.pm-poc.yml"),
    Path("docker-compose.docker-sock.override.example.yml"),
    Path("deploy/docker-compose.prod.yml"),
    Path("packages/hive-conductor/docker-compose.yml"),
    Path("packages/hive-conductor/docker-compose.test.yml"),
    Path("packages/hive-conductor/compose/fragments/phoenix.yml"),
    Path("packages/maistro-canvas/frontend/docker-compose.yml"),
)
COMPOSE_FILES = tuple(ROOT / relative for relative in COMPOSE_RELATIVE_FILES)


# Values are intentionally finite.  The lower bounds prevent a profile from
# becoming unusable, while the upper bounds are the security containment
# ceiling.  Performance tuning belongs to host sizing and orchestration, not
# to weakening this policy.
@dataclass(frozen=True)
class ResourcePolicy:
    memory_min: int
    memory_max: int
    pids_min: int
    pids_max: int
    cpus_min: float
    cpus_max: float


MiB = 1024 * 1024
GiB = 1024 * MiB
DEFAULT_POLICY = ResourcePolicy(128 * MiB, 8 * GiB, 32, 2048, 0.1, 8.0)
SERVICE_POLICIES: dict[str, ResourcePolicy] = {
    "maistro-engine": ResourcePolicy(512 * MiB, 4 * GiB, 128, 1024, 0.25, 4.0),
    "maistro-server-1": ResourcePolicy(512 * MiB, 4 * GiB, 128, 1024, 0.25, 4.0),
    "maistro-server-2": ResourcePolicy(512 * MiB, 4 * GiB, 128, 1024, 0.25, 4.0),
    "hive-conductor": ResourcePolicy(256 * MiB, 2 * GiB, 64, 512, 0.1, 2.0),
    "hive": ResourcePolicy(256 * MiB, 2 * GiB, 64, 512, 0.1, 2.0),
    "postgres": ResourcePolicy(512 * MiB, 4 * GiB, 128, 1024, 0.25, 4.0),
    "postgres-primary": ResourcePolicy(512 * MiB, 4 * GiB, 128, 1024, 0.25, 4.0),
    "postgres-replica": ResourcePolicy(512 * MiB, 4 * GiB, 128, 1024, 0.25, 4.0),
    "postgres-layout-check": ResourcePolicy(128 * MiB, 512 * MiB, 32, 128, 0.05, 0.5),
    "redis": ResourcePolicy(128 * MiB, 1 * GiB, 64, 512, 0.1, 1.0),
    "litellm": ResourcePolicy(256 * MiB, 2 * GiB, 64, 512, 0.1, 2.0),
    "langfuse": ResourcePolicy(256 * MiB, 2 * GiB, 128, 512, 0.1, 2.0),
    "lb": ResourcePolicy(64 * MiB, 512 * MiB, 32, 256, 0.05, 1.0),
    "phoenix": ResourcePolicy(128 * MiB, 1 * GiB, 32, 256, 0.1, 1.0),
}

_MEMORY_RE = re.compile(r"^([0-9]+(?:\.[0-9]+)?)\s*([kmgtpe](?:i?b)?|b)?$", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    path: str
    service: str
    message: str

    def render(self) -> str:
        return f"{self.path}: service {self.service!r}: {self.message}"


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def parse_memory(value: object) -> int | None:
    """Return bytes for a finite Compose memory value, or ``None``."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if math.isfinite(value) and value > 0 else None
    if not isinstance(value, str):
        return None
    match = _MEMORY_RE.fullmatch(value.strip())
    if match is None:
        return None
    amount = float(match.group(1))
    unit = (match.group(2) or "b").lower()
    multipliers = {
        "b": 1,
        "k": 1000,
        "kb": 1000,
        "ki": 1024,
        "kib": 1024,
        "m": 1000**2,
        "mb": 1000**2,
        "mi": MiB,
        "mib": MiB,
        "g": 1000**3,
        "gb": 1000**3,
        "gi": GiB,
        "gib": GiB,
        "t": 1000**4,
        "tb": 1000**4,
        "ti": 1024**4,
        "tib": 1024**4,
        "p": 1000**5,
        "pb": 1000**5,
        "pi": 1024**5,
        "pib": 1024**5,
        "e": 1000**6,
        "eb": 1000**6,
        "ei": 1024**6,
        "eib": 1024**6,
    }
    multiplier = multipliers.get(unit)
    if multiplier is None:
        return None
    result = amount * multiplier
    return int(result) if math.isfinite(result) and result > 0 else None


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _integer(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 and float(value) == number else None


def _policy_for(service: str) -> ResourcePolicy:
    return SERVICE_POLICIES.get(service, DEFAULT_POLICY)


def _check_service(name: str, raw_service: object, path: Path) -> list[Finding]:
    if not isinstance(raw_service, dict):
        return [Finding(_display(path), name, "is not a service mapping")]
    policy = _policy_for(name)
    memory = parse_memory(raw_service.get("mem_limit"))
    swap = parse_memory(raw_service.get("memswap_limit"))
    pids = _integer(raw_service.get("pids_limit"))
    cpus = _finite_number(raw_service.get("cpus"))
    values = (
        ("mem_limit", memory, policy.memory_min, policy.memory_max),
        ("memswap_limit", swap, policy.memory_min, policy.memory_max),
        ("pids_limit", pids, policy.pids_min, policy.pids_max),
        ("cpus", cpus, policy.cpus_min, policy.cpus_max),
    )
    failures: list[Finding] = []
    for key, value, minimum, maximum in values:
        if value is None:
            failures.append(
                Finding(
                    _display(path),
                    name,
                    f"{key} must be a finite, positive service-level limit",
                )
            )
        elif value < minimum or value > maximum:
            failures.append(
                Finding(
                    _display(path),
                    name,
                    f"{key}={value!r} is outside the safety policy [{minimum}, {maximum}]",
                )
            )
    if memory is not None and swap is not None and swap != memory:
        failures.append(
            Finding(
                _display(path),
                name,
                "memswap_limit must equal mem_limit so swap cannot extend the ceiling",
            )
        )
    deploy = raw_service.get("deploy")
    if isinstance(deploy, dict) and isinstance(deploy.get("resources"), dict):
        failures.append(
            Finding(
                _display(path),
                name,
                "must use service-level limits; deploy.resources is ignored by Compose",
            )
        )
    return failures


def check_document(document: object, path: Path) -> list[Finding]:
    if not isinstance(document, dict):
        return [Finding(_display(path), "<document>", "is not a YAML mapping")]
    services = document.get("services")
    if not isinstance(services, dict):
        return []
    failures: list[Finding] = []
    for name, raw_service in services.items():
        if isinstance(name, str):
            failures.extend(_check_service(name, raw_service, path))
    return failures


def audit(paths: tuple[Path, ...] = COMPOSE_FILES) -> list[Finding]:
    failures: list[Finding] = []
    for path in paths:
        if not path.is_file():
            failures.append(Finding(_display(path), "<file>", "supported profile is missing"))
            continue
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            failures.append(Finding(_display(path), "<document>", f"is not valid YAML: {exc}"))
            continue
        failures.extend(check_document(document, path))
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    paths = tuple(args.root / relative for relative in COMPOSE_RELATIVE_FILES)
    failures = audit(paths)
    if failures:
        print(f"FAIL: {len(failures)} Compose resource policy violation(s)")
        for failure in failures:
            print(f"  {failure.render()}")
        return 1
    print(f"OK: {len(paths)} supported Compose profiles have bounded memory, PID, and CPU limits")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
