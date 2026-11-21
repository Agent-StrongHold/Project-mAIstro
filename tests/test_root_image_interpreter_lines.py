"""The root images' base interpreters must be lines the lock can serve.

Same contract as tests/test_sbx_seed_interpreter_line.py, generalized to the
three root Dockerfiles that install from the committed `uv.lock` and were the
subject of #2430: `Dockerfile` (engine), `Dockerfile.research` and
`Dockerfile.rsi-runner`. #2430 re-raised the #2136/#2376 failure class across
all three at once: Dependabot jumped every `python:` FROM to the 3.15 line in
one commit. The digests are real (all three successor indexes resolve in the
registry with linux/amd64 present), the unregistered pin is all
`check-image-pins.py` flags — and every one of the images is unbuildable on
the new line: the engine and research builders `uv export --locked …
--require-hashes` and the RSI runner `uv sync --locked` select
psycopg-binary 3.3.4, which ships no cp315 wheel and no sdist at all, so the
pinned resolution fails closed; coincurve 21.0.0 (still the latest upstream
release) stops at cp313 and cffi 2.0.0 at cp314, both with sdists that need a
compiler none of the builders installs. Counted 2026-11-21 against this lock:
20 linux-relevant entries are cp315-unservable, zero on the pinned 3.12 and
3.13 lines. The disposition record lives in the image-pins notes
(quality/image-pins.json, #2430 round) and inline at each FROM.

This module holds that contract closed statically, without Docker, uv or
network: parse the CPython minor from every digest-pinned `FROM python:` line
of the three root Dockerfiles, walk every registry entry in `uv.lock` whose
environment marker is satisfiable on linux/cpNNN, and assert each ships a
binary artifact installable there — a linux (or any-platform) wheel tagged
for cpNNN, an abi3 wheel whose floor is at or below cpNNN, or a pure-Python
wheel. It also pins the interpreter identity the raw Dependabot diff broke:
each image's own install line (`uv venv --python 3.N` / `uv sync --locked
--python 3.N`) must be one of the base lines the same file's FROMs name, so a
lone FROM jump fails here instead of desyncing the venv from the base (or
pushing uv to fetch an un-pinned managed interpreter into the build).

Deliberately scoped to the three root images: the sbx seed keeps its own
module (tests/test_sbx_seed_interpreter_line.py), the pure-wheel
hive-conductor api-tests harness has no ceiling (#2377), and the installer
templates resolve their own sets (#2375 accepted 3.15.0 there). Entries with
no linux wheels at all (sdist-only publishes such as crcmod) are outside this
contract — they either are not selected by these installs or already require
a source build on every line, which is a pre-existing condition this module
does not adjudicate.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from packaging.markers import Marker

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "uv.lock"

# The three root images #2430 touched; all install from the committed lock.
ROOT_DOCKERFILES = (
    "Dockerfile",
    "Dockerfile.research",
    "Dockerfile.rsi-runner",
)

FROM_RE = re.compile(
    r"^\s*FROM\s+python:(?P<major>\d+)\.(?P<minor>\d+)(?:\.\d+)?-\S+@sha256:[0-9a-f]{64}",
    re.IGNORECASE,
)
INSTALL_PYTHON_RE = re.compile(r"--python\s+(\d+)\.(\d+)")


def _base_lines(dockerfile: Path) -> list[str]:
    """The `cpNNN` lines the file's digest-pinned python FROMs ship."""
    lines: list[str] = []
    for line in dockerfile.read_text(encoding="utf-8").splitlines():
        match = FROM_RE.match(line)
        if match:
            lines.append(f"cp{match.group('major')}{match.group('minor')}")
    if not lines:
        raise AssertionError(
            f"{dockerfile.relative_to(ROOT)} no longer pins any digest-qualified "
            "python:<X.Y>-… base; the interpreter contract cannot be evaluated "
            "against a floating or non-python base"
        )
    return lines


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


def _lock_offenders(line: str) -> list[tuple[str, str, list[str]]]:
    """Registry entries the lock cannot serve with a binary artifact on `line`."""
    environment = _marker_environment(line)
    with LOCK.open("rb") as handle:
        lock = tomllib.load(handle)
    offenders: list[tuple[str, str, list[str]]] = []
    for entry in lock.get("package", []):
        if not entry.get("source", {}).get("registry"):
            continue
        markers = entry.get("environment_markers")
        if markers and not Marker(markers).evaluate(environment):
            continue
        wheel_lines = _linux_wheel_lines(entry)
        if not wheel_lines:
            # No linux wheels at all: outside this contract (see module doc).
            continue
        if "pure" not in wheel_lines and line not in wheel_lines:
            offenders.append((entry["name"], entry["version"], sorted(wheel_lines)))
    return offenders


def test_every_root_image_base_line_is_served_by_the_lock() -> None:
    """No lock entry may lose its linux wheels on any root image's base line.

    The #2136/#2376/#2430 failure mode: every distribution the pinned install
    selects has binary wheels for the pinned line, and a Dependabot base jump
    to a newer line silently moves the ceiling past them — the image then
    fails at `uv pip install --require-hashes` / `uv sync --locked` (the
    psycopg-binary 3.3.4 row carries no sdist at all, so the failure is
    unconditional) with no compiler to fall back on. This test fails at
    authoring time instead, naming the distributions and the disposition to
    consult before moving the line.
    """
    for name in ROOT_DOCKERFILES:
        dockerfile = ROOT / name
        for line in _base_lines(dockerfile):
            offenders = _lock_offenders(line)
            assert not offenders, (
                f"{name} pins base line {line}, which the committed uv.lock "
                f"cannot serve with binary artifacts for {len(offenders)} "
                "linux-relevant distribution(s): "
                + ", ".join(f"{n} {v} (ships {', '.join(ls)})" for n, v, ls in offenders)
                + ". See quality/image-pins.json (#2430 round) and the FROM "
                "comments for the rejection record; re-attempt the bump only "
                "when every linux-relevant locked distribution ships a binary "
                "artifact on the new line."
            )


def test_install_interpreter_line_matches_a_base_from_line() -> None:
    """Each root image's own install line must be one of its base FROM lines.

    A Dependabot docker bump rewrites only the FROM lines, so a jump across
    the interpreter line leaves the image installing for a DIFFERENT python
    than the base ships: `uv venv --python 3.13` on a 3.15 base makes uv
    fetch an un-pinned managed interpreter into the build (the #349 doctrine
    forbids exactly that class of un-attested artifact), and
    Dockerfile.research's runtime additionally hard-codes the python3.12
    site-packages cleanup path, which silently no-ops on a 3.15 base and
    ships pip into the production image. Pinning install-line ∈ base-lines
    turns that desync into a named red here rather than a build that only
    works by downloading an unattested interpreter.
    """
    for name in ROOT_DOCKERFILES:
        dockerfile = ROOT / name
        text = dockerfile.read_text(encoding="utf-8")
        base_lines = set(_base_lines(dockerfile))
        install_lines = {f"cp{major}{minor}" for major, minor in INSTALL_PYTHON_RE.findall(text)}
        assert install_lines, (
            f"{name} no longer names an interpreter on its install line "
            "(--python 3.N); the interpreter identity contract cannot be "
            "evaluated"
        )
        stray = install_lines - base_lines
        assert not stray, (
            f"{name} installs for {sorted(stray)} but its FROM lines ship "
            f"{sorted(base_lines)}; a FROM bump must move the --python "
            "install line to the same interpreter in the same change (or the "
            "bump is rejected — see the #2430 disposition in "
            "quality/image-pins.json)"
        )
