"""Configured-registry prerequisites on Hive's real activation route (#56).

The Container selects its real in-memory authorities; only gateway HTTP and
vault access are fakes. This is not acceptance evidence for durable quota
composition, whose caller actor propagation is a separate integration concern.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from maistro.capabilities.providers import llm_gateway
from maistro.container import Container, create_container
from maistro.identity import Principal
from maistro.runs.model import RunStatus
from maistro.types.config import AgentConfig

_MODEL = "groq/llama-3.3-70b-versatile"


class _Vault:
    """Explicit fake provider key; never opens the deployment vault."""

    def has(self, name: str) -> bool:
        assert name == "GROQ_API_KEY"
        return True

    def use(self, name: str, callback: Callable[[str], Any]) -> Any:
        assert name == "GROQ_API_KEY"
        return callback("test-only-provider-key")


@pytest.fixture
def gateway_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    """Fake the terminal transport for both registration and completion."""
    calls: list[tuple[str, dict[str, Any]]] = []

    class Response:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {
                "model": f"{_MODEL}-version",
                "choices": [{"message": {"content": "pong"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 1},
            }

    class Client:
        async def post(self, url: str, **kwargs: Any) -> Response:
            calls.append((url, kwargs["json"]))
            return Response()

    @asynccontextmanager
    async def fake_transport(*args: Any, **kwargs: Any) -> AsyncIterator[Client]:
        del args, kwargs
        yield Client()

    monkeypatch.setattr(llm_gateway, "shared_client", fake_transport)
    return calls


@asynccontextmanager
async def _configured_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, registered: bool
) -> AsyncIterator[tuple[Container, list[str]]]:
    import config
    import routes.providers as providers
    import services.engine as engine

    provider_path = tmp_path / "providers.yaml"
    # These are explicitly supplied test metadata, not inferred gateway prices.
    provider_path.write_text(
        f"models:\n  - name: {_MODEL}\n    provider: groq\n"
        "    cost_input: 0.5\n    cost_output: 1.25\n    latency_p50_ms: 100\n",
        encoding="utf-8",
    )
    container = await create_container(
        AgentConfig(
            router_api_key="test-only-router-key",
            litellm_key="test-only-gateway-key",
            litellm_url="https://gateway.invalid",
            provider_config_path=str(provider_path) if registered else "",
            database_url="",
        )
    )
    try:
        await container.project_scope_store.create_root("default")
        monkeypatch.setattr(
            engine,
            "get_engine",
            lambda: SimpleNamespace(agent_port=SimpleNamespace(container=container)),
        )
        monkeypatch.setenv("MAISTRO_LLM_BASE_URL", "https://gateway.invalid")
        monkeypatch.setenv("MAISTRO_LLM_API_KEY", "test-only-gateway-key")
        monkeypatch.setattr(
            config, "get_settings", lambda: SimpleNamespace(hive_default_workspace_id="default")
        )
        monkeypatch.setattr(providers, "_vault", _Vault)
        activated: list[str] = []
        monkeypatch.setattr(providers, "_record_activation", activated.append)
        yield container, activated
    finally:
        await container.aclose()


def _request() -> Request:
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    request.state.principal = Principal(user_id="test-operator")
    return request


@pytest.mark.asyncio
async def test_unregistered_activation_pin_refuses_before_gateway_registration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gateway_calls: list[tuple[str, dict[str, Any]]],
) -> None:
    from routes.providers import activate_provider

    async with _configured_container(tmp_path, monkeypatch, registered=False) as (
        container,
        activated,
    ):
        with pytest.raises(HTTPException) as caught:
            await activate_provider("groq", _request())

        assert caught.value.status_code == 502
        assert "ProviderRegistry" in caught.value.detail
        assert "provider_config_path" in caught.value.detail
        assert "gateway /model/new is not sufficient" in caught.value.detail
        assert gateway_calls == []
        assert activated == []
        assert await container.provider_registry.list_models() == []
        (run,) = await container.run_store.list_by_status(RunStatus.FAILED)
        assert run.actor_principal_id == "test-operator"
        assert "ProviderRegistry" in (run.error or "")


@pytest.mark.asyncio
async def test_configured_activation_pin_uses_registered_metadata_in_memory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gateway_calls: list[tuple[str, dict[str, Any]]],
) -> None:
    from routes.providers import activate_provider

    async with _configured_container(tmp_path, monkeypatch, registered=True) as (
        container,
        activated,
    ):
        registered = await container.provider_registry.get_model(_MODEL)
        result = await activate_provider("groq", _request())

        assert result["activated"] is True
        assert activated == ["groq"]
        assert [url for url, _ in gateway_calls] == [
            "https://gateway.invalid/model/new",
            "https://gateway.invalid/v1/chat/completions",
        ]
        invocation = await container.capability_effects.invocation_store.get(
            result["first_model_call"]["invocation_id"]
        )
        assert invocation is not None and invocation.usage is not None
        assert invocation.usage.cost_cents == pytest.approx(12 / 1000 * 0.5 + 1 / 1000 * 1.25)
        assert invocation.usage.provider == "groq"
        assert invocation.usage.model == _MODEL
        assert "test-only-provider-key" not in invocation.model_dump_json()
        assert await container.provider_registry.get_model(_MODEL) is registered
        (run,) = await container.run_store.list_by_status(RunStatus.COMPLETED)
        assert run.run_id == invocation.run_id
        assert run.actor_principal_id == "test-operator"


@pytest.mark.asyncio
async def test_unavailable_activation_pin_refuses_without_gateway_registration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gateway_calls: list[tuple[str, dict[str, Any]]],
) -> None:
    from routes.providers import activate_provider

    from maistro.providers.registry import InMemoryProviderRegistry

    async with _configured_container(tmp_path, monkeypatch, registered=True) as (
        container,
        activated,
    ):
        assert isinstance(container.provider_registry, InMemoryProviderRegistry)
        container.provider_registry.mark_unavailable(_MODEL)
        with pytest.raises(HTTPException) as caught:
            await activate_provider("groq", _request())

        assert caught.value.status_code == 502
        assert "pinned model" in caught.value.detail
        assert "does not fall back" in caught.value.detail
        assert gateway_calls == []
        assert activated == []
