"""The cloud reference stack boots with the configuration it ships.

`deploy/docker-compose.prod.yml` had never been started by anything in CI, and
when it finally was it did not come up. Following the documented steps exactly:

* every replica crash-looped at import -- `deploy/.env.example` shipped
  `API_KEYS=conductor:change-me`, and the server parses `API_KEYS` as a JSON
  list: `error parsing value for field "api_keys"`;
* with that fixed, every replica exited at startup -- `ROUTER_API_KEY is
  unset`, a requirement the dev stack and installer had carried for a long
  time and this file was never told about;
* the "hot-standby replica" had never replicated -- `init-replication.sh`
  needs `REPLICATION_PASSWORD`, the primary was never given it, the script
  aborted on its first line, and the entrypoint carried on so the primary
  still reported healthy while the replica retried `pg_basebackup` forever.

Each of those is the same failure: the stack drifted from requirements that
live elsewhere, because nothing compared them. These tests make the comparison
from the requirements' own source -- the server's real `Settings` and
`_validate_startup`, and the `${VAR:?}` guards in the init script -- so the
next requirement added to either fails here rather than on a first deploy.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from tests._compose_render import _render

ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "deploy" / "docker-compose.prod.yml"
ENV_EXAMPLE = ROOT / "deploy" / ".env.example"
INIT_REPLICATION = ROOT / "deploy" / "init-replication.sh"


def _example_env() -> dict[str, str]:
    """`deploy/.env.example` exactly as a user copies it: every uncommented line."""
    values: dict[str, str] = {}
    for raw in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def _replicas(rendered: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    return {name: env for name, env in rendered.items() if name.startswith("maistro-server")}


def test_the_example_env_renders_the_whole_stack() -> None:
    """Copying the template and running `up` must not stop at interpolation --
    every `${VAR:?}` the compose file demands has a line in the template."""
    rendered = _render(PROD, _example_env())

    assert _replicas(rendered), "no maistro-server replicas in the prod stack"


def test_the_example_api_keys_parse_as_the_server_parses_them() -> None:
    """The first crash: the server reads API_KEYS as JSON, the template did not."""
    api_keys = _example_env()["API_KEYS"]

    parsed = json.loads(api_keys)

    assert isinstance(parsed, list) and parsed, api_keys
    assert all(isinstance(e, str) and ":" in e for e in parsed), (
        "each entry must name its principal (#843)"
    )


@pytest.fixture
def replica_environment(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """A replica's environment as rendered from the shipped template.

    The process environment is cleared of anything the server reads first, so
    the result reflects the compose file alone rather than whatever the test
    runner happens to export.
    """
    env = next(iter(_replicas(_render(PROD, _example_env())).values()))
    for key in list(os.environ):
        if re.match(r"^(API_KEYS|ROUTER_API_KEY|REQUIRE_|DB_|DATABASE_URL|LITELLM_|MAISTRO_)", key):
            monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return env


@pytest.mark.usefixtures("replica_environment")
def test_every_replica_passes_the_servers_own_startup_validation() -> None:
    """The second crash, and every future one of its kind.

    Uses the server's real Settings and `_validate_startup`, not a list of
    names copied from them: a requirement added to startup validation fails
    this test until the cloud stack provides it.
    """
    from maistro.config.settings import Settings
    from maistro_server.main import _validate_startup

    _validate_startup(Settings())


@pytest.mark.usefixtures("replica_environment")
def test_every_replica_reaches_postgres_rather_than_the_in_process_store() -> None:
    """No database URL is not an error -- the server quietly runs in memory.

    For a stack whose point is shared state across replicas, that would be
    the worst available failure, so the resolved URL is checked directly.
    """
    from maistro.config.database import resolve_database_url

    assert resolve_database_url().startswith("postgresql"), resolve_database_url()


def test_the_primary_is_given_everything_its_init_script_requires() -> None:
    """The replication failure, derived from the script's own guards.

    Every `${VAR:?...}` in init-replication.sh must reach the primary's
    environment, or the script aborts on its first line and the hot standby
    never gets a role to log in as.
    """
    required = set(re.findall(r"\$\{([A-Z_][A-Z0-9_]*):\?", INIT_REPLICATION.read_text()))
    assert required, (
        "the init script declares no required variables; this check would prove nothing"
    )

    primary = _render(PROD, _example_env())["postgres-primary"]

    assert required <= primary.keys(), (
        f"not passed to postgres-primary: {sorted(required - primary.keys())}"
    )


def test_the_replica_logs_in_with_the_same_password_the_primary_creates() -> None:
    rendered = _render(PROD, _example_env())

    assert (
        rendered["postgres-replica"]["PGPASSWORD"]
        == rendered["postgres-primary"]["REPLICATION_PASSWORD"]
    )


def test_the_load_balancer_bounds_a_dead_replica() -> None:
    """With one replica stopped, half of all requests used to hang.

    A stopped container does not refuse connections, it never answers, so
    nginx waited out the 60s default connect timeout before it could retry
    the healthy replica -- and without a shared zone each worker counted
    failures separately, so ejection took three failures per worker.
    """
    conf = (ROOT / "deploy" / "nginx.conf").read_text()
    upstream = conf[
        conf.index("upstream maistro_backend") : conf.index(
            "}", conf.index("upstream maistro_backend")
        )
    ]

    assert re.search(r"^\s*zone\s+\S+\s+\S+;", upstream, re.M), "failure counts are per-worker"
    connect = re.search(r"proxy_connect_timeout\s+(\d+)s;", conf)
    assert connect and int(connect.group(1)) <= 5, "a dead replica's connect() can hang for 60s"
    assert re.search(r"proxy_next_upstream\s+[^;]*\berror\b[^;]*\btimeout\b", conf)
