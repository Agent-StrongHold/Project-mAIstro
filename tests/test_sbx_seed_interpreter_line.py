"""The sbx-tests seed's base interpreter must be a line the lock can serve.

The failure this prevents is the #2136/#2376 class: Dependabot jumps the
`deploy/sbx/template/Dockerfile.tests` base from the pinned CPython line to the
newest published one, the digest is real, the registry row is the only thing
the image-pins gate complains about — and the image itself is unbuildable,
because the seed's `uv sync --frozen --no-install-workspace` (#351 removed the
`|| true` that used to mask exactly this) needs a cpNNN binary wheel for every
selected compiled distribution and the seed image installs no C compiler to
build sdists from. #2136 evaluated the 3.15 jump for the engine images and
rejected it on this wheel ceiling ("no coincurve release ships cp315 wheels");
#2376 re-raised the same jump for the sbx-tests image, and the ceiling was
re-verified empirically on 2026-11-18: with psycopg-binary raised to a
cp315-wheel release the sync still fails closed (cffi 2.0.0 falls back to its
sdist and needs libffi headers), and coincurve 21.0.0 remains the latest
upstream release without cp315 wheels.

This module holds that contract closed statically, without Docker, uv or
network: parse the FROM line's CPython minor, then walk every registry entry in
`uv.lock` whose environment marker is satisfiable on linux/cpNNN and assert
each ships a binary artifact installable there — a linux (or any-platform)
wheel tagged for cpNNN, an abi3 wheel whose floor is at or below cpNNN, or a
pure-Python wheel (installable on any line). A package that has linux wheels
for other lines but none for the base's line is exactly the distribution the
next Dependabot bump would fail on, so the failure names them all and points at
the disposition record.

The check is deliberately narrower than "the lock is universal": entries with
no linux wheels at all (sdist-only publishes such as crcmod) are outside this
contract — they are either not selected by the seed sync or already require a
source build on every line, which is a pre-existing condition this module does
not adjudicate.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from packaging.markers import Marker

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "deploy" / "sbx" / "template" / "Dockerfile.tests"
LOCK = ROOT / "uv.lock"

FROM_RE = re.compile(
    r"^\s*FROM\s+python:(?P<major>\d+)\.(?P<minor>\d+)(?:\.\d+)?-\S+@sha256:[0-9a-f]{64}",
    re.IGNORECASE,
)


def _base_interpreter() -> str:
    """The `cpNNN` line the seed base ships, from the pinned FROM tag."""
    for line in DOCKERFILE.read_text(encoding="utf-8").splitlines():
        match = FROM_RE.match(line)
        if match:
            return f"cp{match.group('major')}{match.group('minor')}"
    raise AssertionError(
        f"{DOCKERFILE.relative_to(ROOT)} no longer pins a digest-qualified "
        "python:<X.Y>-… base; the seed interpreter contract cannot be "
        "evaluated against a floating or non-python base"
    )


def _marker_environment(line: str) -> dict[str, str]:
    """A linux CPython environment for the cpNNN line, for marker evaluation."""
    major, minor = line[2], line[3:]
    return {
        "implementation_name": "cpython",
        "implementation_version": f"{major}.{minor}.0",
        "os_name": "posix",
        "platform_machine": "x86_64",
        "platform_release": "6.8.0",
        "platform_system": "Linux",
        "platform_version": "",
        "python_full_version": f"{major}.{minor}.0",
        "platform_python_implementation": "CPython",
        "python_version": f"{major}.{minor}",
        "sys_platform": "linux",
    }


def _linux_wheel_lines(entry: dict) -> set[str]:
    """The cpNNN lines (or {'pure'}) the entry has installable wheels for.

    A wheel is installable for a line when its platform is linux or any, its
    ABI is none/abi3/a cp tag, and its python tag covers the line: a pure tag
    covers every line, a cpNN-cpNN wheel covers exactly cpNN, and a
    cpNN-abi3 wheel covers cpNN and every later line (the stable ABI promise).
    """
    lines: set[str] = set()
    for wheel in entry.get("wheels", []):
        filename = wheel.get("url", "").rsplit("/", 1)[-1]
        parts = filename[: -len(".whl")].split("-")
        if len(parts) < 5:
            continue
        pytag, abi, platform = parts[-3], parts[-2], parts[-1]
        if "linux" not in platform and platform != "any":
            continue
        if abi != "none" and abi != "abi3" and not abi.startswith("cp"):
            continue
        if pytag.startswith("py"):
            lines.add("pure")
            continue
        if pytag.startswith("cp") and pytag[2:].isdigit():
            # `cp` + major + minor (cp312 = 3.12); abi3 covers its floor line
            # and every later minor.
            major, minor = pytag[2], int(pytag[3:])
            if abi == "abi3":
                lines.update(f"cp{major}{n}" for n in range(minor, minor + 8))
            else:
                lines.add(pytag)
    return lines


def test_seed_base_line_has_a_binary_artifact_for_every_linux_relevant_lock_entry() -> None:
    """No lock entry may lose its linux wheels on the seed base's CPython line.

    The #2136/#2376 failure mode: every distribution the seed sync selects has
    binary wheels for the pinned line, and a Dependabot base jump to a newer
    line silently moves the ceiling past them — the image then fails at
    `uv sync --frozen` with "doesn't have a source distribution or wheel for
    the current platform" and no compiler to fall back on. This test fails at
    authoring time instead, naming the distributions and the disposition to
    consult before moving the line.
    """
    line = _base_interpreter()
    environment = _marker_environment(line)
    offenders: list[tuple[str, str, list[str]]] = []
    with LOCK.open("rb") as handle:
        lock = tomllib.load(handle)
    for entry in lock.get("package", []):
        if "registry" not in entry.get("source", {}):
            continue  # workspace/path members install from source by design
        marker = entry.get("marker")
        if marker is not None and not Marker(str(marker)).evaluate(environment):
            continue  # not installable on linux/cpNNN at all
        lines = _linux_wheel_lines(entry)
        if lines and "pure" not in lines and line not in lines:
            offenders.append((entry["name"], entry["version"], sorted(lines)))
    assert not offenders, (
        f"the sbx-tests seed base ({DOCKERFILE.relative_to(ROOT)}) pins CPython "
        f"{line[2]}.{line[3:]}, but {len(offenders)} uv.lock distribution(s) have "
        "linux wheels only for other lines and would fail the seed's "
        "`uv sync --frozen` on this base (no sdist fallback: the seed image "
        "installs no C compiler): "
        + ", ".join(f"{name}=={version} (wheels for {lines})" for name, version, lines in offenders)
        + ". Move the base only to a line every distribution covers, and record "
        "the disposition in the image's quality/image-pins.json row (see the "
        "#2136 wheel-ceiling rejection and the #2376 re-verification)."
    )
