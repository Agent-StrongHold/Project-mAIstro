"""Workspace cutover P0.9: the Sentinel permission table is armed in every deploy profile.

A deploy profile here is a shipped Compose stack, and each engine-bearing
service in it is a composition root that builds a Sentinel: `maistro-server`
from `maistro.yaml`'s `security` section (`_security_config`), and the
Conductor's embedded container from `MAISTRO_PERMISSION_PRESET` /
`MAISTRO_PERMISSIONS` (`adapters/maistro_core.py`). Each service's environment
is rendered from the compose file as `docker compose` would, then fed through
that service's own config path.

Sentinel is fail-closed on a table miss (ADR-072726-0d6b, #1165), so an empty
table denies every tool rather than allowing it -- but "armed" means the
deployment states some tool authority, and today none does. Every profile is
in `KNOWN_GAPS`, asserting the empty table, so arming one fails this test
until its entry is deleted.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

from maistro.config import settings as settings_module
from maistro.config.loader import load_yaml_config
from maistro.security._types import PermissionTable
from maistro.security.permission_policy import build_permission_table
from maistro_server.main import _security_config
from tests._compose_render import MissingRequired, _environment

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "packages" / "hive-conductor" / "backend")
)

from config import Settings as HiveSettings

ROOT = Path(__file__).resolve().parents[2]
DEV = ROOT / "docker-compose.yml"
PM_POC = ROOT / "docker-compose.pm-poc.yml"
PROD = ROOT / "deploy" / "docker-compose.prod.yml"
PROD_ENV_EXAMPLE = ROOT / "deploy" / ".env.example"
HIVE_STANDALONE = ROOT / "packages" / "hive-conductor" / "docker-compose.yml"

#: Every profile builds an empty table today. Refs #66 (Sentinel armed on every
#: real path); the Workspace deploy (#804) inherits whichever profile it ships on.
KNOWN_GAPS: frozenset[str] = frozenset(
    {
        "dev:maistro-engine",  # Refs #66
        "dev:hive-conductor",  # Refs #66
        "pm-poc:maistro-engine",  # Refs #66
        "pm-poc:hive-conductor",  # Refs #66
        "cloud-prod:maistro-server-1",  # Refs #66
        "cloud-prod:maistro-server-2",  # Refs #66
        "hive-standalone:hive-conductor",  # Refs #66
    }
)

#: Process variables either composition root reads, cleared so the result
#: reflects the compose file alone.
_READ_BY_ROOTS = re.compile(
    r"^(MAISTRO_|API_KEYS|ROUTER_API_KEY|JWT_SECRET|LITELLM_|DATABASE_URL|DB_|REQUIRE_|CORS_)"
)

_PLACEHOLDER = "compose-placeholder-value-0000000000000000"


def _example_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def _render_services(
    files: tuple[Path, ...], host_env: dict[str, str]
) -> dict[str, dict[str, str]]:
    """Each service's environment across `-f` files, later files overriding.

    A `${VAR:?}` the host leaves unset is given a placeholder: the question
    here is what the stack states about permissions, not whether the
    operator filled in every secret.
    """
    env = dict(host_env)
    while True:
        try:
            rendered: dict[str, dict[str, str]] = {}
            for path in files:
                doc = yaml.safe_load(path.read_text(encoding="utf-8"))
                for name, service in doc["services"].items():
                    rendered.setdefault(name, {}).update(_environment(service, env))
            return rendered
        except MissingRequired as missing:
            env[str(missing).partition(":")[0]] = _PLACEHOLDER


def _apply_service_env(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for key in list(os.environ):
        if _READ_BY_ROOTS.match(key):
            monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def _server_table(env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> PermissionTable:
    """`maistro-server`'s table: its YAML config, then `_security_config`.

    The image copies no `config/` directory, so the path resolves against the
    repository the image is built from.
    """
    _apply_service_env(monkeypatch, env)
    monkeypatch.setattr(settings_module, "_yaml_config", None)
    load_yaml_config(ROOT / env.get("MAISTRO_CONFIG", "config/maistro.yaml"))
    security = _security_config()
    return build_permission_table(
        preset=security.permission_preset, permissions=security.permissions
    )


def _hive_table(env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> PermissionTable:
    """The Conductor's table: its `Settings`, as `adapters/maistro_core.py` passes them."""
    _apply_service_env(monkeypatch, env)
    settings = HiveSettings(_env_file=None)
    return build_permission_table(
        preset=settings.maistro_permission_preset, permissions=settings.maistro_permissions
    )


_TableBuilder = Callable[[dict[str, str], pytest.MonkeyPatch], PermissionTable]

#: profile id -> (compose files, host env, service, composition root).
PROFILES: dict[str, tuple[tuple[Path, ...], Callable[[], dict[str, str]], str, _TableBuilder]] = {
    "dev:maistro-engine": ((DEV,), dict, "maistro-engine", _server_table),
    "dev:hive-conductor": ((DEV,), dict, "hive-conductor", _hive_table),
    "pm-poc:maistro-engine": ((DEV, PM_POC), dict, "maistro-engine", _server_table),
    "pm-poc:hive-conductor": ((DEV, PM_POC), dict, "hive-conductor", _hive_table),
    "cloud-prod:maistro-server-1": (
        (PROD,),
        lambda: _example_env(PROD_ENV_EXAMPLE),
        "maistro-server-1",
        _server_table,
    ),
    "cloud-prod:maistro-server-2": (
        (PROD,),
        lambda: _example_env(PROD_ENV_EXAMPLE),
        "maistro-server-2",
        _server_table,
    ),
    "hive-standalone:hive-conductor": ((HIVE_STANDALONE,), dict, "hive-conductor", _hive_table),
}


def test_known_gaps_name_real_profiles() -> None:
    assert set(PROFILES) >= KNOWN_GAPS


def test_every_engine_service_in_the_shipped_stacks_is_a_profile() -> None:
    """A new engine service in a shipped stack must be added above, not missed."""
    engine_images = re.compile(r"maistro-(engine|server)|hive-conductor")
    shipped: set[str] = set()
    for prefix, path in (("dev", DEV), ("cloud-prod", PROD), ("hive-standalone", HIVE_STANDALONE)):
        services = _render_services((path,), {})
        shipped |= {f"{prefix}:{name}" for name in services if engine_images.search(name)}

    assert shipped <= set(PROFILES), sorted(shipped - set(PROFILES))


@pytest.mark.parametrize("profile", sorted(PROFILES))
def test_permission_table_is_armed(profile: str, monkeypatch: pytest.MonkeyPatch) -> None:
    files, host_env, service, build_table = PROFILES[profile]
    env = _render_services(files, host_env())[service]

    table = build_table(env, monkeypatch)

    if profile in KNOWN_GAPS:
        assert table == {}, f"{profile} arms {sorted(table)} now; delete it from KNOWN_GAPS"
    else:
        assert table, f"{profile} builds an empty Sentinel permission table"
