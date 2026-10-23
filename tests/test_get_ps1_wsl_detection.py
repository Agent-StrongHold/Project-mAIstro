"""Parser and install-path regression tests for get.ps1's WSL distro detection (#354).

The tests supervise tests/installer/wsl_detection_harness.ps1, which dot-sources
the real get.ps1 and drives it with a scripted ``wsl.exe`` at the process
boundary. Two case families:

- ``parser:<fixture-stem>``  real captured ``wsl -l -v`` variants (default
  marker, localized headers, Unicode names, WSL1/WSL2, running/stopped/
  installing, no-default, multiple distros, no-distro banners), each parsed
  twice: as plain lines and re-encoded the way wsl.exe actually reaches
  PowerShell (UTF-16LE bytes decoded through an OEM codepage, i.e. NUL-padded
  and lossy for non-ASCII content).
- ``scenario:<name>``        end-to-end install/reboot decisions: an existing
  default distro must be used (never reinstalled or rebooted over), an
  explicitly requested distro must be preserved, an existing usable default
  must be adopted when the requested default is absent, a fresh machine must
  install without a reboot when the distro becomes usable, a stuck install
  must still reach the reboot, and machine-readable JSON listing must be
  preferred where offered (falling back on unmapped shapes).

The pytest layer only supervises; every expectation lives in the harness so
the Windows E2E workflow job runs the exact same cases.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GET_PS1 = ROOT / "get.ps1"
HARNESS = ROOT / "tests" / "installer" / "wsl_detection_harness.ps1"
FIXTURES = ROOT / "tests" / "fixtures" / "wsl-list"

PARSER_CASES = sorted(path.stem for path in FIXTURES.glob("*.txt"))
SCENARIO_CASES = [
    "existing-default-usable",
    "rerun-twice-idempotent",
    "existing-nondefault-usable",
    "adopt-existing-default",
    "explicit-distro-preserved",
    "fresh-install-no-distros",
    "install-stuck-reboots",
    "json-table-preferred",
    "json-unmapped-falls-back",
    "exact-name-match",
]


def _run_harness(mode: str, case: str) -> subprocess.CompletedProcess[str]:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("pwsh is not installed")
    env = os.environ.copy()
    for name in ("GITHUB_TOKEN", "MAISTRO_GITHUB_TOKEN", "MAISTRO_SHA256SUMS_URL"):
        env.pop(name, None)
    env["MAISTRO_DRY_RUN"] = "1"
    return subprocess.run(
        [
            pwsh,
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(HARNESS),
            "-Mode",
            mode,
            "-Case",
            case,
            "-GetPs1",
            str(GET_PS1),
            "-Fixtures",
            str(FIXTURES),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


@pytest.mark.parametrize("case", PARSER_CASES)
def test_parser_fixture_variants(case: str) -> None:
    result = _run_harness("parser", case)

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert f"RESULT parser:{case} ok" in result.stdout


@pytest.mark.parametrize("case", SCENARIO_CASES)
def test_install_path_scenario(case: str) -> None:
    result = _run_harness("scenario", case)

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert f"RESULT scenario:{case} ok" in result.stdout


def test_harness_case_list_matches_the_python_enumeration() -> None:
    """The Windows E2E runner enumerates cases from the harness; this pins the
    harness list to the same set pytest parametrizes, so neither side drifts."""

    result = _run_harness("List", "")

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    listed = result.stdout.splitlines()
    assert {line[len("parser:") :] for line in listed if line.startswith("parser:")} == set(
        PARSER_CASES
    )
    assert {line[len("scenario:") :] for line in listed if line.startswith("scenario:")} == set(
        SCENARIO_CASES
    )
