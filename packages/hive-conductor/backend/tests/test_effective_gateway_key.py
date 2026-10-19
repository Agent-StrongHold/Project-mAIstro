"""The one effective model-gateway credential reaches every runtime consumer (#1824).

Three contracts are pinned here:

1. **The effective-key precedence matrix** (`services.secrets.effective_llm_gateway_key`):
   vault ``MAISTRO_LLM_API_KEY`` -> settings/env ``MAISTRO_LLM_API_KEY`` ->
   vault/env ``LITELLM_API_KEY`` -> supported proxy aliases
   (``LITELLM_PROXY_KEY``, then ``LITELLM_MASTER_KEY``) -> ``None``. An empty
   value at any layer is *unset* and falls through; a conflict resolves to the
   earlier layer; nothing is ever synthesized.

2. **No placeholder credential** (#1824 removes ``sk-noop``): the embedded
   runtime's legacy model client is built with the effective key, and an
   unconfigured deployment has no key at all -- the client refuses dispatch
   *before* any HTTP with a sanitized error instead of bearing a fake token a
   real gateway can only answer 401.

3. **One contract, two doors**: the canonical governed egress endpoint
   (`services.governed_model._endpoint`) resolves the same credential through
   the same contract as the roster's legacy client, so the two doors cannot
   drift onto different credentials.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from config import Settings

from maistro.agents.types import LLMProviderError

#: Every alias the matrix reads, cleared so a test's result reflects only the
#: variables it states itself.
_KEY_ENV_VARS = (
    "MAISTRO_LLM_API_KEY",
    "LITELLM_API_KEY",
    "LITELLM_PROXY_KEY",
    "LITELLM_MASTER_KEY",
)


@pytest.fixture(autouse=True)
def _no_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _KEY_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _no_vault():
    """No vault is available unless a test installs one (SPEC-003 legs)."""
    import services.foundation as f

    prev = f._singleton
    f._singleton = None
    yield
    f._singleton = prev


class _FakeVault:
    def __init__(self, secrets: dict[str, str]) -> None:
        self._secrets = secrets

    def use(self, name: str, callback):
        if name not in self._secrets:
            raise KeyError(name)
        return callback(self._secrets[name])


class _FakeFoundation:
    def __init__(self, vault) -> None:
        self.vault = vault
        self.vault_available = True


def _settings(**kwargs: Any) -> Settings:
    # `_env_file=None`: a developer checkout's .env must not answer for the
    # matrix a test is stating.
    return Settings(_env_file=None, **kwargs)


class TestEffectiveKeyMatrix:
    def test_only_maistro_llm_api_key_is_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from services.secrets import effective_llm_gateway_key

        monkeypatch.setenv("MAISTRO_LLM_API_KEY", "sk-maistro-only")
        assert effective_llm_gateway_key(_settings()) == "sk-maistro-only"

    def test_only_litellm_api_key_is_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from services.secrets import effective_llm_gateway_key

        monkeypatch.setenv("LITELLM_API_KEY", "sk-litellm-only")
        assert effective_llm_gateway_key(_settings()) == "sk-litellm-only"

    def test_supported_proxy_alias_proxy_key_is_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from services.secrets import effective_llm_gateway_key

        monkeypatch.setenv("LITELLM_PROXY_KEY", "sk-proxy-alias")
        assert effective_llm_gateway_key(_settings()) == "sk-proxy-alias"

    def test_supported_proxy_alias_master_key_is_used(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services.secrets import effective_llm_gateway_key

        monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-master-alias")
        assert effective_llm_gateway_key(_settings()) == "sk-master-alias"

    def test_proxy_key_alias_outranks_master_key_alias(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services.secrets import effective_llm_gateway_key

        monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-master-alias")
        monkeypatch.setenv("LITELLM_PROXY_KEY", "sk-proxy-alias")
        assert effective_llm_gateway_key(_settings()) == "sk-proxy-alias"

    def test_vault_maistro_key_outranks_every_env_alias(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.foundation as f
        from services.secrets import effective_llm_gateway_key

        f._singleton = _FakeFoundation(
            _FakeVault(
                {"MAISTRO_LLM_API_KEY": "sk-from-vault", "LITELLM_API_KEY": "sk-vault-litellm"}
            )
        )
        monkeypatch.setenv("MAISTRO_LLM_API_KEY", "sk-from-env")
        monkeypatch.setenv("LITELLM_API_KEY", "sk-litellm-env")
        assert effective_llm_gateway_key(_settings()) == "sk-from-vault"

    def test_vault_litellm_key_outranks_env_aliases(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import services.foundation as f
        from services.secrets import effective_llm_gateway_key

        f._singleton = _FakeFoundation(_FakeVault({"LITELLM_API_KEY": "sk-vault-litellm"}))
        monkeypatch.setenv("LITELLM_PROXY_KEY", "sk-proxy-alias")
        assert effective_llm_gateway_key(_settings()) == "sk-vault-litellm"

    def test_conflicting_maistro_and_litellm_resolve_to_maistro(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services.secrets import effective_llm_gateway_key

        monkeypatch.setenv("MAISTRO_LLM_API_KEY", "sk-maistro-wins")
        monkeypatch.setenv("LITELLM_API_KEY", "sk-litellm-loses")
        assert effective_llm_gateway_key(_settings()) == "sk-maistro-wins"

    def test_empty_value_falls_through_to_the_next_layer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A blanked variable is *unset*: it must not shadow a configured one.

        The shipped compose file emits ``MAISTRO_LLM_API_KEY=${MAISTRO_LLM_API_KEY:-}``,
        so an unset operator key arrives as an empty string while
        ``LITELLM_API_KEY`` carries the real credential.
        """
        from services.secrets import effective_llm_gateway_key

        monkeypatch.setenv("MAISTRO_LLM_API_KEY", "")
        monkeypatch.setenv("LITELLM_API_KEY", "sk-litellm-answers")
        assert effective_llm_gateway_key(_settings()) == "sk-litellm-answers"

    def test_no_configuration_is_none_not_empty(self) -> None:
        from services.secrets import effective_llm_gateway_key

        assert effective_llm_gateway_key(_settings()) is None


class TestNoPlaceholderCredential:
    """#1824 removes `sk-noop`: absent configuration refuses before dispatch."""

    async def test_unconfigured_client_refuses_complete_before_any_http(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import adapters.maistro_core as adapter

        def _no_http(*_a: object, **_kw: object) -> None:
            raise AssertionError("an unconfigured client must not open an HTTP dispatch")

        monkeypatch.setattr(adapter, "shared_client", _no_http)
        client = adapter._HttpOpenAILLMClient(
            base_url="http://localhost:4000/v1", api_key="", model="m"
        )
        with pytest.raises(LLMProviderError, match="credential is not configured"):
            await client.complete([{"role": "user", "content": "hi"}], "m")

    async def test_unconfigured_client_refuses_stream_before_any_http(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import adapters.maistro_core as adapter

        monkeypatch.setattr(
            adapter,
            "shared_client",
            lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("no dispatch")),
        )
        client = adapter._HttpOpenAILLMClient(
            base_url="http://localhost:4000/v1", api_key="", model="m"
        )
        with pytest.raises(LLMProviderError, match="credential is not configured"):
            async for _chunk in client.stream([{"role": "user", "content": "hi"}], "m"):
                pass

    def test_refusal_names_no_secret_material(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The sanitized error carries the remediation, never key material."""
        import adapters.maistro_core as adapter

        client = adapter._HttpOpenAILLMClient(
            base_url="http://localhost:4000/v1", api_key="", model="m"
        )
        with pytest.raises(LLMProviderError) as excinfo:
            client._require_credential()
        message = str(excinfo.value)
        assert "sk-noop" not in message
        assert "MAISTRO_LLM_API_KEY" in message

    async def test_configured_client_dispatches_with_the_effective_credential(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The other half of the guard (#1824): a configured client passes it.

        ``_require_credential`` must be a no-op when the effective key is
        present — the refusal is fail-closed for absent configuration only,
        never a blanket refusal. The dispatch that then happens carries the
        intended credential as the bearer token for the gateway it names.
        (``stream`` delegates to ``complete``, so this one passage covers the
        guard for both entry points.)
        """
        import adapters.maistro_core as adapter

        captured: dict[str, Any] = {}
        payload = {"choices": [{"message": {"content": "ok"}}]}

        class _FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, Any]:
                return payload

        class _FakeAsyncClient:
            async def __aenter__(self) -> _FakeAsyncClient:
                return self

            async def __aexit__(self, *exc: object) -> None:
                return None

            async def post(self, url: str, **kwargs: Any) -> _FakeResponse:
                captured["url"] = url
                captured.update(kwargs)
                return _FakeResponse()

        monkeypatch.setattr(adapter, "shared_client", lambda *_a, **_kw: _FakeAsyncClient())
        client = adapter._HttpOpenAILLMClient(
            base_url="http://localhost:4000/v1", api_key="sk-effective-key", model="m"
        )
        result = await client.complete([{"role": "user", "content": "hi"}], "m")

        assert result == payload, "a configured client dispatches, it does not refuse"
        assert captured["headers"]["Authorization"] == "Bearer sk-effective-key"
        assert captured["url"] == "http://localhost:4000/v1/chat/completions"

    async def test_runtime_builds_the_legacy_client_with_the_effective_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only LITELLM_API_KEY stated: the roster's client and the governed
        egress endpoint both carry it -- and the placeholder is gone."""
        from adapters.maistro_core import _construct_runtime

        monkeypatch.setenv("LITELLM_API_KEY", "sk-effective-key")
        container = SimpleNamespace(
            prompt_manager=object(),
            context_assembly_policy=object(),
            context_builder=object(),
            warden=object(),
            sentinel=object(),
            learning_store=object(),
            learning_extractor=object(),
            outcome_store=object(),
            session_store=object(),
            quota_tracker=object(),
            capability_effects=object(),
            provider_registry=object(),
            llm_router=object(),
            a2a_delegator=object(),
            agents={},
            # The real Container always carries these; develop's admitted-model
            # wiring in _construct_runtime reads them (#1152, #1824 merge).
            run_store=None,
            provider_adapter_catalog=None,
        )
        captured: dict[str, Any] = {}

        async def fake_create_container(config):
            return container

        async def fake_create_agents(**kwargs):
            captured.update(kwargs)
            return {}

        monkeypatch.setattr("maistro.container.create_container", fake_create_container)
        monkeypatch.setattr("maistro.agents.factory.create_agents", fake_create_agents)

        runtime = await _construct_runtime(_settings(litellm_api_base="http://gw.test/v1"))

        assert captured["model_endpoint"].api_key == "sk-effective-key"
        assert runtime.llm._key == "sk-effective-key"
        # The two doors share one endpoint object: they cannot drift.
        assert runtime.governed_egress._endpoint is captured["model_endpoint"]

    async def test_unconfigured_runtime_holds_no_key_at_all(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty configuration -> empty key everywhere, never `sk-noop`."""
        from adapters.maistro_core import _construct_runtime

        container = SimpleNamespace(
            prompt_manager=object(),
            context_assembly_policy=object(),
            context_builder=object(),
            warden=object(),
            sentinel=object(),
            learning_store=object(),
            learning_extractor=object(),
            outcome_store=object(),
            session_store=object(),
            quota_tracker=object(),
            capability_effects=object(),
            provider_registry=object(),
            llm_router=object(),
            a2a_delegator=object(),
            agents={},
            run_store=None,
            provider_adapter_catalog=None,
        )

        async def fake_create_container(config):
            return container

        async def fake_create_agents(**kwargs):
            return {}

        monkeypatch.setattr("maistro.container.create_container", fake_create_container)
        monkeypatch.setattr("maistro.agents.factory.create_agents", fake_create_agents)

        runtime = await _construct_runtime(_settings(litellm_api_base="http://gw.test/v1"))

        assert runtime.llm._key == ""
        assert runtime.governed_egress._endpoint.api_key == ""


class TestGovernedEndpointUsesTheContract:
    def test_endpoint_resolves_the_effective_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import config
        from services.governed_model import _endpoint

        monkeypatch.setenv("LITELLM_API_BASE", "http://gw.test/v1")
        monkeypatch.setenv("LITELLM_PROXY_KEY", "sk-proxy-alias")
        # `get_settings` caches: an earlier test in a full-suite run can leave
        # a Settings carrying its own gateway key. State the env, then resolve
        # through exactly that construction (same hygiene as the sibling
        # one-contract test below).
        config.get_settings.cache_clear()
        try:
            endpoint = _endpoint()
        finally:
            config.get_settings.cache_clear()
        assert endpoint.api_key == "sk-proxy-alias"

    def test_endpoint_and_runtime_key_cannot_disagree(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Both doors resolve through one contract: same env, same key."""
        import config
        from services.governed_model import _endpoint
        from services.secrets import effective_llm_gateway_key

        monkeypatch.setenv("LITELLM_API_BASE", "http://gw.test/v1")
        monkeypatch.setenv("MAISTRO_LLM_API_KEY", "sk-one-contract")
        # `get_settings` caches; the test states the env first, then resolves
        # both doors through that exact construction.
        config.get_settings.cache_clear()
        try:
            assert _endpoint().api_key == effective_llm_gateway_key(config.get_settings())
        finally:
            config.get_settings.cache_clear()
