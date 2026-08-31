"""Every PostgreSQL health check names a database its container creates (#689).

`pg_isready` reports the *server* as accepting connections whenever it gets a
response, and "database does not exist" is a response. So a probe naming a
database nothing created passes, the job proceeds green, and the server logs a
`FATAL` per probe for the life of the job. #682 introduced exactly that on the
Quality gate: `POSTGRES_DB: maistro_test`, probed as `pg_isready -U maistro`,
whose implicit database is the *user* name — `maistro`, which is never created.

The cost is not a broken build. It is eight `FATAL` lines in a green log,
teaching every later reader to skim past the word. The next one will be real.

This is a test rather than a one-time correction because the correction is one
character-string per service block and nothing else would notice it coming
back. Scoped to `services:` blocks, which are structured and parseable; the
smoke job's shell-loop probes set `POSTGRES_DB=maistro` and probe `-U maistro`,
so they agree by construction, and a change that broke that would also stop the
engine container connecting — it fails loudly on its own.
"""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"

#: initdb always creates this one, whatever `POSTGRES_DB` says, so a probe
#: naming it is safe in every container.
ALWAYS_PRESENT = "postgres"


def _postgres_services() -> list[tuple[str, str, dict[str, Any]]]:
    found: list[tuple[str, str, dict[str, Any]]] = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for job_name, job in (document.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            for service_name, service in (job.get("services") or {}).items():
                if not isinstance(service, dict):
                    continue
                if "pg_isready" not in str(service.get("options", "")):
                    continue
                found.append((f"{path.name}:{job_name}:{service_name}", path.name, service))
    return found


def _health_command(options: str) -> list[str]:
    """The `--health-cmd` argument, split into its own words.

    Two levels of quoting, and missing the second one made the first version of
    this test vacuous: `--health-cmd "pg_isready -U maistro"` splits into the
    single token `pg_isready -U maistro`, so a scan for `-U` found nothing,
    every service fell back to the always-present default, and the test passed
    against the very defect it was written for. Caught by reverting a probe and
    watching it stay green.
    """
    if "--health-cmd" not in options:
        return []
    tokens = shlex.split(options.split("--health-cmd", 1)[1])
    return shlex.split(tokens[0]) if tokens else []


def _probe_database(options: str, env: dict[str, Any]) -> tuple[str, str]:
    """The database the probe opens, and the one the container creates."""
    tokens = _health_command(options)
    probe_user = ALWAYS_PRESENT
    probe_db = None
    for index, token in enumerate(tokens):
        if token == "-U" and index + 1 < len(tokens):
            probe_user = tokens[index + 1]
        if token == "-d" and index + 1 < len(tokens):
            probe_db = tokens[index + 1]
    # `pg_isready` defaults the database to the connecting user's name, which is
    # the whole of this defect: naming the user is not naming a database.
    created_user = str(env.get("POSTGRES_USER", ALWAYS_PRESENT))
    created_db = str(env.get("POSTGRES_DB", created_user))
    return probe_db or probe_user, created_db


def test_at_least_one_service_is_checked() -> None:
    """A guard that silently matches nothing is not a guard. If the workflows
    stop declaring PostgreSQL services this fails and asks to be retired."""
    assert _postgres_services()


@pytest.mark.parametrize("where, _file, service", _postgres_services())
def test_the_probe_names_a_database_the_container_creates(
    where: str, _file: str, service: dict[str, Any]
) -> None:
    probe_db, created_db = _probe_database(
        str(service.get("options", "")), service.get("env") or {}
    )

    assert probe_db in {created_db, ALWAYS_PRESENT}, (
        f"{where}: the health check opens {probe_db!r}, which this container "
        f"never creates — it creates {created_db!r}. The probe still passes, "
        f"because a refusal is a response, and the server logs FATAL every "
        f"few seconds for the life of the job."
    )


def test_the_health_command_is_split_past_both_levels_of_quoting() -> None:
    """The guard on the parse, not the workflows. This test was green against a
    reverted probe until the inner `shlex.split` went in; without this, the same
    mistake would make every case above pass for the wrong reason."""
    options = '--health-cmd "pg_isready -U maistro -d maistro_test" --health-interval 5s'

    assert _health_command(options) == ["pg_isready", "-U", "maistro", "-d", "maistro_test"]
    assert _probe_database(
        options, {"POSTGRES_USER": "maistro", "POSTGRES_DB": "maistro_test"}
    ) == (
        "maistro_test",
        "maistro_test",
    )
    # And the defect itself: the probe falls back to the user name.
    assert _probe_database(
        '--health-cmd "pg_isready -U maistro"',
        {"POSTGRES_USER": "maistro", "POSTGRES_DB": "maistro_test"},
    ) == ("maistro", "maistro_test")
