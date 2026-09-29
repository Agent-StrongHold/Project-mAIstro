"""install.sh records the non-default Docker socket path without dying (#807).

The branch that records ``MAISTRO_DOCKER_SOCK`` runs only when the Docker
endpoint is not the default ``/var/run/docker.sock`` — Colima's
``~/.colima/<profile>/docker.sock`` on macOS is the supported case. Gate C's
Linux clean-install leg never takes that branch, and
``release-installer.yml`` runs ``./install.sh`` only on tags, so no PR check
executed a line of it: install.sh shipped a call to ``upsert_env``, a function
it never defines (the real helper is ``set_env_value``), and a supported
macOS install died with ``upsert_env: command not found`` before any container
started.

Following the verbatim-lift pattern from ``tests/test_secret_env.py`` and
``tests/test_install_engine_floor.py``, these tests source the real functions
out of ``install.sh`` and run them against a stub ``docker`` binary, so the
non-default-socket branch — and everything it writes through
``scripts/secret_env.py`` — fails a PR check instead of a user's machine.
"""

from __future__ import annotations

import os
import shlex
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = ROOT / "install.sh"

#: record_docker_sock plus the env-writing path it must reach, lifted verbatim
#: from install.sh.
_FUNCTIONS = (
    "ensure_python",
    "secret_env_run",
    "set_env_value",
    "record_docker_sock",
)

DEFAULT_SOCKET = "/var/run/docker.sock"
COLIMA_SOCKET = "/Users/maistro/.colima/default/docker.sock"


def _harness(shim_dir: Path) -> str:
    extract = ";".join(f"/^{name}()/,/^}}/p" for name in _FUNCTIONS)
    install = shlex.quote(str(INSTALL_SH))
    return f"""
set -euo pipefail
PATH={shlex.quote(str(shim_dir))}:$PATH
ok() {{ :; }}
info() {{ :; }}
warn() {{ echo "WARN: $*" >&2; }}
fail() {{ echo "[error] $*" >&2; exit 1; }}
SCRIPT_DIR={str(ROOT)!r}
ENV_FILE=".env"
PYTHON_CMD=()
source <(sed -n {extract!r} {install})
"""


def _run(
    tmp_path: Path, script: str, *, env_extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", "-c", _harness(tmp_path) + script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _write_docker_shim(shim_dir: Path, *, host: str | None, fail_inspect: bool = False) -> None:
    """A stub `docker` whose `context inspect` answers `host`. `None` answers
    nothing (models a daemon the CLI cannot reach); `fail_inspect` models a
    CLI too old for `docker context`, so the installer falls back to
    $DOCKER_HOST."""
    lines = ["#!/usr/bin/env bash"]
    if fail_inspect:
        lines.append("echo 'docker context is unsupported' >&2")
        lines.append("exit 1")
    else:
        lines.append('if [[ "${1:-}" == "context" && "${2:-}" == "inspect" ]]; then')
        if host is None:
            lines.append("    exit 1")
        else:
            lines.append(f"    printf '%s\\n' {shlex.quote(host)}")
            lines.append("    exit 0")
        lines.append("fi")
    lines.append("exit 0")
    shim = shim_dir / "docker"
    shim.write_text("\n".join(lines) + "\n", encoding="utf-8")
    shim.chmod(0o755)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_install_sh_records_the_socket_through_set_env_value() -> None:
    """The regression pin: the call site names the helper install.sh actually
    defines. `upsert_env` never existed — the branch that names it is the one
    under test here."""
    body = INSTALL_SH.read_text(encoding="utf-8")
    assert "set_env_value MAISTRO_DOCKER_SOCK" in body
    assert "upsert_env" not in body


def test_a_non_default_socket_is_recorded(tmp_path: Path) -> None:
    """Colima exposes the socket under ~/.colima/<profile>/docker.sock. This
    branch is exactly the one no other gate executes (#807): before the fix it
    aborted with `upsert_env: command not found`, so the recorded path never
    reached .env and the builder sandbox lost its socket mount."""
    _write_docker_shim(tmp_path, host=f"unix://{COLIMA_SOCKET}")
    result = _run(tmp_path, "record_docker_sock\n")
    assert result.returncode == 0, result.stderr
    env_body = (tmp_path / ".env").read_text(encoding="utf-8")
    assert f"MAISTRO_DOCKER_SOCK={COLIMA_SOCKET}" in env_body


def test_the_recorded_env_file_stays_at_0600(tmp_path: Path) -> None:
    """The write goes through scripts/secret_env.py like every other .env
    write; a widened file would be a credential-safety regression."""
    _write_docker_shim(tmp_path, host=f"unix://{COLIMA_SOCKET}")
    result = _run(tmp_path, "umask 0000\nrecord_docker_sock\n")
    assert result.returncode == 0, result.stderr
    assert _mode(tmp_path / ".env") == 0o600


def test_the_default_socket_is_not_recorded(tmp_path: Path) -> None:
    """The default needs no override — compose already mounts the standard
    path — so the branch must stay silent and write nothing."""
    _write_docker_shim(tmp_path, host=f"unix://{DEFAULT_SOCKET}")
    result = _run(tmp_path, "record_docker_sock\n")
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / ".env").exists()


def test_docker_host_fallback_is_recorded(tmp_path: Path) -> None:
    """A `docker` CLI without context support (or a dead daemon) falls back to
    $DOCKER_HOST; a non-default value there is recorded the same way."""
    _write_docker_shim(tmp_path, host=None, fail_inspect=True)
    result = _run(
        tmp_path,
        "record_docker_sock\n",
        env_extra={"DOCKER_HOST": f"unix://{COLIMA_SOCKET}"},
    )
    assert result.returncode == 0, result.stderr
    env_body = (tmp_path / ".env").read_text(encoding="utf-8")
    assert f"MAISTRO_DOCKER_SOCK={COLIMA_SOCKET}" in env_body


def test_a_non_socket_endpoint_warns_and_writes_nothing(tmp_path: Path) -> None:
    """tcp:// endpoints cannot be bind-mounted; the installer says so instead
    of recording something the builder would choke on."""
    _write_docker_shim(tmp_path, host="tcp://127.0.0.1:2375")
    result = _run(tmp_path, "record_docker_sock\n")
    assert result.returncode == 0, result.stderr
    assert "not a unix socket" in result.stderr
    assert not (tmp_path / ".env").exists()


def test_a_missing_docker_cli_is_a_no_op(tmp_path: Path) -> None:
    """Podman hosts have no `docker` binary; the socket record is advisory and
    must not create an .env or fail the install. No shim is installed here, so
    `command -v docker` fails on the harness PATH itself."""
    result = _run(tmp_path, "record_docker_sock\n")
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / ".env").exists()
