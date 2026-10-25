"""install.sh refuses Docker daemons the embedded v29 CLI cannot negotiate.

The engine images COPY their docker CLI from ``docker:29-cli``: that CLI only
speaks Docker API 1.44+, a floor that rose with the go1.26.8 toolchain rebuild
that fixed CVE-2025-68121 (+21 HIGHs) in the previously embedded go1.22.11
binary. An Engine 24 daemon (API 1.43) would otherwise break the builder
sandboxes mid-install with a cryptic negotiation error, so ``install.sh``
refuses it up front.

``release-installer.yml`` runs ``./install.sh`` only on tags, so no PR check
executes a line of the installer — the same gap tests/test_secret_env.py
closes for the env-writing path. These tests lift the real functions out of
``install.sh`` verbatim and run them against a stub ``docker`` binary, so a
rewiring mistake fails a PR check instead of a release.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = ROOT / "install.sh"

#: The engine-floor functions, lifted verbatim from install.sh.
_FUNCTIONS = ("version_ge", "ensure_docker_engine_supported")

_REFUSED_MESSAGE = "Docker Engine 25+ (API 1.44+) required"


def _harness(shim_dir: Path, base_path: str = "$PATH") -> str:
    extract = ";".join(f"/^{name}()/,/^}}/p" for name in _FUNCTIONS)
    install = shlex.quote(str(INSTALL_SH))
    return f"""
set -euo pipefail
PATH={shlex.quote(str(shim_dir))}:{base_path}
ok() {{ echo "[ok] $*"; }}
info() {{ :; }}
warn() {{ echo "WARN: $*" >&2; }}
fail() {{ echo "[error] $*" >&2; exit 1; }}
eval "$(grep -E '^MIN_DOCKER_API_VERSION=' {install})"
source <(sed -n {extract!r} {install})
"""


def _run(
    shim_dir: Path, script: str, *, base_path: str | None = None
) -> subprocess.CompletedProcess[str]:
    harness = _harness(shim_dir, base_path if base_path is not None else "$PATH")
    return subprocess.run(
        ["bash", "-c", harness + script],
        capture_output=True,
        text=True,
        check=False,
    )


def _path_without_docker(tmp_path: Path) -> str:
    """A PATH that can never resolve `docker`: a dir holding only the tools
    the harness itself needs. `command -v docker` over this PATH models a
    podman-only host deterministically, whatever the test machine runs."""
    minibin = tmp_path / "minibin"
    minibin.mkdir()
    for tool in ("sed", "grep"):
        for base in ("/usr/bin", "/bin"):
            source = Path(base) / tool
            if source.exists():
                (minibin / tool).symlink_to(source)
                break
        else:
            raise AssertionError(f"{tool} not found in /usr/bin or /bin")
    return shlex.quote(str(minibin))


def _write_docker_shim(
    shim_dir: Path, api_version: str | None = None, *, broken: bool = False
) -> None:
    """A stub `docker` binary. `broken` models a daemon that never answers;
    `api_version=None` models a `docker version` that prints nothing."""
    lines = ["#!/usr/bin/env bash"]
    if broken:
        lines.append(
            "echo 'Cannot connect to the Docker daemon at unix:///var/run/docker.sock' >&2"
        )
        lines.append("exit 1")
    else:
        lines.append('if [[ "${1:-}" == "version" ]]; then')
        if api_version is None:
            lines.append("    exit 1")
        else:
            lines.append(f"    echo {shlex.quote(api_version)}")
            lines.append("    exit 0")
        lines.append("fi")
        lines.append("exit 0")
    shim = shim_dir / "docker"
    shim.write_text("\n".join(lines) + "\n", encoding="utf-8")
    shim.chmod(0o755)


def test_the_floor_constant_is_present_and_pins_engine_25s_api() -> None:
    body = INSTALL_SH.read_text(encoding="utf-8")
    match = re.search(r'^MIN_DOCKER_API_VERSION="([0-9.]+)"$', body, re.M)
    assert match, "install.sh lost the MIN_DOCKER_API_VERSION floor constant"
    assert match.group(1) == "1.44", (
        "the floor moved; revisit the refusal boundary tests alongside it"
    )


def test_start_engine_enforces_the_floor_before_first_daemon_use() -> None:
    body = INSTALL_SH.read_text(encoding="utf-8")
    assert re.search(
        r"ensure_compose_runtime\n\s+ensure_docker_engine_supported\n\s+record_docker_sock",
        body,
    ), "start_engine must check the engine floor right after the runtime is ready"


def test_engine_24_daemon_is_refused_with_an_upgrade_pointer(tmp_path: Path) -> None:
    _write_docker_shim(tmp_path, "1.43")
    result = _run(tmp_path, "ensure_docker_engine_supported\n")
    assert result.returncode != 0, result.stdout
    assert _REFUSED_MESSAGE in result.stderr
    assert "detected API 1.43" in result.stderr
    assert "Upgrade Docker Engine, then re-run." in result.stderr
    assert "[ok]" not in result.stdout


@pytest.mark.parametrize("api", ["1.44", "1.45", "1.48", "2.0"])
def test_engine_25_plus_passes(tmp_path: Path, api: str) -> None:
    _write_docker_shim(tmp_path, api)
    result = _run(tmp_path, "ensure_docker_engine_supported\n")
    assert result.returncode == 0, result.stderr
    assert "[ok]" in result.stdout
    assert "[error]" not in result.stderr


def test_a_missing_docker_cli_is_skipped(tmp_path: Path) -> None:
    """Podman-only hosts have no docker binary; the compose-runtime detection
    owns that path, so the floor check must stay out of the way."""
    result = _run(
        tmp_path, "ensure_docker_engine_supported\n", base_path=_path_without_docker(tmp_path)
    )
    assert result.returncode == 0, result.stderr
    assert "[error]" not in result.stderr
    assert "[ok]" not in result.stdout


@pytest.mark.parametrize("broken", [True, False])
def test_an_unanswering_daemon_is_skipped(tmp_path: Path, broken: bool) -> None:
    """A daemon that is down (version fails) or answers nothing (empty API)
    is the bootstrap paths' problem; the floor check must not stack a second
    error on top of theirs."""
    _write_docker_shim(tmp_path, None, broken=broken)
    result = _run(tmp_path, "ensure_docker_engine_supported\n")
    assert result.returncode == 0, result.stderr
    assert "[error]" not in result.stderr
    assert "[ok]" not in result.stdout


@pytest.mark.parametrize(
    ("left", "right", "expected_ge"),
    [
        ("1.44", "1.44", True),
        ("1.45", "1.44", True),
        ("1.43", "1.44", False),
        ("1.4", "1.44", False),
        ("2.0", "1.99", True),
    ],
)
def test_version_ge_orders_dotted_numeric_versions(
    tmp_path: Path, left: str, right: str, expected_ge: bool
) -> None:
    result = _run(
        tmp_path,
        f"version_ge {left} {right} && echo GE || echo LT\n",
        base_path=_path_without_docker(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    assert ("GE\n" if expected_ge else "LT\n") in result.stdout
