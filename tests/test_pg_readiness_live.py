"""Live PostgreSQL characterization of the #339 readiness contract.

The static pins in `tests/test_pg_readiness_compose.py` hold the shape; this
module proves the *behavior* on the production image (`pgvector/pgvector:pg18`)
inside throwaway Docker containers — no live database, no shared state, every
container and volume created here is removed here. Skipped unless Docker is
reachable (set `MAISTRO_PG_READINESS_DOCKER=0` to skip explicitly).

Everything under test is read from the shipped files — the healthcheck
command, its intervals, the `postgres-init` one-shot script and `init-db.sql`
are extracted from `docker-compose.yml` / `init-db.sql`, never re-typed here —
so these tests exercise the configuration the stack ships, not a parallel
copy of it.

Four properties, each demanded by #339's acceptance:

1. **First boot never reports ready mid-initialization.** The image
   entrypoint's temporary server (unix socket, `listen_addresses=''`)
   answers the OLD socket probe for the whole init window — measured here —
   while the new TCP+credentials+query healthcheck stays not-ready until the
   final server is up, and the `postgres-init` one-shot then succeeds.
2. **Interrupted initialization completes on restart.** A container killed
   mid-init-script leaves a half-initialized cluster; the entrypoint never
   re-runs `initdb.d` on non-empty PGDATA, so recovery must come from the
   one-shot re-running the idempotent `init-db.sql` — and it does.
3. **Wrong credentials fail closed with diagnostics.** A volume initialized
   with one password and a container started with another stays not-ready —
   the server answers (server-ready) while the authenticated query is
   refused (application-not-ready), and the health log says which is which.
4. **An existing volume restarts healthy.** The second boot of an
   initialized cluster is healthy quickly, the one-shot is a no-op that
   still succeeds, and the databases still answer.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.yml"
INIT_SQL = ROOT / "init-db.sql"

_DOC: dict[str, Any] = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
_PG = _DOC["services"]["postgres"]
_INIT = _DOC["services"]["postgres-init"]

#: `${POSTGRES_IMAGE:-pgvector/pgvector:pg18}` -> the default, which is what
#: an operator without a .env override runs.
_IMAGE_MATCH = re.fullmatch(r"\$\{[A-Za-z_][A-Za-z0-9_]*:-(.+)\}", str(_PG["image"]))
IMAGE = _IMAGE_MATCH.group(1) if _IMAGE_MATCH else str(_PG["image"])

#: The shipped healthcheck, with `$$` unescaped the way Compose does at
#: apply time: the password expands inside the container.
HEALTH_CMD = _PG["healthcheck"]["test"][1].replace("$$", "$")
HEALTH_INTERVAL = str(_PG["healthcheck"]["interval"])
HEALTH_TIMEOUT = str(_PG["healthcheck"]["timeout"])
HEALTH_RETRIES = str(_PG["healthcheck"]["retries"])
HEALTH_START_PERIOD = str(_PG["healthcheck"]["start_period"])

#: The shipped one-shot script, verbatim.
INIT_SCRIPT = _INIT["command"][0]

PGDATA = str(_PG["environment"]["PGDATA"])
PG_USER = str(_PG["environment"]["POSTGRES_USER"])
PG_DB = str(_PG["environment"]["POSTGRES_DB"])

PASSWORD = "readiness-test-password-339"
WRONG_PASSWORD = "a-different-password-339"

REQUIRED_DBS = ("litellm", "langfuse", "openwebui")


def _docker_reachable() -> bool:
    try:
        subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return True


pytestmark = [
    pytest.mark.scope("integration"),
    pytest.mark.skipif(
        not _docker_reachable(),
        reason="Docker not reachable; live PostgreSQL readiness characterization needs it",
    ),
    pytest.mark.skipif(
        os.environ.get("MAISTRO_PG_READINESS_DOCKER") == "0",
        reason="MAISTRO_PG_READINESS_DOCKER=0",
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
    """The outputs of the health probes so far — the failure diagnostics."""
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
    raise AssertionError(f"timed out after {timeout}s waiting for: {what}; last state: {last!r}")


def _wait_healthy(container: str, timeout: float = 120.0) -> None:
    _wait(lambda: _health(container) == "healthy", timeout, f"{container} healthy")


def _database_exists(container: str, name: str) -> bool:
    out = _exec(
        container,
        [
            "psql",
            "-U",
            PG_USER,
            "-d",
            PG_DB,
            "-Atc",
            f"SELECT 1 FROM pg_database WHERE datname = '{name}'",
        ],
    )
    return out.strip().endswith("1")


def _start_postgres(
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
        "postgres",
        "-e",
        f"POSTGRES_USER={PG_USER}",
        "-e",
        f"POSTGRES_PASSWORD={password}",
        "-e",
        f"POSTGRES_DB={PG_DB}",
        "-e",
        f"PGDATA={PGDATA}",
        "-v",
        f"{volume}:/var/lib/postgresql",
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
    ]
    if init_dir is not None:
        cmd += ["-v", f"{init_dir}:/docker-entrypoint-initdb.d:ro"]
    cmd.append(IMAGE)
    completed = _run(cmd)
    assert completed.returncode == 0, f"docker run failed: {completed.stderr}"


def _run_init_sidecar(
    *, network: str, password: str, timeout: float = 120.0
) -> subprocess.CompletedProcess[str]:
    """Run the shipped postgres-init one-shot script against `postgres`."""
    return _run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            network,
            "-e",
            f"PGPASSWORD={password}",
            "-v",
            f"{INIT_SQL}:/init-db.sql:ro",
            "--entrypoint",
            "/bin/sh",
            IMAGE,
            "-ec",
            INIT_SCRIPT,
        ],
        timeout=timeout,
    )


@pytest.fixture()
def _stack(tmp_path: Path) -> Iterator[dict[str, Any]]:
    """A per-test network plus tracked containers/volumes, all removed after.

    Every test boots its own `postgres`-aliased container; a shared network
    would round-robin the alias between them and send one test's sidecar and
    health probes to another test's cluster.
    """
    network = f"m339-net-{tmp_path.name[-12:]}"
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


def _init_dir(
    tmp_path: Path, name: str, extra: str | None = None, *, include_real: bool = True
) -> Path:
    """A docker-entrypoint-initdb.d directory, plus an optional extra script
    (alphabetically last) that widens or interrupts the initialization window
    for the scenario under test.

    ``include_real=False`` seeds ONLY the scenario script — for the
    interrupted-init scenario, which must simulate a first boot that died
    partway through a *partial* init file, not one that completed the real
    one first.
    """
    directory = tmp_path / name
    directory.mkdir()
    if include_real:
        shutil.copy(INIT_SQL, directory / "init-db.sql")
    if extra is not None:
        (directory / "zz-scenario.sql").write_text(extra, encoding="utf-8")
    return directory


def test_first_boot_ready_only_after_initialization_completes(
    _stack: dict[str, Any], tmp_path: Path
) -> None:
    """The temporary init server answers the old probe; the new one waits.

    `zz-scenario.sql` parks the entrypoint's temporary server for a
    measurable window AFTER init-db.sql created the databases: during that
    window a socket `pg_isready` (the pre-#339 healthcheck) reports
    accepting while the TCP+credentials+query probe cannot — proving the
    shipped healthcheck cannot report ready mid-bootstrap, and that the
    one-shot succeeds once initialization is actually complete.
    """
    container = f"{_stack['network']}-first-boot"
    _stack["containers"].append(container)
    init_dir = _init_dir(tmp_path, "first-boot", extra="\\! sleep 8")
    _start_postgres(
        container,
        network=_stack["network"],
        volume=_fresh_volume(_stack, "first-boot"),
        password=PASSWORD,
        init_dir=init_dir,
    )

    # Observe the temporary-server window: socket accepting, TCP refusing.
    saw_temp_window = False
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline and _health(container) != "healthy":
        socket_probe = _exec(container, ["pg_isready", "-U", PG_USER])
        tcp_probe = _exec(container, ["pg_isready", "-U", PG_USER, "-h", "postgres"])
        if "accepting" in socket_probe and "no response" in tcp_probe:
            saw_temp_window = True
            assert _health(container) != "healthy", (
                "the temporary initialization server answers the socket probe "
                "(the pre-#339 healthcheck would have reported ready) but the "
                "shipped healthcheck must stay not-ready until it completes"
            )
        time.sleep(0.5)
    assert saw_temp_window, (
        "never observed the temporary-server window (socket accepting, TCP "
        "refusing); the scenario is inconclusive"
    )

    _wait_healthy(container)
    # Initialization completed: every required database answers.
    for db in REQUIRED_DBS:
        assert _database_exists(container, db), f"{db} missing after first boot"
    sidecar = _run_init_sidecar(network=_stack["network"], password=PASSWORD)
    assert sidecar.returncode == 0, f"postgres-init failed on a clean cluster: {sidecar.stderr}"


def test_interrupted_initialization_completes_on_restart(
    _stack: dict[str, Any], tmp_path: Path
) -> None:
    """Kill mid-init, restart: the one-shot completes what was interrupted.

    The scenario script creates litellm and then parks inside the init
    window; a SIGKILL there leaves a non-empty PGDATA with half the
    databases. The entrypoint never re-runs initdb.d on restart, so without
    the one-shot the missing databases would never appear and the service
    needing them would crash-loop forever.
    """
    container = f"{_stack['network']}-interrupted"
    _stack["containers"].append(container)
    volume = _fresh_volume(_stack, "interrupted")
    # Only litellm is created before the kill; langfuse/openwebui never were.
    # No real init-db.sql here: the scenario must die inside a PARTIAL init,
    # not after the real one already completed.
    scenario = "CREATE DATABASE litellm;\n\\! sleep 25\nCREATE DATABASE langfuse;\n"
    init_dir = _init_dir(tmp_path, "interrupted", extra=scenario, include_real=False)
    _start_postgres(
        container, network=_stack["network"], volume=volume, password=PASSWORD, init_dir=init_dir
    )

    # Wait until litellm is committed, then kill mid-script (inside the sleep).
    _wait(lambda: _database_exists(container, "litellm"), 90, "litellm created before the kill")
    _run(["docker", "kill", container])
    _run(["docker", "start", container])

    # The restarted server is healthy for the application endpoint (maistro
    # answers), but the cluster is still half-initialized.
    _wait_healthy(container)
    assert not _database_exists(container, "langfuse"), (
        "langfuse should not exist yet: the entrypoint skipped initdb.d on the "
        "non-empty cluster, so only the one-shot can complete initialization"
    )

    # The shipped one-shot completes it, and the completion marker is honest.
    sidecar = _run_init_sidecar(network=_stack["network"], password=PASSWORD)
    assert sidecar.returncode == 0, (
        f"postgres-init did not complete the interrupted init: {sidecar.stderr}"
    )
    for db in REQUIRED_DBS:
        assert _database_exists(container, db), f"{db} missing after recovery"


def test_wrong_credentials_fail_closed_with_diagnostics(
    _stack: dict[str, Any], tmp_path: Path
) -> None:
    """A password mismatch is a readiness failure, not a dependent crash-loop.

    The volume is initialized with one password and the container restarted
    with another. The server itself answers (server-ready) — but the
    authenticated application probe is refused, so the healthcheck stays
    not-ready and the failure names the credential, which is the
    server-ready versus application-ready diagnostic #339 asks for.
    """
    container = f"{_stack['network']}-wrong-credentials"
    _stack["containers"].append(container)
    volume = _fresh_volume(_stack, "wrong-credentials")
    init_dir = _init_dir(tmp_path, "wrong-credentials")
    _start_postgres(
        container, network=_stack["network"], volume=volume, password=PASSWORD, init_dir=init_dir
    )
    _wait_healthy(container)

    # Same volume, different password: what a stale .env produces. The
    # unclean shutdown puts the server briefly into recovery ("rejecting");
    # wait for it to answer before asserting what readiness means.
    _run(["docker", "rm", "-f", container])
    _start_postgres(container, network=_stack["network"], volume=volume, password=WRONG_PASSWORD)
    _wait(
        lambda: "accepting" in _exec(container, ["pg_isready", "-U", PG_USER, "-h", "postgres"]),
        90,
        "server answering after restart",
    )

    # The server answers; the application probe must not. Three probe
    # intervals (15s at the shipped 5s interval) is sustained not-ready,
    # and the auth failure reaches the health log on the first probe.
    deadline = time.monotonic() + 15
    saw_auth_failure = False
    while time.monotonic() < deadline:
        assert _health(container) != "healthy", (
            "wrong credentials must not read as healthy: every dependent "
            "service would start and crash-loop on authentication"
        )
        server_probe = _exec(container, ["pg_isready", "-U", PG_USER, "-h", "postgres"])
        assert "accepting" in server_probe, "server itself should answer (server-ready)"
        if "password authentication failed" in _health_log(container):
            saw_auth_failure = True
        time.sleep(1.0)
    assert saw_auth_failure, (
        "the health log must name the credential failure — that is the "
        "server-ready versus application-ready diagnostic"
    )

    # The one-shot fails the same way, fail-closed, with the same diagnostic.
    sidecar = _run_init_sidecar(network=_stack["network"], password=WRONG_PASSWORD)
    assert sidecar.returncode != 0, "postgres-init must not succeed with wrong credentials"
    assert "password authentication failed" in sidecar.stderr


def test_existing_volume_restarts_healthy_and_init_is_a_noop(
    _stack: dict[str, Any], tmp_path: Path
) -> None:
    """Second boot of an initialized cluster: healthy, idempotent, intact."""
    container = f"{_stack['network']}-existing-volume"
    _stack["containers"].append(container)
    volume = _fresh_volume(_stack, "existing-volume")
    init_dir = _init_dir(tmp_path, "existing-volume")
    _start_postgres(
        container, network=_stack["network"], volume=volume, password=PASSWORD, init_dir=init_dir
    )
    _wait_healthy(container)
    _run_init_sidecar(network=_stack["network"], password=PASSWORD)

    _run(["docker", "restart", container])
    _wait_healthy(container)
    for db in REQUIRED_DBS:
        assert _database_exists(container, db), f"{db} lost across restart"
    # Re-running the one-shot on the initialized cluster is a no-op that
    # still succeeds — the marker survives restarts.
    sidecar = _run_init_sidecar(network=_stack["network"], password=PASSWORD)
    assert sidecar.returncode == 0, f"idempotent re-run failed: {sidecar.stderr}"
