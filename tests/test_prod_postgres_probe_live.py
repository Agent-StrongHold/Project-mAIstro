"""Live characterization of the prod stack's postgres-primary probe (#2396).

The static pins in `tests/test_prod_postgres_probe.py` hold the shape; this
module proves the *behavior* of the production primary's healthcheck on its
real image (`pgvector/pgvector:pg17`), reading the healthcheck command,
intervals, environment, and init script from `deploy/docker-compose.prod.yml`
— never re-typed here. Only the postgres-primary service runs (the prod stack
as a whole needs engine builds and a gateway; the probe under test is this
service's), inside throwaway Docker containers that this module removes.

Three properties:

1. **First boot never reports ready mid-initialization.** The entrypoint's
   temporary server answers the OLD socket probe for the whole init window —
   on this stack that window covers `init-replication.sh` creating the
   `replicator` role the replica's pg_basebackup logs in as — while the
   TCP+credentials+query probe stays not-ready. Once healthy, the replicator
   role exists: healthy implies the init script's effects are present.
2. **Wrong credentials fail closed with diagnostics.** A volume initialized
   with one password and a container started with another stays not-ready —
   the server answers (server-ready) while the authenticated query is refused
   (application-not-ready), and the health log names the credential.
3. **An existing volume restarts healthy.** The second boot of an initialized
   cluster is healthy quickly and the replicator role survives.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "deploy" / "docker-compose.prod.yml"
INIT_SCRIPT = ROOT / "deploy" / "init-replication.sh"

_DOC: dict[str, Any] = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
_PRIMARY = _DOC["services"]["postgres-primary"]

_IMAGE = re.fullmatch(r"[\w./:-]+", str(_PRIMARY["image"]))
assert _IMAGE
IMAGE = _IMAGE.group(0)

#: The shipped healthcheck with `$$` unescaped the way Compose does at apply
#: time: user, password, and database expand inside the container.
HEALTH_CMD = _PRIMARY["healthcheck"]["test"][1].replace("$$", "$")
HEALTH_INTERVAL = str(_PRIMARY["healthcheck"]["interval"])
HEALTH_TIMEOUT = str(_PRIMARY["healthcheck"]["timeout"])
HEALTH_RETRIES = str(_PRIMARY["healthcheck"]["retries"])
HEALTH_START_PERIOD = str(_PRIMARY["healthcheck"]["start_period"])

PASSWORD = "prod-probe-password-2396"
WRONG_PASSWORD = "a-different-password-2396"
REPLICATION_PASSWORD = "replication-probe-password-2396"

#: The prod primary's defaults (its environment parameterizes these; the
#: rendered defaults are what an operator without overrides runs).
PG_USER = "maistro"
PG_DB = "maistro"


def _docker_reachable() -> bool:
    try:
        subprocess.run(["docker", "info"], capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return True


pytestmark = [
    pytest.mark.scope("integration"),
    pytest.mark.skipif(
        not _docker_reachable(),
        reason="Docker not reachable; live prod-probe characterization needs it",
    ),
    pytest.mark.skipif(
        os.environ.get("MAISTRO_PROD_PROBE_DOCKER") == "0",
        reason="MAISTRO_PROD_PROBE_DOCKER=0",
    ),
]


def _run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def _exec(container: str, argv: list[str]) -> str:
    completed = _run(["docker", "exec", container, *argv])
    return completed.stdout + completed.stderr


def _health(container: str) -> str:
    completed = _run(
        [
            "docker",
            "inspect",
            "--format",
            "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
            container,
        ]
    )
    return completed.stdout.strip()


def _health_log(container: str) -> str:
    completed = _run(
        [
            "docker",
            "inspect",
            "--format",
            "{{range .State.Health.Log}}{{.Output}}{{end}}",
            container,
        ]
    )
    return completed.stdout


def _wait(predicate: Any, timeout: float, what: str) -> None:
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        last = predicate()
        if last:
            return
        time.sleep(0.5)
    raise AssertionError(f"timed out after {timeout}s waiting for: {what}; last: {last!r}")


def _wait_healthy(container: str, timeout: float = 120.0) -> None:
    _wait(lambda: _health(container) == "healthy", timeout, f"{container} healthy")


def _role_exists(container: str, role: str) -> bool:
    out = _exec(
        container,
        [
            "psql",
            "-U",
            PG_USER,
            "-d",
            PG_DB,
            "-Atc",
            f"SELECT 1 FROM pg_roles WHERE rolname = '{role}'",
        ],
    )
    return out.strip().endswith("1")


def _start_primary(
    name: str,
    *,
    network: str,
    volume: str,
    password: str,
    init_dir: Path | None = None,
) -> None:
    cmd = [
        "docker",
        "run",
        "-d",
        "--name",
        name,
        "--network",
        network,
        "--network-alias",
        "postgres-primary",
        "-e",
        f"POSTGRES_USER={PG_USER}",
        "-e",
        f"POSTGRES_PASSWORD={password}",
        "-e",
        f"POSTGRES_DB={PG_DB}",
        "-e",
        f"REPLICATION_PASSWORD={REPLICATION_PASSWORD}",
        "-e",
        "POSTGRES_INITDB_ARGS=--data-checksums",
        "-v",
        f"{volume}:/var/lib/postgresql/data",
    ]
    if init_dir is not None:
        cmd += ["-v", f"{init_dir}:/docker-entrypoint-initdb.d:ro"]
    else:
        cmd += ["-v", f"{INIT_SCRIPT}:/docker-entrypoint-initdb.d/init-replication.sh:ro"]
    cmd += [
        "--health-cmd",
        HEALTH_CMD,
        "--health-interval",
        HEALTH_INTERVAL,
        "--health-timeout",
        HEALTH_TIMEOUT,
        "--health-retries",
        HEALTH_RETRIES,
        "--health-start-period",
        HEALTH_START_PERIOD,
        IMAGE,
    ]
    completed = _run(cmd)
    assert completed.returncode == 0, f"docker run failed: {completed.stderr}"


@pytest.fixture()
def _stack(tmp_path: Path) -> Iterator[dict[str, Any]]:
    """A per-test network plus tracked containers/volumes, all removed after."""
    network = f"m2396-net-{tmp_path.name[-12:]}"
    _run(["docker", "network", "create", network])
    made: dict[str, Any] = {"network": network, "containers": [], "volumes": []}
    yield made
    for container in made["containers"]:
        _run(["docker", "rm", "-f", container])
    for volume in made["volumes"]:
        _run(["docker", "volume", "rm", "-f", volume])
    _run(["docker", "network", "rm", network])


def _fresh_volume(_stack: dict[str, Any], name: str) -> str:
    volume = f"{_stack['network']}-{name}"
    _run(["docker", "volume", "create", volume])
    _stack["volumes"].append(volume)
    return volume


def test_first_boot_ready_only_after_init_completed(_stack: dict[str, Any], tmp_path: Path) -> None:
    """The temp-server window answers the old probe; the new one waits — and
    healthy implies the replicator role init-replication.sh creates exists.

    The window is widened the way the local stack's live test widens its own:
    a copy of init-replication.sh with a sleep appended AFTER the role
    creation, so the temporary server is observably the only listener while
    the init script's effects already exist — proving the probe waits for the
    FINAL server, not for the artifacts.
    """
    container = f"{_stack['network']}-first-boot"
    _stack["containers"].append(container)
    # A copy of the shipped script with the window widened, in its own
    # initdb.d directory (a directory bind, like the #339 live tests: a
    # single-file bind from a macOS tmpdir fails interpreter execution),
    # executable like the original. The role creation itself is untouched.
    init_dir = tmp_path / "initdb"
    init_dir.mkdir()
    widened = init_dir / "init-replication.sh"
    widened.write_text(INIT_SCRIPT.read_text(encoding="utf-8") + "\nsleep 8\n", encoding="utf-8")
    widened.chmod(0o755)
    _start_primary(
        container,
        network=_stack["network"],
        volume=_fresh_volume(_stack, "first-boot"),
        password=PASSWORD,
        init_dir=init_dir,
    )
    saw_temp_window = False
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline and _health(container) != "healthy":
        socket_probe = _exec(container, ["pg_isready", "-U", PG_USER])
        tcp_probe = _exec(container, ["pg_isready", "-U", PG_USER, "-h", "postgres-primary"])
        if "accepting" in socket_probe and "no response" in tcp_probe:
            saw_temp_window = True
            assert _health(container) != "healthy", (
                "the temporary initialization server answers the socket probe "
                "(the pre-#2396 healthcheck would have reported ready) but the "
                "shipped probe must stay not-ready until the final server is up"
            )
        time.sleep(0.5)
    assert saw_temp_window, (
        "never observed the temporary-server window (socket accepting, TCP "
        "refusing); the scenario is inconclusive"
    )

    _wait_healthy(container)
    # Healthy means the application endpoint answers AND the init script's
    # artifact is present: the replicator role the replica's pg_basebackup
    # needs. This is the property the replica's dependency relies on.
    assert _role_exists(container, "replicator"), (
        "primary reported healthy but the replicator role from "
        "init-replication.sh does not exist — healthy must imply init completed"
    )


def test_wrong_credentials_fail_closed_with_diagnostics(_stack: dict[str, Any]) -> None:
    """A password mismatch is a readiness failure named in the health log."""
    container = f"{_stack['network']}-wrong-credentials"
    _stack["containers"].append(container)
    volume = _fresh_volume(_stack, "wrong-credentials")
    _start_primary(container, network=_stack["network"], volume=volume, password=PASSWORD)
    _wait_healthy(container)

    # Same volume, different password: what a stale .env produces.
    _run(["docker", "rm", "-f", container])
    _start_primary(container, network=_stack["network"], volume=volume, password=WRONG_PASSWORD)

    _wait(
        lambda: (
            "accepting" in _exec(container, ["pg_isready", "-U", PG_USER, "-h", "postgres-primary"])
        ),
        90,
        "server answering after restart",
    )
    deadline = time.monotonic() + 15
    saw_auth_failure = False
    while time.monotonic() < deadline:
        assert _health(container) != "healthy", (
            "wrong credentials must not read as healthy: the replica and both "
            "engines would start and crash-loop on authentication"
        )
        if "password authentication failed" in _health_log(container):
            saw_auth_failure = True
        time.sleep(1.0)
    assert saw_auth_failure, (
        "the health log must name the credential failure — that is the "
        "server-ready versus application-ready diagnostic"
    )


def test_existing_volume_restarts_healthy(_stack: dict[str, Any]) -> None:
    """Second boot of an initialized cluster: healthy, replicator role intact."""
    container = f"{_stack['network']}-existing-volume"
    _stack["containers"].append(container)
    volume = _fresh_volume(_stack, "existing-volume")
    _start_primary(container, network=_stack["network"], volume=volume, password=PASSWORD)
    _wait_healthy(container)
    assert _role_exists(container, "replicator")

    _run(["docker", "restart", container])
    _wait_healthy(container)
    assert _role_exists(container, "replicator"), "replicator role lost across restart"
