"""The model gateway is chosen in `.env`, once, and every service agrees (#808).

Both Compose files used to get this wrong in different directions.

`docker-compose.yml` hardcoded four copies of ``http://litellm:4000`` into the
engine and Hive, so setting `LITELLM_*` in `.env` changed nothing and pointing
the stack at a hosted or corporate gateway needed a hand-written override.

`deploy/docker-compose.prod.yml` -- the cloud reference stack -- passed
`LITELLM_BASE_URL` alone, defaulting to empty, and no key at all, while
`LITELLM_API_BASE`, the name most of the code reads, was never set. That stack
booted, passed `/health/ready`, and could not call a single model.

These tests render the files the way Compose does and read the result, rather
than grepping the YAML for a string: the defect was never a missing string, it
was that the values a container actually received did not follow `.env`.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "docker-compose.yml"
PROD = ROOT / "deploy" / "docker-compose.prod.yml"

#: Every gateway name the code reads. Precedence differs by package --
#: hive-conductor tries LITELLM_API_BASE first, maistro-bootstrap LITELLM_URL --
#: so the only safe state is all of them agreeing.
URL_ALIASES = ("LITELLM_URL", "LITELLM_BASE_URL", "LITELLM_PROXY_URL")
KEY_ALIASES = ("LITELLM_API_KEY", "LITELLM_PROXY_KEY")

#: Everything each file requires with `:?`, so a render can get as far as the
#: gateway lines. Values are placeholders; none of them is under test here.
DEV_REQUIRED = {
    "API_KEYS": "x",
    "DB_PASSWORD": "x",
    "LANGFUSE_NEXTAUTH_SECRET": "x",
    "LANGFUSE_SALT": "x",
    "LITELLM_MASTER_KEY": "bundled-master",
    "ROUTER_API_KEY": "x",
    "TASK_DELEGATION_KEY": "x",
}
PROD_REQUIRED = {
    "API_KEYS": "x",
    "POSTGRES_PASSWORD": "x",
    "REDIS_PASSWORD": "x",
    "REPLICATION_PASSWORD": "x",
    "TASK_DELEGATION_KEY": "x",
}

EXTERNAL = {"LITELLM_BASE_URL": "https://gw.corp.example", "LITELLM_API_KEY": "sk-external"}


class MissingRequired(Exception):
    """A `${VAR:?message}` with VAR unset -- what `docker compose` refuses on."""


_EXPR = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)(?:(:?[-?])(.*))?\Z", re.S)


def _interpolate(value: str, env: dict[str, str]) -> str:
    """Compose's `${VAR}`, `${VAR:-default}` and `${VAR:?message}`, nested.

    Outermost first and *lazily*, as Compose does: the default in
    `${A:-${B:?msg}}` is only evaluated when A is unset, so an external
    gateway key makes the bundled master key optional instead of raising.
    Innermost-first would get that exact case wrong.
    """
    out: list[str] = []
    i = 0
    while i < len(value):
        if value.startswith("$$", i):
            out.append("$")
            i += 2
        elif value.startswith("${", i):
            expr, i = _read_braced(value, i + 2)
            out.append(_evaluate(expr, env))
        else:
            out.append(value[i])
            i += 1
    return "".join(out)


def _read_braced(text: str, start: int) -> tuple[str, int]:
    depth, j = 1, start
    while j < len(text):
        if text.startswith("${", j):
            depth, j = depth + 1, j + 2
            continue
        if text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[start:j], j + 1
        j += 1
    raise ValueError(f"unterminated interpolation in {text!r}")


def _evaluate(expr: str, env: dict[str, str]) -> str:
    match = _EXPR.match(expr)
    assert match, f"interpolation form this test does not model: ${{{expr}}}"
    name, op, arg = match.group(1), match.group(2), match.group(3) or ""
    current = env.get(name)
    unset = current is None or (op is not None and op.startswith(":") and current == "")
    if op in (":-", "-"):
        return _interpolate(arg, env) if unset else str(current)
    if op in (":?", "?"):
        if unset:
            raise MissingRequired(f"{name}: {arg}")
        return str(current)
    return "" if current is None else current


def _environment(service: dict[str, Any], env: dict[str, str]) -> dict[str, str]:
    raw = service.get("environment") or {}
    pairs = (
        ((item.partition("=")[0], item.partition("=")[2]) for item in raw)
        if isinstance(raw, list)
        else ((k, "" if v is None else str(v)) for k, v in raw.items())
    )
    return {key: _interpolate(val, env) for key, val in pairs}


def _render(path: Path, env: dict[str, str]) -> dict[str, dict[str, str]]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {name: _environment(svc, env) for name, svc in doc["services"].items()}


def _gateway_consumers(rendered: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    return {
        name: env
        for name, env in rendered.items()
        if any(key in env for key in (*URL_ALIASES, "LITELLM_API_BASE", *KEY_ALIASES))
    }


# --- the dev / single-host stack -------------------------------------------


def test_every_gateway_consumer_follows_the_bundled_proxy_by_default() -> None:
    consumers = _gateway_consumers(_render(DEV, DEV_REQUIRED))

    assert {"maistro-engine", "hive-conductor"} <= consumers.keys()
    for name, env in consumers.items():
        for alias in URL_ALIASES:
            if alias in env:
                assert env[alias] == "http://litellm:4000", (name, alias)
        assert env["LITELLM_API_BASE"] == "http://litellm:4000/v1", name
        for alias in KEY_ALIASES:
            if alias in env:
                assert env[alias] == "bundled-master", (name, alias)


def test_setting_the_gateway_in_env_repoints_every_consumer_without_an_override() -> None:
    """#808 AC-2 and AC-3: the overridden value reaches the containers."""
    consumers = _gateway_consumers(_render(DEV, {**DEV_REQUIRED, **EXTERNAL}))

    for name, env in consumers.items():
        for alias in URL_ALIASES:
            if alias in env:
                assert env[alias] == "https://gw.corp.example", (name, alias)
        assert env["LITELLM_API_BASE"] == "https://gw.corp.example/v1", name
        for alias in KEY_ALIASES:
            if alias in env:
                assert env[alias] == "sk-external", (name, alias)


def test_no_two_services_can_disagree_about_the_gateway() -> None:
    """#808 AC-4: one input, so the aliases cannot drift apart.

    Checked with a gateway set, because the defaults agreeing proves only that
    the hardcoded copies happened to match.
    """
    consumers = _gateway_consumers(_render(DEV, {**DEV_REQUIRED, **EXTERNAL}))
    roots = {env[a] for env in consumers.values() for a in URL_ALIASES if a in env}
    bases = {env["LITELLM_API_BASE"] for env in consumers.values()}

    assert roots == {"https://gw.corp.example"}
    assert bases == {"https://gw.corp.example/v1"}


def test_the_legacy_litellm_url_name_is_still_honoured() -> None:
    """The engine's own error message told people to set LITELLM_URL."""
    env = _render(DEV, {**DEV_REQUIRED, "LITELLM_URL": "https://legacy.example"})["maistro-engine"]

    assert env["LITELLM_BASE_URL"] == "https://legacy.example"
    assert env["LITELLM_API_BASE"] == "https://legacy.example/v1"


def test_a_non_standard_openai_path_can_be_given_explicitly() -> None:
    env = _render(
        DEV,
        {
            **DEV_REQUIRED,
            **EXTERNAL,
            "LITELLM_API_BASE": "https://gw.corp.example/openai/v1",
        },
    )["maistro-engine"]

    assert env["LITELLM_API_BASE"] == "https://gw.corp.example/openai/v1"
    assert env["LITELLM_BASE_URL"] == "https://gw.corp.example"


# --- the cloud reference stack ---------------------------------------------


def test_the_cloud_stack_refuses_to_start_without_a_gateway() -> None:
    """It runs no model gateway of its own, so an unset one is a boot-time error.

    The alternative was what shipped: a server that passes health checks and
    cannot call a model.
    """
    with pytest.raises(MissingRequired, match="LITELLM_"):
        _render(PROD, PROD_REQUIRED)


def test_every_cloud_replica_gets_the_same_complete_gateway() -> None:
    consumers = _gateway_consumers(_render(PROD, {**PROD_REQUIRED, **EXTERNAL}))

    assert len(consumers) >= 2, "expected every maistro-server replica to be configured"
    for name, env in consumers.items():
        for alias in URL_ALIASES:
            assert env[alias] == "https://gw.corp.example", (name, alias)
        assert env["LITELLM_API_BASE"] == "https://gw.corp.example/v1", name
        for alias in KEY_ALIASES:
            assert env[alias] == "sk-external", (name, alias)


# --- the resolver above must agree with the real one -----------------------


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker CLI not installed")
@pytest.mark.parametrize("path, required", [(DEV, DEV_REQUIRED), (PROD, PROD_REQUIRED)])
def test_the_python_render_matches_docker_compose_config(
    path: Path, required: dict[str, str]
) -> None:
    """Keeps `_interpolate` honest where the real renderer is available.

    `docker compose config` needs only the CLI, not a running daemon. Without
    this check the tests above would be testing a reimplementation of Compose
    that nothing ensures behaves like Compose.
    """
    env = {**required, **EXTERNAL}
    proc = subprocess.run(
        ["docker", "compose", "-f", str(path), "config", "--format", "json"],
        capture_output=True,
        text=True,
        env={**{k: v for k, v in os.environ.items() if not k.startswith("LITELLM_")}, **env},
        check=False,
    )
    if proc.returncode != 0 and "Cannot connect" in proc.stderr:
        pytest.skip("docker compose unavailable in this environment")
    assert proc.returncode == 0, proc.stderr

    import json

    real = {
        name: {k: str(v) for k, v in (svc.get("environment") or {}).items()}
        for name, svc in json.loads(proc.stdout)["services"].items()
    }
    ours = _render(path, env)
    for name, rendered in _gateway_consumers(ours).items():
        for key, value in rendered.items():
            if key.startswith("LITELLM_"):
                assert real[name][key] == value, (name, key)
