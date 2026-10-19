"""The server worker loads the operator YAML itself, before Container startup (#1880).

`maistro_server.entrypoint.main` runs the schema migrations and then
`os.execvp`s uvicorn, so a YAML singleton loaded in that parent dies with the
exec'd-away interpreter. The worker that actually serves requests therefore
has to call `load_yaml_config()` itself, before the lifespan's YAML consumers
run — `_validate_startup` reads `_router_api_key()` through the singleton, and
`_agent_config` reads `_security_config()` / `_model_bindings()` on the way
into `create_container`. Without the worker-side load, every deployment comes
up silently on the fail-closed defaults no matter what the operator declared.

These tests drive the real worker hook (`main._runtime_lifespan`, reached the
way uvicorn reaches it) against the real YAML parser on disk. None of them
preloads the singleton: the fixture leaves it `None`, which is exactly the
state a fresh worker process starts in. The composition factory is stubbed to
observe the effective `AgentConfig` and then stop the lifespan before the
unrelated services that would otherwise start after it; the malformed and
type-invalid cases prove startup never reaches that factory at all.

A genuine second process proves the restart case: a fresh worker reads the
changed file, because there is no prior Python singleton to inherit.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import maistro.config.settings as settings_module
import maistro_server.main as server_main
from maistro_server.startup import StartupPhase, set_startup_phase

# A synthetic secret planted in the invalid inputs. If startup handling leaks
# raw parser/validation error text anywhere, this marker leaks with it.
SECRET_MARKER = "sk-synthetic-secret-1880-do-not-leak"

# Every suite's collection runs under these (scripts/check-suite-inventory.py
# BASE_ENV parity); the subprocesses here need the same floor.
_SUBPROCESS_ENV_BASE: dict[str, str] = {
    "REQUIRE_AUTH": "false",
    "MAISTRO_DRY_RUN": "1",
    "ALLOW_UNSAFE_RESOURCE_OVERRIDES": "true",
    "RATE_LIMIT_PER_MINUTE": "6000",
    "RATE_LIMIT_BURST": "1000",
}

# Loader/env vars that would otherwise make a run's configuration depend on
# the machine it runs on (the same list maistro-core's loader tests clear).
_CONSUMED_ENV_VARS = (
    "DATABASE_URL",
    "LITELLM_URL",
    "LITELLM_MASTER_KEY",
    "ROUTER_API_KEY",
    "JWT_SECRET",
    "PHOENIX_COLLECTOR_ENDPOINT",
    "MAISTRO_WEBHOOK_SECRET",
    "MAISTRO_CORS_ORIGINS",
    "MAISTRO_RATE_LIMIT_RPM",
    "MAISTRO_MAX_REQUEST_BODY_BYTES",
    "MAISTRO_JWKS_URL",
    "MAISTRO_AUTH_ISSUER",
    "MAISTRO_AUTH_AUDIENCE",
    "MAISTRO_AUTH_CLIENT_ID",
    "MAISTRO_AUTH_AUTHORIZATION_URL",
    "MAISTRO_AUTH_TOKEN_URL",
    "MAISTRO_AUTH_CLIENT_SECRET",
)


@pytest.fixture(autouse=True)
def _fresh_worker_singleton() -> Any:
    """Start and leave the YAML singleton `None` — a fresh worker's state.

    No test preloads: whatever the assertions see must have been loaded by the
    lifespan's own hook. Clearing before *and* after also keeps one test's
    loaded file from leaking into the next through the process-wide global.
    """
    settings_module.set_yaml_config(None)
    yield
    settings_module.set_yaml_config(None)


@pytest.fixture(autouse=True)
def _clean_loader_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _CONSUMED_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _reset_startup_phase() -> Any:
    yield
    set_startup_phase(server_main.app, StartupPhase.NOT_STARTED)


class _CompositionObserved(Exception):
    """Raised by the stubbed factory to stop the lifespan right after it."""


async def _drive_worker_lifespan(
    monkeypatch: pytest.MonkeyPatch,
    observation: dict[str, Any],
) -> Any:
    """Run the real worker lifespan up to Container composition, then stop.

    The factory stub records the `AgentConfig` the lifespan actually built —
    which can only carry YAML declarations if the worker hook loaded them —
    appends the structural ordering marker, and raises so the lifespan never
    reaches the unrelated services after it. The loader is wrapped, not
    replaced: the real file read, real parser and real singleton assignment
    all still execute underneath the observation.
    """
    real_load_yaml_config = server_main.load_yaml_config

    def observing_load_yaml_config() -> Any:
        observation["events"].append("yaml_loaded")
        return real_load_yaml_config()

    async def fake_create_container(config: Any, pg_pool: Any = None) -> Any:
        observation["events"].append("container_composed")
        observation["config"] = config
        raise _CompositionObserved

    monkeypatch.setattr(server_main, "load_yaml_config", observing_load_yaml_config)
    monkeypatch.setattr(server_main, "create_container", fake_create_container)
    # A fresh lazy proxy: the module's logger may already have cached a logger
    # bound to an earlier sys.stderr (configure_logging uses
    # `cache_logger_on_first_use=True`), so bind one whose first use — inside
    # the lifespan, after configure_logging — captures into THIS test's
    # stderr. The real structlog pipeline and renderer still run.
    import structlog

    monkeypatch.setattr(server_main, "logger", structlog.get_logger())

    import contextlib

    from fastapi import FastAPI

    app = FastAPI(lifespan=server_main._runtime_lifespan)
    context = app.router.lifespan_context(app)
    with contextlib.suppress(_CompositionObserved):
        await context.__aenter__()
    return context


def _write_valid_yaml(path: Path, binding_id: str, provider: str) -> None:
    path.write_text(
        "router_api_key: yaml-router-key\n"
        "model_bindings:\n"
        f"  - binding_id: {binding_id}\n"
        "    project_id: proj-a\n"
        f"    provider_name: {provider}\n",
        encoding="utf-8",
    )


async def test_worker_lifespan_loads_operator_yaml_before_container_composition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fresh worker's Container config carries the file's declarations.

    The YAML is the only source of `router_api_key` here (the env var is
    cleared), so reaching `_validate_startup` at all proves the load happened
    first; the observed bindings prove the same declarations reached
    `_agent_config`.
    """
    config_path = tmp_path / "maistro.yaml"
    _write_valid_yaml(config_path, "prod-summarize", "gpt-4")
    monkeypatch.setenv("MAISTRO_CONFIG", str(config_path))

    observation: dict[str, Any] = {"events": [], "config": None}
    await _drive_worker_lifespan(monkeypatch, observation)

    assert observation["events"] == ["yaml_loaded", "container_composed"]
    config = observation["config"]
    assert config.router_api_key == "yaml-router-key"
    assert [b.binding_id for b in config.model_bindings] == ["prod-summarize"]
    assert config.model_bindings[0].project_id == "proj-a"
    assert config.model_bindings[0].provider_name == "gpt-4"


async def test_missing_yaml_file_starts_on_fail_closed_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicitly named missing file is defaults, not a startup failure.

    The parser contract (`TestLoadRawYaml.test_missing_file_returns_defaults`)
    stays: startup continues into Container composition with the empty
    fail-closed Binding list — a missing file authorizes nothing, but it does
    not stop the server.
    """
    monkeypatch.setenv("MAISTRO_CONFIG", str(tmp_path / "absent.yaml"))
    monkeypatch.setenv("ROUTER_API_KEY", "env-router-key")

    observation: dict[str, Any] = {"events": [], "config": None}
    await _drive_worker_lifespan(monkeypatch, observation)

    assert observation["events"] == ["yaml_loaded", "container_composed"]
    config = observation["config"]
    assert list(config.model_bindings) == []
    assert config.router_api_key == "env-router-key"
    assert config.security.permissions == {}


async def test_malformed_yaml_stops_startup_before_composition_without_leaking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Malformed YAML stops the worker before the Container, sanitizing the error.

    The parser embeds raw file contents in its ValueError; the worker must
    surface a configuration-invalid failure that carries neither the source
    fragment nor the chained parser exception — the planted secret must appear
    nowhere in the raised error, its chain, or the captured stderr, while the
    sanitized startup event does.
    """
    config_path = tmp_path / "maistro.yaml"
    config_path.write_text(
        f"router_api_key: {SECRET_MARKER}\nmodel_bindings: [unbalanced\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MAISTRO_CONFIG", str(config_path))

    observation: dict[str, Any] = {"events": [], "config": None}
    with pytest.raises(RuntimeError) as excinfo:
        await _drive_worker_lifespan(monkeypatch, observation)

    error_text = f"{excinfo.value!r}\n{excinfo.value!s}"
    assert SECRET_MARKER not in error_text
    assert "unbalanced" not in error_text
    # `from None`: the chained parser error (which quotes the file) is suppressed.
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__suppress_context__ is True
    assert "Invalid YAML" not in error_text

    # The composition factory is never reached on an invalid file.
    assert observation["events"] == ["yaml_loaded"]
    assert observation["config"] is None

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert SECRET_MARKER not in combined
    assert "operator_yaml_config_invalid" in combined
    assert "maistro.yaml" in combined  # the path is named; its contents are not
    # The singleton was never assigned from the invalid file.
    assert settings_module.get_yaml_config() is None


async def test_type_invalid_yaml_stops_startup_before_composition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A file that parses but violates the schema fails the same sanitized way.

    Typed invalidity fails inside `MaistroYamlConfig(**raw)`, before the
    singleton is assigned, so the worker must stop before composition rather
    than come up as if the declarations were absent.
    """
    config_path = tmp_path / "maestro-typed-invalid.yaml"
    config_path.write_text(
        "router_api_key: test-key\n"
        "model_bindings:\n"
        f"  - binding_id: {SECRET_MARKER}\n",  # missing required project_id
        encoding="utf-8",
    )
    monkeypatch.setenv("MAISTRO_CONFIG", str(config_path))

    observation: dict[str, Any] = {"events": [], "config": None}
    with pytest.raises(RuntimeError) as excinfo:
        await _drive_worker_lifespan(monkeypatch, observation)

    error_text = f"{excinfo.value!r}\n{excinfo.value!s}"
    assert SECRET_MARKER not in error_text
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__suppress_context__ is True

    assert observation["events"] == ["yaml_loaded"]
    assert observation["config"] is None

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert SECRET_MARKER not in combined
    assert "operator_yaml_config_invalid" in combined


_CHILD_WORKER_SCRIPT = """\
import asyncio
import json
import sys

import maistro.config.settings as settings_module
import maistro_server.main as server_main


class _CompositionObserved(Exception):
    pass


async def main() -> None:
    observed = {}

    async def fake_create_container(config, pg_pool=None):
        observed["binding_ids"] = [b.binding_id for b in config.model_bindings]
        observed["router_api_key"] = config.router_api_key
        raise _CompositionObserved

    server_main.create_container = fake_create_container

    from fastapi import FastAPI

    app = FastAPI(lifespan=server_main._runtime_lifespan)
    context = app.router.lifespan_context(app)
    try:
        await context.__aenter__()
    except _CompositionObserved:
        print("OBSERVED " + json.dumps(observed), flush=True)
        return
    raise SystemExit("composition factory was never entered")


sys.exit(asyncio.run(main()) or 0)
"""


def _worker_subprocess_env(config_path: Path) -> dict[str, str]:
    """A clean child environment: suite env floor, no database, this config."""
    repo_srcs = [
        "packages/maistro-core/src",
        "packages/maistro-server/src",
        "packages/maistro-turing/src",
        "packages/maistro-canvas/src",
        "packages/maistro-design/src",
        "packages/maistro-bootstrap/src",
        "packages/maistro-rsi/src",
        "packages/maistro-evolve/src",
        "packages/maistro-ext-sdk/src",
    ]
    env = {k: v for k, v in os.environ.items() if k not in _CONSUMED_ENV_VARS}
    env.update(_SUBPROCESS_ENV_BASE)
    env["MAISTRO_CONFIG"] = str(config_path)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(Path.cwd() / src) for src in repo_srcs] + [env.get("PYTHONPATH", "")]
    )
    return env


def _run_fresh_worker(config_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", _CHILD_WORKER_SCRIPT],
        env=_worker_subprocess_env(config_path),
        capture_output=True,
        text=True,
        timeout=120,
        cwd=Path.cwd(),
        check=False,
    )


def test_second_fresh_worker_reads_changed_declarations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A genuinely new worker process reads the file as it is *now*.

    Each child is a fresh Python process running the real worker lifespan
    against the real parser, so it can only observe the file's current
    declarations — there is no prior singleton for it to inherit. Rewriting
    the file between the two workers proves restart picks up the change
    rather than remembering the first worker's view.
    """
    config_path = tmp_path / "maistro.yaml"
    _write_valid_yaml(config_path, "first-worker-binding", "gpt-4")

    first = _run_fresh_worker(config_path)
    assert first.returncode == 0, first.stderr
    first_observed = json.loads(_observed_payload(first.stdout))
    assert first_observed["binding_ids"] == ["first-worker-binding"]
    assert first_observed["router_api_key"] == "yaml-router-key"

    _write_valid_yaml(config_path, "second-worker-binding", "gpt-4-mini")
    second = _run_fresh_worker(config_path)
    assert second.returncode == 0, second.stderr
    second_observed = json.loads(_observed_payload(second.stdout))
    assert second_observed["binding_ids"] == ["second-worker-binding"]
    assert second_observed["router_api_key"] == "yaml-router-key"


def test_fresh_worker_rejects_malformed_yaml_without_leaking_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real worker process exits non-zero, and stderr carries no secret."""
    config_path = tmp_path / "maistro.yaml"
    config_path.write_text(
        f"router_api_key: {SECRET_MARKER}\nmodel_bindings: [unbalanced\n",
        encoding="utf-8",
    )

    result = _run_fresh_worker(config_path)

    assert result.returncode != 0
    assert SECRET_MARKER not in result.stderr
    assert SECRET_MARKER not in result.stdout
    assert "operator_yaml_config_invalid" in result.stderr
    assert "Invalid YAML" not in result.stderr


def _observed_payload(stdout: str) -> str:
    for line in stdout.splitlines():
        if line.startswith("OBSERVED "):
            return line[len("OBSERVED ") :]
    raise AssertionError(f"worker never observed composition; stdout was: {stdout!r}")
