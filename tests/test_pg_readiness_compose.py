"""#339: PostgreSQL readiness in the shipped Conductor Compose stack.

The static pins here mirror the shape `tests/test_backup_restore_oracle.py`
established for the same defect class elsewhere: the postgres image's init
entrypoint runs a *temporary* server on the unix socket
(``listen_addresses=''``) before the application databases exist, and a
socket ``pg_isready`` answers inside that window — so a socket-keyed
healthcheck marked the stack healthy mid-bootstrap and LiteLLM and Langfuse
started against databases that did not exist yet (measured live in
``tests/test_pg_readiness_live.py``: socket accepting, TCP refusing, for the
whole temporary-server window).

Three properties, each pinned structurally so the shape cannot silently
regress:

1. The ``postgres`` healthcheck probes the application endpoint over TCP to
   the service's own network address (the temporary server never listens on
   TCP) and executes a real query as the application user with the
   application password — readiness means endpoint + credentials + user +
   database answer, and a wrong ``DB_PASSWORD`` fails in the health log
   instead of as crash-loops in every dependent service.
2. Initialization completes on every ``up``: the ``postgres-init`` one-shot
   re-runs the idempotent ``init-db.sql`` after the server is healthy, so a
   first boot interrupted inside the init script finishes on the next start
   (the image entrypoint never re-runs ``initdb.d`` on a non-empty PGDATA).
3. Every service that connects to PostgreSQL waits for *both* gates:
   ``postgres`` healthy (server + application endpoint) and ``postgres-init``
   completed (every required database exists and answers).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.yml"
INIT_SQL = ROOT / "init-db.sql"

#: The databases `init-db.sql` creates and the sidecar verifies. The live
#: module and the assertions below cross-check this set against both files,
#: so a database added to one but not the other fails here rather than
#: shipping half-initialized.
REQUIRED_DATABASES = ("litellm", "langfuse", "openwebui")

#: The racy probe this issue replaced (#339's fail-before baseline): a socket
#: ``pg_isready`` answers inside the entrypoint's temporary initialization
#: server, before init-db.sql has created the litellm/langfuse databases.
RACY_HEALTHCHECK = ["CMD-SHELL", "pg_isready -U maistro"]


def _doc() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    return loaded


def _healthcheck_cmd(services: dict[str, Any], service: str) -> str:
    test: list[str] = services[service]["healthcheck"]["test"]
    assert test[0] == "CMD-SHELL", f"{service} healthcheck must stay CMD-SHELL (podman, #1820)"
    return test[1]


def _readiness_violations(cmd: str) -> list[str]:
    """Why a healthcheck command can report ready before initialization is done."""
    violations: list[str] = []
    if "-h postgres" not in cmd:
        violations.append(
            "probe does not go over TCP to the service's own network address: the "
            "init entrypoint's temporary server (socket-only, listen_addresses='') "
            "can satisfy a socket probe before the application databases exist"
        )
    if "psql" not in cmd or "SELECT 1" not in cmd:
        violations.append(
            "probe does not execute a real query against the application database, "
            "so it can pass before the database answers (pg_isready accepts wrong "
            "credentials and nonexistent databases alike)"
        )
    if "PGPASSWORD" not in cmd:
        violations.append(
            "probe does not authenticate with the application password, so a wrong "
            "DB_PASSWORD against an existing volume reads as healthy and every "
            "dependent service crash-loops on auth instead"
        )
    if "$$POSTGRES_PASSWORD" not in cmd:
        violations.append(
            "probe does not defer the password to the container ($$): host-side "
            "interpolation would freeze the value into the rendered file"
        )
    return violations


def test_postgres_healthcheck_probes_the_application_endpoint() -> None:
    """Healthy must mean endpoint + credentials + user + database answer."""
    services = _doc()["services"]
    cmd = _healthcheck_cmd(services, "postgres")
    violations = _readiness_violations(cmd)
    assert violations == [], "postgres healthcheck is racy (#339): " + "; ".join(violations)
    # The probe's user and database are the service's own application
    # coordinates, not a second spelling that can drift.
    env = services["postgres"]["environment"]
    assert f"-U {env['POSTGRES_USER']}" in cmd
    assert f"-d {env['POSTGRES_DB']}" in cmd


def test_racy_socket_probe_baseline_still_fails() -> None:
    """Fail-before: the pinned racy probe must keep failing the checker.

    Without this, the checker above could pass vacuously — a shape check
    nothing racy fails proves nothing about the shape it replaced.
    """
    assert _readiness_violations(RACY_HEALTHCHECK[1]), (
        "fail-before baseline drifted: the pinned socket-only probe is no "
        "longer racy, so the checker has lost its teeth"
    )


def test_postgres_healthcheck_absorbs_slow_first_boot() -> None:
    """A slow initdb must wait, not exhaust the failure budget and abort `up`.

    During start_period a failed probe does not count toward unhealthy (a
    successful probe still marks healthy immediately), so slow storage
    cannot turn a healthy-but-slow first boot into a failed stack — the same
    contract the engine's first-boot migration budget uses.
    """
    healthcheck = _doc()["services"]["postgres"]["healthcheck"]
    start_period = healthcheck.get("start_period")
    assert start_period, "postgres healthcheck needs a start_period for slow first boot"
    match = re.fullmatch(r"(\d+)s", str(start_period))
    assert match, f"unparsable start_period: {start_period!r}"
    assert int(match.group(1)) >= 300, "start_period must absorb a slow initdb (engine uses 300s)"


def _sidecar_verified_databases(script: str) -> set[str]:
    """The databases the one-shot's verification loop queries by name."""
    match = re.search(r"for db in ([\w ]+); do", script)
    assert match, "postgres-init must verify required databases in a named loop"
    return set(match.group(1).split())


def test_postgres_init_completes_initialization_on_every_up() -> None:
    """The one-shot that makes interrupted initialization recoverable.

    The image entrypoint runs ``/docker-entrypoint-initdb.d`` exactly once —
    when PGDATA is empty. A first boot killed inside ``init-db.sql`` leaves a
    non-empty cluster with half the databases and nothing ever re-runs the
    init scripts; the ``postgres-init`` one-shot re-runs the idempotent file
    on every ``up`` so the next start completes.
    """
    services = _doc()["services"]
    init = services.get("postgres-init")
    assert init, "postgres-init one-shot is missing: interrupted init cannot recover"

    # It runs only after the server is application-ready, and it is a
    # one-shot: `restart: "no"` keeps it from becoming a second lifecycle.
    assert init["depends_on"]["postgres"] == {"condition": "service_healthy"}
    assert init["restart"] == '"no"' or init["restart"] == "no", (
        "postgres-init must stay a one-shot, not a supervised lifecycle"
    )

    # It runs the same file the entrypoint runs on first boot — one source
    # of truth for what "initialized" means, mounted read-only.
    volumes = init.get("volumes", [])
    assert "./init-db.sql:/init-db.sql:ro" in volumes, (
        "postgres-init must run the tracked init-db.sql, not a second copy"
    )

    script = "\n".join(init["command"])
    assert "psql" in script and "/init-db.sql" in script, (
        "postgres-init must apply init-db.sql through psql"
    )
    # The completion marker: every required database must answer a real
    # query before the one-shot may succeed — that success is what the
    # dependent services wait on.
    verified = _sidecar_verified_databases(script)
    assert tuple(sorted(verified)) == tuple(sorted(REQUIRED_DATABASES)), (
        f"postgres-init verifies {sorted(verified)}; the required set is "
        f"{sorted(REQUIRED_DATABASES)}"
    )
    assert "SELECT 1" in script, "verification must be a real query, not existence gossip"


def test_every_postgres_consumer_waits_for_completed_initialization() -> None:
    """Dependent services wait for initialization, not just a listening server."""
    services = _doc()["services"]
    consumers = [
        name
        for name, svc in services.items()
        if isinstance(svc.get("depends_on"), dict)
        and "postgres" in svc["depends_on"]
        and name not in ("postgres-init",)
    ]
    assert set(consumers) == {"litellm", "langfuse", "maistro-engine", "hive-conductor"}, (
        f"postgres consumers drifted: {sorted(consumers)}"
    )
    for name in consumers:
        depends = services[name]["depends_on"]
        assert depends.get("postgres") == {"condition": "service_healthy"}, (
            f"{name} must wait for the postgres healthcheck"
        )
        assert depends.get("postgres-init") == {"condition": "service_completed_successfully"}, (
            f"{name} must wait for initialization to complete (#339): the "
            "healthcheck proves the server and application endpoint; the "
            "one-shot proves every required database exists"
        )


def test_init_db_sql_is_idempotent() -> None:
    """The init file must be safe to re-run on a half-initialized cluster.

    CREATE DATABASE has no IF NOT EXISTS form, so each creation is guarded by
    a catalog probe with ``\\gexec``: the statement runs only when the
    database is missing. Extensions use IF NOT EXISTS. Anything else would
    make the recovery path (postgres-init re-running this file after an
    interrupted first boot) fail on the databases that DID get created.
    """
    sql = INIT_SQL.read_text(encoding="utf-8")
    for db in REQUIRED_DATABASES:
        guarded = (
            f"SELECT 'CREATE DATABASE {db}' WHERE NOT EXISTS "
            f"(SELECT FROM pg_database WHERE datname = '{db}')\\gexec"
        )
        assert guarded in sql, (
            f"CREATE DATABASE {db} must be guarded by a pg_database probe + "
            "\\gexec so re-running init-db.sql is a no-op on an initialized "
            "cluster and completes an interrupted one"
        )
    assert "CREATE EXTENSION IF NOT EXISTS vector" in sql
    assert "CREATE EXTENSION IF NOT EXISTS pg_trgm" in sql
    # No unguarded creation can ship alongside the guarded ones: an
    # unguarded CREATE DATABASE would abort the recovery re-run.
    for statement in re.findall(r"^CREATE DATABASE (\w+)", sql, re.M):
        assert statement in REQUIRED_DATABASES, "unguarded CREATE DATABASE in init-db.sql"


def test_sidecar_database_list_matches_init_sql() -> None:
    """The verification list and the creation list are the same set.

    The sidecar verifies databases by name in its shell loop; init-db.sql
    creates them by name in SQL. If the two lists drift, the completion
    marker stops meaning "every required database answers".
    """
    sql = INIT_SQL.read_text(encoding="utf-8")
    created = set(re.findall(r"WHERE datname = '(\w+)'", sql))
    assert created == set(REQUIRED_DATABASES), (
        f"init-db.sql creates {sorted(created)}; the contract is {sorted(REQUIRED_DATABASES)}"
    )
    script = "\n".join(_doc()["services"]["postgres-init"]["command"])
    assert _sidecar_verified_databases(script) == set(REQUIRED_DATABASES), (
        "the sidecar's verification list and init-db.sql's creation list drifted"
    )
