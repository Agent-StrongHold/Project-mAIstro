"""A hung Docker credential helper fails the install in seconds, not never.

Docker Desktop keeps registry credentials behind `docker-credential-desktop`,
backed by the macOS keychain. When the keychain cannot show its prompt -- ssh,
launchd, a locked login keychain -- the helper blocks forever, and so does
every pull and build waiting on it. On the Mac this was found on, `compose up
--build` sat at "load metadata for docker.io/library/python" for 14 minutes
with no output; docker-buildx's only child was a `get` that never returned.
The helper ignores SIGTERM and SIGALRM, so only SIGKILL stops it.

`check_docker_credential_helper` probes it once, bounded, before anything is
pulled. These tests lift it verbatim out of install.sh and point it at stub
helpers, since CI has no keychain to hang on.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = ROOT / "install.sh"


def _setup(tmp_path: Path, *, creds_store: str | None, helper_body: str | None) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # A `docker` must exist for the check to run at all.
    (bin_dir / "docker").write_text("#!/usr/bin/env bash\nexit 0\n")
    (bin_dir / "docker").chmod(0o755)
    if creds_store and helper_body is not None:
        helper = bin_dir / f"docker-credential-{creds_store}"
        helper.write_text(f"#!/usr/bin/env bash\n{helper_body}\n")
        helper.chmod(0o755)
    config_dir = tmp_path / "docker-config"
    config_dir.mkdir()
    config = {"credsStore": creds_store} if creds_store else {}
    (config_dir / "config.json").write_text(json.dumps(config))
    return bin_dir


def _check(
    tmp_path: Path, bin_dir: Path, *, timeout: str = "2"
) -> subprocess.CompletedProcess[str]:
    install = shlex.quote(str(INSTALL_SH))
    script = f"""
# The same options install.sh runs under. Without -e here, a helper that
# aborted the real installer on a *successful* lookup passed every test.
set -euo pipefail
ok()   {{ echo "OK: $*"; }}
info() {{ echo "INFO: $*"; }}
warn() {{ echo "WARN: $*"; }}
fail() {{ echo "FAIL: $*" >&2; exit 1; }}
# eval, not `source <(...)`: macOS ships bash 3.2 as /bin/bash, where
# sourcing a process substitution silently reads nothing.
eval "$(sed -n '/^check_docker_credential_helper()/,/^}}/p;/^run_with_timeout()/,/^}}/p' {install})"
PYTHON_CMD=(python3)
check_docker_credential_helper
echo "PREFLIGHT PASSED"
"""
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{_host_path_without_docker()}",
            "DOCKER_CONFIG": str(tmp_path / "docker-config"),
            "MAISTRO_CRED_HELPER_TIMEOUT": timeout,
        },
        timeout=60,
    )


def _host_path_without_docker() -> str:
    """PATH with every directory holding a real docker or credential helper dropped.

    On a Mac with Docker Desktop both live in /usr/local/bin, and leaving them
    visible lets the host's own hung helper answer for a stub -- which is how
    the "not installed" case first failed here while it would have passed in
    CI, where there is no Docker Desktop at all.
    """
    keep = []
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if not d or not os.path.isdir(d):
            continue
        names = set(os.listdir(d))
        if "docker" in names or any(n.startswith("docker-credential-") for n in names):
            continue
        keep.append(d)
    return os.pathsep.join(keep)


def test_a_hung_helper_fails_fast_with_what_to_do(tmp_path: Path) -> None:
    """The case that froze the install. It must end, and say why."""
    bin_dir = _setup(tmp_path, creds_store="desktop", helper_body="sleep 300")

    started = time.monotonic()
    result = _check(tmp_path, bin_dir, timeout="2")
    elapsed = time.monotonic() - started

    assert result.returncode != 0
    assert elapsed < 20, f"the probe did not give up (took {elapsed:.0f}s)"
    assert "did not answer within 2s" in result.stderr
    assert "security unlock-keychain" in result.stderr
    assert '"credsStore": "desktop"' in result.stderr
    assert "PREFLIGHT PASSED" not in result.stdout


def test_a_helper_that_ignores_sigterm_is_still_stopped(tmp_path: Path) -> None:
    """docker-credential-desktop ignores SIGTERM and SIGALRM; only SIGKILL
    works. A timeout built on either of the first two would bound nothing."""
    bin_dir = _setup(
        tmp_path,
        creds_store="desktop",
        helper_body="trap '' TERM ALRM\nwhile :; do sleep 1; done",
    )

    started = time.monotonic()
    result = _check(tmp_path, bin_dir, timeout="2")

    assert result.returncode != 0
    assert time.monotonic() - started < 20


def test_a_healthy_helper_passes(tmp_path: Path) -> None:
    bin_dir = _setup(tmp_path, creds_store="desktop", helper_body='echo "{}"')

    result = _check(tmp_path, bin_dir)

    assert result.returncode == 0, result.stderr
    assert "PREFLIGHT PASSED" in result.stdout


def test_a_helper_that_errors_quickly_is_not_a_hang(tmp_path: Path) -> None:
    """No stored credentials is an ordinary answer. Only silence is the problem."""
    bin_dir = _setup(
        tmp_path, creds_store="desktop", helper_body='echo "credentials not found" >&2; exit 1'
    )

    result = _check(tmp_path, bin_dir)

    assert result.returncode == 0, result.stderr
    assert "PREFLIGHT PASSED" in result.stdout


def test_no_credential_store_means_nothing_is_probed(tmp_path: Path) -> None:
    """Linux hosts and plain Docker installs usually configure none."""
    bin_dir = _setup(tmp_path, creds_store=None, helper_body=None)

    result = _check(tmp_path, bin_dir)

    assert result.returncode == 0
    assert "PREFLIGHT PASSED" in result.stdout


def test_a_configured_helper_that_is_not_installed_is_left_to_docker(tmp_path: Path) -> None:
    """Docker reports a missing helper itself, clearly; nothing hangs."""
    bin_dir = _setup(tmp_path, creds_store="desktop", helper_body=None)

    result = _check(tmp_path, bin_dir)

    assert result.returncode == 0
    assert "PREFLIGHT PASSED" in result.stdout
