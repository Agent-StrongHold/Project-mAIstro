"""The worker's installed model configuration reaches the runtime's Binding.

The worker loads the operator YAML itself before any consumer
(`_validate_startup` reads `ROUTER_API_KEY` through the singleton,
`_agent_config` reads `model_bindings` / the security grants through it) — the
loader semantics themselves are pinned by develop's
`test_model_config_process_startup.py`. This file is the proof that the
configuration which reaches that worker actually reaches the runtime's
scoped Binding:

- the declared `model.chat` Binding resolves through the real Container the
  worker itself built, on the existing bootstrap + scope routing (no
  transport, no test singleton injection);
- the same holds in a fresh process running the real shipped lifespan;
- the credential the installed configuration names reaches both doors the
  server has into the gateway — the `AgentConfig.litellm_key` handed to
  `create_container` (where the scoped `model.chat` credential registers) and
  the `GatewayEndpoint` the governed egress carries (§ `_gateway_credential`).
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

import maistro.capabilities.providers.llm_gateway as llm_gateway
import maistro.config.settings as settings_module
from maistro.config.settings import LiteLLMSettings, Settings
from maistro_server import main

_REPO_ROOT = Path(__file__).resolve().parents[3]

_DRIVER_TIMEOUT_S = 180.0


@pytest.fixture(autouse=True)
def _yaml_singleton_hygiene() -> Iterator[None]:
    """`load_yaml_config` sets a process-wide singleton; do not leak it."""
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


class TestInstalledGatewayCredential:
    """The credential half of the issue title: the installed configuration's
    gateway credential must reach the runtime, not just the Binding.

    A stack switched to an external gateway (`LITELLM_BASE_URL` pointed
    off-stack) states its key as `LITELLM_API_KEY` — exactly the variable the
    shipped compose file derives for both containers
    (`LITELLM_API_KEY=${LITELLM_API_KEY:-${LITELLM_MASTER_KEY}}`). Server
    construction used to read only the bundled `LITELLM_MASTER_KEY` setting, so
    the roster's client and the governed egress both presented the *bundled*
    proxy's key to a foreign gateway and every governed call came back 401.
    """

    def _settings(self, master_key: str) -> Settings:
        return Settings(
            api_keys=["ops:test-key"],
            require_auth=False,
            litellm=LiteLLMSettings(master_key=master_key),
        )

    def test_an_external_gateway_key_outranks_the_bundled_master_key(
        self, _clean_boot_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LITELLM_API_KEY", "external-gateway-key")
        settings = self._settings(master_key="bundled-proxy-master-key")

        assert main._gateway_credential(settings) == "external-gateway-key"
        # The Container's scoped `model.chat` credential registers from this
        # value, so the roster door and the governed door cannot disagree.
        assert main._agent_config(settings).litellm_key == "external-gateway-key"

    def test_a_bundled_stack_keeps_its_master_key(
        self, _clean_boot_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nothing configured beyond the bundled proxy: the master key stays
        the credential rather than the empty string an alias-only read gives."""
        monkeypatch.delenv("LITELLM_API_KEY", raising=False)
        settings = self._settings(master_key="bundled-proxy-master-key")

        assert main._gateway_credential(settings) == "bundled-proxy-master-key"
        assert main._agent_config(settings).litellm_key == "bundled-proxy-master-key"

    async def test_the_governed_egress_carries_the_same_credential(
        self, _clean_boot_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Both doors read one decision: the `GatewayEndpoint` the composition
        point builds carries the credential `_agent_config` handed the
        Container, not a second resolution of it."""
        monkeypatch.setenv("LITELLM_API_KEY", "external-gateway-key")
        settings = self._settings(master_key="bundled-proxy-master-key")
        built: list[llm_gateway.GatewayEndpoint] = []
        real_endpoint = llm_gateway.GatewayEndpoint

        def _recording_endpoint(base_url: str, api_key: str = "") -> object:
            endpoint = real_endpoint(base_url=base_url, api_key=api_key)
            built.append(endpoint)
            return endpoint

        monkeypatch.setattr(llm_gateway, "GatewayEndpoint", _recording_endpoint)
        container, _egress = await main._build_container(settings, pg_pool=None)

        endpoints = [endpoint for endpoint in built if endpoint.api_key]
        assert endpoints, "the composition point built no credentialed endpoint"
        assert {endpoint.api_key for endpoint in endpoints} == {"external-gateway-key"}
        assert sorted(container.agents) == [main.CONDUCTOR_AGENT_NAME]
