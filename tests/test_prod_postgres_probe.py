"""#2396: the production stack's postgres-primary readiness is application-level.

Follow-up to the local stack's #339 fix (PR #2395), discovered during its live
verification: ``deploy/docker-compose.prod.yml``'s ``postgres-primary`` kept
the socket ``pg_isready`` probe shape. The prod stack does NOT have the local
stack's multi-database initdb.d race — its one init script creates the
``replicator`` role, not dependent databases — so this is probe hardening, not
the same defect: a socket probe answers inside the entrypoint's temporary
initialization server (which on this stack covers ``init-replication.sh``),
and it accepts any password, so a wrong ``POSTGRES_PASSWORD`` against an
existing volume read as healthy while the replica's ``pg_basebackup``, both
engines, and the Conductor crash-looped on authentication.

These pins hold the shipped shape; ``tests/test_prod_postgres_probe_live.py``
proves the behavior on the real image.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "deploy" / "docker-compose.prod.yml"

#: The probe this issue replaced (#2396's fail-before baseline): socket-only,
#: host-interpolated user, no query, no credentials.
RACY_PROBE = "pg_isready -U ${POSTGRES_USER:-maistro}"


def _doc() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    return loaded


def _healthcheck_cmd(services: dict[str, Any], service: str) -> str:
    test: list[str] = services[service]["healthcheck"]["test"]
    assert test[0] == "CMD-SHELL", f"{service} healthcheck must stay CMD-SHELL"
    return test[1]


def _probe_violations(cmd: str) -> list[str]:
    violations: list[str] = []
    if "-h postgres-primary" not in cmd:
        violations.append(
            "probe does not go over TCP to the service's own network address: the "
            "init entrypoint's temporary server (socket-only) can satisfy a socket "
            "probe before init-replication.sh has created the replicator role"
        )
    if "psql" not in cmd or "SELECT 1" not in cmd:
        violations.append(
            "probe does not execute a real query against the application database, "
            "so it can pass before the database answers"
        )
    if "$$POSTGRES_PASSWORD" not in cmd:
        violations.append(
            "probe does not authenticate with the application password (deferred to "
            "the container with $$), so a wrong POSTGRES_PASSWORD against an existing "
            "volume reads as healthy and every consumer crash-loops on auth"
        )
    if "$$POSTGRES_USER" not in cmd or "$$POSTGRES_DB" not in cmd:
        violations.append(
            "probe hardcodes or host-interpolates the user/database instead of "
            "reading the container's POSTGRES_USER/POSTGRES_DB — this stack "
            "parameterizes both, and a second spelling can drift"
        )
    return violations


def test_primary_probe_is_application_level() -> None:
    services = _doc()["services"]
    violations = _probe_violations(_healthcheck_cmd(services, "postgres-primary"))
    assert violations == [], "postgres-primary probe is racy (#2396): " + "; ".join(violations)


def test_racy_socket_probe_baseline_still_fails() -> None:
    """Fail-before: the pinned racy probe must keep failing the checker."""
    assert _probe_violations(RACY_PROBE), (
        "fail-before baseline drifted: the pinned socket-only probe is no longer "
        "racy, so the checker has lost its teeth"
    )


def test_primary_probe_absorbs_slow_first_boot() -> None:
    """initdb + init-replication.sh on slow storage must wait, not abort `up`."""
    healthcheck = _doc()["services"]["postgres-primary"]["healthcheck"]
    start_period = healthcheck.get("start_period")
    assert start_period, "postgres-primary healthcheck needs a start_period"
    match = re.fullmatch(r"(\d+)s", str(start_period))
    assert match, f"unparsable start_period: {start_period!r}"
    assert int(match.group(1)) >= 300, "start_period must absorb a slow initdb (#339 uses 300s)"


def test_primary_init_flow_is_untouched() -> None:
    """#2396 hardens the probe only: the replication init script stays as-is."""
    primary = _doc()["services"]["postgres-primary"]
    volumes = primary.get("volumes", [])
    assert any(
        "init-replication.sh" in v and "/docker-entrypoint-initdb.d/" in v for v in volumes
    ), (
        "init-replication.sh must stay mounted at /docker-entrypoint-initdb.d — "
        "this change must not touch the init flow"
    )
    assert "REPLICATION_PASSWORD" in str(primary["environment"]), (
        "the replication password env the init script reads must stay"
    )


def test_every_primary_consumer_waits_for_its_health() -> None:
    services = _doc()["services"]
    consumers = [
        name
        for name, svc in services.items()
        if isinstance(svc.get("depends_on"), dict)
        and svc["depends_on"].get("postgres-primary") == {"condition": "service_healthy"}
    ]
    assert set(consumers) == {
        "postgres-replica",
        "maistro-server-1",
        "maistro-server-2",
        "hive-conductor",
    }, f"postgres-primary consumers drifted: {sorted(consumers)}"


def test_replica_probe_stays_socket_only_by_reviewed_decision() -> None:
    """The replica keeps its socket probe — a reviewed decision, not an oversight.

    The replica has no temporary-server window: it never runs initdb.d (its
    cluster comes from pg_basebackup or an existing PGDATA), so the socket
    probe cannot answer before the final server. And a credential-bearing
    probe would require shipping POSTGRES_PASSWORD into a container whose
    only credential today is the replication password — widening the secret's
    exposure for no race it closes. A password mismatch fails at the PRIMARY's
    probe first, which every replica bootstrap depends on.

    This pin exists so the asymmetry is a decision someone re-reads, not a
    detail nobody notices again.
    """
    services = _doc()["services"]
    replica_cmd = _healthcheck_cmd(services, "postgres-replica")
    assert "pg_isready" in replica_cmd and "-h" not in replica_cmd, (
        "if the replica probe changes, re-read the reviewed decision above: "
        "the replica has no initdb.d window, and a psql probe would need "
        "POSTGRES_PASSWORD in the replica's environment"
    )
