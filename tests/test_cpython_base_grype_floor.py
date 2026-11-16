"""The CPython base pins must stay at or above the grype-flagged CVE floors.

The container gate's Grype cross-check (``--fail-on high --only-fixed``) reads
the CPython binary shipped inside every runtime image. CPython 3.13.16 and
3.12.15 binaries carry CVE-2026-115557 (CRITICAL, fixed in 3.13.18 and 3.12.16
respectively); the gate failed on ``hive-conductor:pr-2059`` at security.yml
run 43844074725 (job 133219714506) on exactly that finding.

Two contracts closed here:

- the pinned 3.13 tag in ``quality/image-pins.json`` stays at the floor, and
  security.yml's ``docker run`` version asserts name the SAME patch release --
  a pin bump that forgets the workflow assert would fail the gate with a bare
  assert far from the pin that caused it;
- the moving ``3.12-slim`` pin stays on a digest whose tag head resolved to
  3.12.16 (verified by running the image's interpreter), and every Dockerfile
  that builds from it references the registry row verbatim.

Structural assertions over pinned text, not a build, so the test is fast and
machine-independent.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PINS = json.loads((REPO_ROOT / "quality" / "image-pins.json").read_text())["pins"]

# CVE-2026-115557 (CRITICAL in the CPython binary; grype --fail-on high):
# fixed in 3.13.18 on the 3.13 line and in 3.12.16 on the 3.12 line.
GRYPE_FLOOR_3_13 = (3, 13, 18)

# `python:3.12-slim` tag head recorded 2026-11-16 (#2059); verified to resolve
# to CPython 3.12.16 by `docker run --entrypoint python <digest> --version`.
GRYPE_FLOOR_3_12_SLIM_DIGEST = (
    "sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b"
)

# The retired digest pinned the tag head that resolved to CPython 3.12.15,
# whose binary grype flags at CRITICAL.
RETIRED_3_12_SLIM_DIGEST = "sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704"

PYTHON_3_13_ROW = next(
    row for row in PINS if row["image"] == "python" and row["tag"].startswith("3.13.")
)
PYTHON_3_12_ROW = next(
    row for row in PINS if row["image"] == "python" and row["tag"] == "3.12-slim"
)


def _parse_patch_tag(tag: str) -> tuple[int, int, int]:
    return tuple(int(part) for part in tag.removesuffix("-slim-bookworm").split("."))


def test_python_3_13_pin_meets_the_grype_floor() -> None:
    pinned = _parse_patch_tag(PYTHON_3_13_ROW["tag"])
    assert pinned >= GRYPE_FLOOR_3_13, (
        f"{PYTHON_3_13_ROW['tag']} is below the CVE-2026-115557 fix release "
        f"3.13.18; grype --fail-on high fails the container gate on the "
        f"shipped CPython binary"
    )


def test_security_yml_version_asserts_name_the_pinned_3_13_patch() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "security.yml").read_text(encoding="utf-8")
    pinned = _parse_patch_tag(PYTHON_3_13_ROW["tag"])
    asserts = re.findall(r"assert sys\.version_info\[:3\] == \((\d+), (\d+), (\d+)\)", workflow)
    assert asserts, "no CPython version assert found in security.yml"
    for found in asserts:
        got = tuple(int(part) for part in found)
        assert got == pinned, (
            f"security.yml asserts CPython {got} but the pinned base image "
            f"ships {pinned}; the docker-run verify steps would fail (or pass "
            f"vacuously) against the shipped image"
        )


@pytest.mark.parametrize(
    "dockerfile",
    (
        REPO_ROOT / "Dockerfile",
        REPO_ROOT / "packages/hive-conductor/Dockerfile",
    ),
    ids=lambda p: p.name,
)
def test_engine_and_conductor_dockerfiles_pin_the_registered_3_13_base(
    dockerfile: Path,
) -> None:
    registered = f"python:{PYTHON_3_13_ROW['tag']}@{PYTHON_3_13_ROW['digest']}"
    text = dockerfile.read_text(encoding="utf-8")
    assert registered in text, f"{dockerfile.name}: base pin {registered} not referenced verbatim"


@pytest.mark.parametrize(
    "dockerfile",
    (
        REPO_ROOT / "Dockerfile.research",
        REPO_ROOT / "Dockerfile.rsi-runner",
        REPO_ROOT / "packages/hive-conductor/tests/Dockerfile",
        REPO_ROOT / "deploy/sbx/template/Dockerfile.tests",
    ),
    ids=lambda p: p.name,
)
def test_3_12_dockerfiles_pin_the_registered_grype_floor_digest(
    dockerfile: Path,
) -> None:
    assert PYTHON_3_12_ROW["digest"] == GRYPE_FLOOR_3_12_SLIM_DIGEST, (
        "quality/image-pins.json's 3.12-slim row is not the digest verified to "
        "resolve to CPython 3.12.16 (the CVE-2026-115557 floor)"
    )
    registered = f"python:3.12-slim@{PYTHON_3_12_ROW['digest']}"
    text = dockerfile.read_text(encoding="utf-8")
    assert registered in text, f"{dockerfile.name}: base pin {registered} not referenced verbatim"


@pytest.mark.parametrize(
    "dockerfile",
    (
        REPO_ROOT / "Dockerfile",
        REPO_ROOT / "packages/hive-conductor/Dockerfile",
        REPO_ROOT / "Dockerfile.research",
        REPO_ROOT / "Dockerfile.rsi-runner",
        REPO_ROOT / "packages/hive-conductor/tests/Dockerfile",
        REPO_ROOT / "deploy/sbx/template/Dockerfile.tests",
    ),
    ids=lambda p: p.name,
)
def test_no_dockerfile_references_the_vulnerable_3_12_15_digest(
    dockerfile: Path,
) -> None:
    text = dockerfile.read_text(encoding="utf-8")
    assert RETIRED_3_12_SLIM_DIGEST not in text, (
        f"{dockerfile.name}: still pinned to the retired digest that resolves "
        f"to CPython 3.12.15, whose binary grype flags CVE-2026-115557 "
        f"(CRITICAL)"
    )
