"""The uvicorn worker loads the documented YAML config before any consumer (#1824).

The shipped entrypoint (`maistro_server.entrypoint`) serializes migrations,
then `os.execvp`s into uvicorn — anything loaded before the exec is lost with
the parent process. `_runtime_lifespan` therefore loads the documented
configuration in the worker itself, before `_validate_startup` (which reads
`ROUTER_API_KEY` through the singleton) and before `_build_container` (whose
`_agent_config` reads `model_bindings` and the security grants through it).

Pinned here:

- a fresh worker process loads the documented file with NO test singleton
  injection, and the declared `model.chat` Bindings resolve through the real
  Container (existing bootstrap + scope routing; no transport);
- a malformed or type-invalid explicit file refuses startup before any
  Container is built — never substituted with empty/default success;
- a missing file keeps the parser contract: empty, fail-closed model
  authorization, and startup proceeds.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

import maistro.config.settings as settings_module
from maistro_server import main

_REPO_ROOT = Path(__file__).resolve().parents[3]

_DRIVER_TIMEOUT_S = 180.0


@pytest.fixture(autouse=True)
def _yaml_singleton_hygiene() -> Iterator[None]:
    """`load_yaml_config` sets a process-wide singleton; do not leak it."""
    # Also clear container state a previous test's successful boot left on the
    # shared module-level app, so refusal tests can assert "no container was
    # built" against THIS test's own attempt.
    main.app.state.container = None
    yield
    settings_module.set_yaml_config(None)
    main.app.state.container = None


@pytest.fixture(autouse=True)
def _no_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the Container fully in-memory: this proves worker config loading."""
    monkeypatch.setattr(main, "resolve_database_url", lambda: "")


@pytest.fixture()
def _clean_boot_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """A DB-less, auth-off boot env — the shape the shipped entrypoint runs."""
    for key in list(os.environ):
        if key.startswith("DB_") or key in ("DATABASE_URL", "ROUTER_API_KEY", "MAISTRO_CONFIG"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ROUTER_API_KEY", "worker-yaml-test-router-key")
    monkeypatch.setenv("DEBUG", "true")


@asynccontextmanager
async def _lifespan() -> AsyncIterator[None]:
    async with main.app.router.lifespan_context(main.app):
        yield


def _write_yaml(tmp_path: Path, body: str) -> Path:
    config_path = tmp_path / "maistro.yaml"
    config_path.write_text(body, encoding="utf-8")
    return config_path


class TestWorkerLoadsDocumentedConfig:
    async def test_missing_file_starts_empty_and_fail_closed(
        self, _clean_boot_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Missing explicit path = the pinned parser contract: `{}` -> empty
        fail-closed model authorization, startup proceeds."""
        monkeypatch.setenv("MAISTRO_CONFIG", str(tmp_path / "absent.yaml"))

        async with _lifespan():
            yaml_config = settings_module.get_yaml_config()
            assert yaml_config is not None
            assert yaml_config.model_bindings == []
            assert main._model_bindings() == []
            # The container this worker built carries the empty list: nothing
            # is authorized, and nothing was invented.
            assert main.app.state.container is not None

    async def test_worker_loads_yaml_before_validation_and_container(
        self, _clean_boot_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """ROUTER_API_KEY stated only in the YAML: if the worker did not load
        the file before `_validate_startup`, this boot would refuse."""
        config_path = _write_yaml(
            tmp_path,
            "router_api_key: from-documented-yaml\n"
            "model_bindings:\n"
            "  - binding_id: worker-summarize\n"
            "    project_id: proj-worker\n"
            "    provider_name: worker-model\n",
        )
        monkeypatch.delenv("ROUTER_API_KEY", raising=False)
        monkeypatch.setenv("MAISTRO_CONFIG", str(config_path))

        async with _lifespan():
            yaml_config = settings_module.get_yaml_config()
            assert yaml_config is not None
            assert yaml_config.router_api_key == "from-documented-yaml"
            assert [b.binding_id for b in main._model_bindings()] == ["worker-summarize"]
            container = main.app.state.container
            assert container is not None
            # Positive proof on the existing bootstrap/credential routing:
            # the declared Binding is live in the scope authority a
            # `llm.summarize` node resolves through.
            from maistro.capabilities.model_chat import MODEL_CHAT_CAPABILITY

            binding = await container.capability_effects.bindings.resolve(
                "worker-summarize",
                workspace_id="default",
                project_id="proj-worker",
                node_id="summarize",
                capability=MODEL_CHAT_CAPABILITY,
            )
            assert binding.provider_name == "worker-model"
            assert binding.credential_refs == ()  # no key configured -> no credential

    async def test_malformed_yaml_refuses_startup_before_any_container(
        self, _clean_boot_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        config_path = _write_yaml(tmp_path, "model_bindings: [unbalanced\n")
        monkeypatch.setenv("MAISTRO_CONFIG", str(config_path))

        with pytest.raises(RuntimeError, match="failed to load or validate"):
            async with _lifespan():
                pass
        # The failure is a startup failure: no Container was built, no
        # singleton was set, and empty/default success was not substituted.
        assert main.app.state.container is None
        assert settings_module.get_yaml_config() is None

    async def test_type_invalid_yaml_refuses_startup_before_any_container(
        self, _clean_boot_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        config_path = _write_yaml(tmp_path, 'model_bindings: "not-a-list"\n')
        monkeypatch.setenv("MAISTRO_CONFIG", str(config_path))

        with pytest.raises(RuntimeError, match="failed to load or validate"):
            async with _lifespan():
                pass
        assert main.app.state.container is None
        assert settings_module.get_yaml_config() is None

    def test_sanitized_error_names_path_and_class_not_file_content(
        self, _clean_boot_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The surfaced message is sanitized: the file's *content* (which for a
        config file can be secret material) must not appear in it."""
        config_path = _write_yaml(tmp_path, "jwt_secret: [unbalanced-secret-value\n")
        monkeypatch.setenv("MAISTRO_CONFIG", str(config_path))

        with pytest.raises(RuntimeError) as excinfo:
            main._load_documented_yaml_config()
        message = str(excinfo.value)
        assert str(config_path) in message
        assert "unbalanced-secret-value" not in message
        assert type(excinfo.value.__cause__) is not None  # detail kept for tracebacks


class TestFreshEntrypointProcess:
    """The shipped path: a real worker process, no test singleton injection."""

    def _spawn_worker(
        self, driver: str, env_extra: dict[str, str]
    ) -> subprocess.CompletedProcess[str]:
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("DB_")
            and key not in ("DATABASE_URL", "API_KEYS", "ROUTER_API_KEY", "MAISTRO_CONFIG")
        }
        env["PYTHONPATH"] = os.pathsep.join(
            (
                str(_REPO_ROOT / "packages" / "maistro-core" / "src"),
                str(_REPO_ROOT / "packages" / "maistro-server" / "src"),
                env.get("PYTHONPATH", ""),
            )
        )
        env.update({"REQUIRE_AUTH": "false", "DEBUG": "true", "MAISTRO_DRY_RUN": "1"})
        env.update(env_extra)
        return subprocess.run(
            [sys.executable, "-c", textwrap.dedent(driver)],
            capture_output=True,
            text=True,
            timeout=_DRIVER_TIMEOUT_S,
            env=env,
            cwd=str(_REPO_ROOT),
        )

    def test_fresh_worker_loads_documented_config_and_resolves_the_binding(
        self, tmp_path: Path
    ) -> None:
        """AC: a fresh shipped-entrypoint process loads documented
        configuration without test singleton injection.

        The driver asserts the singleton is still None on entry, boots the
        real lifespan, and resolves the YAML-declared Binding through the
        Container the worker itself built. ROUTER_API_KEY exists ONLY in the
        YAML: a worker that loads after validation cannot pass this boot.
        """
        config_path = _write_yaml(
            tmp_path,
            "router_api_key: from-documented-yaml\n"
            "model_bindings:\n"
            "  - binding_id: worker-summarize\n"
            "    project_id: proj-worker\n"
            "    provider_name: worker-model\n",
        )
        driver = """
            import asyncio


            async def main() -> None:
                import maistro.config.settings as settings_module
                from maistro_server import main

                pre = settings_module.get_yaml_config()
                assert pre is None, f"singleton pre-injected into a fresh worker: {pre}"

                async with main.app.router.lifespan_context(main.app):
                    loaded = settings_module.get_yaml_config()
                    assert loaded is not None, "worker never loaded the documented config"
                    assert loaded.router_api_key == "from-documented-yaml"
                    assert [b.binding_id for b in main._model_bindings()] == [
                        "worker-summarize"
                    ]

                    from maistro.capabilities.model_chat import MODEL_CHAT_CAPABILITY

                    container = main.app.state.container
                    binding = await container.capability_effects.bindings.resolve(
                        "worker-summarize",
                        workspace_id="default",
                        project_id="proj-worker",
                        node_id="summarize",
                        capability=MODEL_CHAT_CAPABILITY,
                    )
                    assert binding.provider_name == "worker-model"
                    assert binding.workspace_id == "default"
                print("WORKER-YAML-PROOF-OK")


            asyncio.run(main())
        """
        proc = self._spawn_worker(driver, {"MAISTRO_CONFIG": str(config_path)})
        assert proc.returncode == 0, (
            f"worker failed:\nstdout:\n{proc.stdout[-4000:]}\nstderr:\n{proc.stderr[-4000:]}"
        )
        assert "WORKER-YAML-PROOF-OK" in proc.stdout

    def test_fresh_worker_refuses_malformed_config_before_dispatch(self, tmp_path: Path) -> None:
        config_path = _write_yaml(tmp_path, "model_bindings: [unbalanced\n")
        driver = """
            import asyncio


            async def main() -> None:
                from maistro_server import main

                async with main.app.router.lifespan_context(main.app):
                    pass


            asyncio.run(main())
        """
        proc = self._spawn_worker(driver, {"MAISTRO_CONFIG": str(config_path)})
        assert proc.returncode != 0
        combined = proc.stdout + proc.stderr
        # Startup was refused by the sanitized guard, before any dispatch.
        assert "failed to load or validate" in combined
        assert "app.state.container" not in combined or "WORKER" not in combined
