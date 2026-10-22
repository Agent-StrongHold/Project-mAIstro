"""The Apple Silicon image check cannot freeze the installer (Mac install).

`report_arch` asks the registry whether each third-party image ships an arm64
build. It is advisory -- a missing manifest only means QEMU emulation -- and it
used to be the one step that could stop a Mac install dead:

* `docker manifest inspect` ran under the user's docker config. Docker Desktop
  sets `credsStore: desktop`, and the helper blocks whenever it cannot reach the
  keychain UI. Measured on a real Mac: 8+ minutes with no output, while the
  registries answered in under half a second. With the helper bypassed the same
  lookup took 7 seconds. There was no timeout, so the installer sat at
  "checking base images for native arm64 builds..." indefinitely.
* The image list was hardcoded and had drifted: it checked `pgvector:pg17`
  while the stack runs `pg18`, then -- having been killed rather than answered
  -- warned that a native image "may be emulated".

These run `report_arch` lifted verbatim out of install.sh against a stub
`docker`, so no test needs a daemon, a registry or a network.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = ROOT / "install.sh"


def _stub_docker(bin_dir: Path, *, images: str, manifest: str, hang: bool = False) -> Path:
    """A `docker` that serves `compose config --images` and `manifest inspect`.

    Every manifest lookup is logged with the DOCKER_CONFIG it ran under, which
    is the property the credential-helper fix is about.
    """
    log = bin_dir / "calls.log"
    body = f"""#!/usr/bin/env bash
if [[ "$1" == "compose" ]]; then
    printf '%s\\n' {shlex.quote(images)}
    exit 0
fi
if [[ "$1" == "manifest" && "$2" == "inspect" ]]; then
    printf 'inspect %s DOCKER_CONFIG=%s\\n' "$3" "${{DOCKER_CONFIG:-<unset>}}" >> {shlex.quote(str(log))}
    {"sleep 30" if hang else ":"}
    printf '%s' {shlex.quote(manifest)}
    exit 0
fi
exit 1
"""
    docker = bin_dir / "docker"
    docker.write_text(body)
    docker.chmod(0o755)
    return log


def _report_arch(bin_dir: Path, *, timeout: str = "20") -> subprocess.CompletedProcess[str]:
    install = shlex.quote(str(INSTALL_SH))
    script = f"""
# The same options install.sh runs under. Without -e here, a helper that
# aborted the real installer on a *successful* lookup passed every test.
set -euo pipefail
ok()   {{ echo "OK: $*"; }}
info() {{ echo "INFO: $*"; }}
warn() {{ echo "WARN: $*"; }}
# eval, not `source <(...)`: macOS ships bash 3.2 as /bin/bash, where
# sourcing a process substitution silently reads nothing.
eval "$(sed -n '/^report_arch()/,/^}}/p;/^run_with_timeout()/,/^}}/p' {install})"
ARCH=arm64
COMPOSE_CMD=(docker compose)
COMPOSE_FILES=(-f docker-compose.yml)
report_arch
"""
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "MAISTRO_ARCH_CHECK_TIMEOUT": timeout,
        },
        timeout=60,
    )


ARM64_INDEX = (
    '{"manifests":[{"platform":{"architecture":"arm64"}},{"platform":{"architecture":"amd64"}}]}'
)
AMD64_ONLY = '{"manifests":[{"platform":{"architecture":"amd64"}}]}'
STACK_IMAGES = "pgvector/pgvector:pg18\nlangfuse/langfuse:2\nmaistro-engine:local"


def test_the_images_checked_are_the_ones_the_stack_runs(tmp_path: Path) -> None:
    """Read from `compose config --images`, so the list cannot drift again."""
    log = _stub_docker(tmp_path, images=STACK_IMAGES, manifest=ARM64_INDEX)

    result = _report_arch(tmp_path)

    asked = log.read_text()
    assert "pgvector/pgvector:pg18" in asked
    assert "pg17" not in asked
    assert "OK: arm64 image available: pgvector/pgvector:pg18" in result.stdout


def test_locally_built_images_are_not_looked_up(tmp_path: Path) -> None:
    """`maistro-engine:local` is built on this machine, natively; there is no
    registry manifest to inspect, and asking would only waste a timeout."""
    log = _stub_docker(tmp_path, images=STACK_IMAGES, manifest=ARM64_INDEX)

    _report_arch(tmp_path)

    assert "maistro-engine:local" not in log.read_text()


def test_the_lookup_never_runs_under_the_users_credential_helper(tmp_path: Path) -> None:
    """The root cause of the freeze, pinned.

    Public images need no credentials. Running the lookup under the user's
    config invoked `docker-credential-desktop`, which is what blocked.
    """
    log = _stub_docker(tmp_path, images=STACK_IMAGES, manifest=ARM64_INDEX)

    _report_arch(tmp_path)

    for line in log.read_text().splitlines():
        config_dir = line.rsplit("DOCKER_CONFIG=", 1)[1]
        assert config_dir != "<unset>", "manifest inspect ran with the user's docker config"
        assert "maistro-anon-docker" in config_dir


def test_a_hanging_lookup_is_abandoned_and_the_install_continues(tmp_path: Path) -> None:
    """Bounded, and honest about it.

    A lookup that does not answer is reported as unchecked -- not as "will be
    emulated", which is what the old code said about native images it had
    simply failed to hear back from.
    """
    _stub_docker(tmp_path, images="pgvector/pgvector:pg18", manifest=ARM64_INDEX, hang=True)

    started = time.monotonic()
    result = _report_arch(tmp_path, timeout="1")
    elapsed = time.monotonic() - started

    assert result.returncode == 0
    assert elapsed < 15, f"the check did not give up (took {elapsed:.0f}s)"
    assert "Could not check pgvector/pgvector:pg18" in result.stdout
    assert "emulate" not in result.stdout


def test_an_image_without_arm64_is_still_reported_as_emulated(tmp_path: Path) -> None:
    """The check's actual job survives the fix."""
    _stub_docker(tmp_path, images="example/amd64-only:1", manifest=AMD64_ONLY)

    result = _report_arch(tmp_path)

    assert "No arm64 manifest for example/amd64-only:1" in result.stdout
    assert "QEMU" in result.stdout


def test_the_temporary_anonymous_config_is_cleaned_up(tmp_path: Path) -> None:
    log = _stub_docker(tmp_path, images="pgvector/pgvector:pg18", manifest=ARM64_INDEX)

    _report_arch(tmp_path)

    config_dir = log.read_text().splitlines()[0].rsplit("DOCKER_CONFIG=", 1)[1]
    assert not Path(config_dir).exists()


def test_a_successful_check_does_not_abort_a_set_e_script(tmp_path: Path) -> None:
    """The regression that would have shipped: under install.sh's `set -e`,
    `wait` on the killed watcher returned 143 and ended the install, on the
    happy path, right after printing that every image was native."""
    _stub_docker(tmp_path, images="pgvector/pgvector:pg18", manifest=ARM64_INDEX)
    script_tail = "\necho REACHED_THE_END\n"
    install = shlex.quote(str(INSTALL_SH))
    result = subprocess.run(
        [
            "bash",
            "-c",
            "set -euo pipefail\n"
            'ok() { echo "OK: $*"; }; info() { :; }; warn() { :; }\n'
            f"eval \"$(sed -n '/^report_arch()/,/^}}/p;/^run_with_timeout()/,/^}}/p' {install})\"\n"
            "ARCH=arm64; COMPOSE_CMD=(docker compose); COMPOSE_FILES=(-f docker-compose.yml)\n"
            "report_arch" + script_tail,
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}"},
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert "REACHED_THE_END" in result.stdout
