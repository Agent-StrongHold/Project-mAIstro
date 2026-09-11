"""Container holds the canonical CapabilityRegistry (DI composition root, SPEC-184)."""

from __future__ import annotations

from typing import Any, ClassVar

import httpx

from maistro.capabilities.registry import CapabilityRegistry
from maistro.container import create_container
from maistro.types.config import AgentConfig


async def test_container_wires_capability_registry() -> None:
    container = await create_container(AgentConfig(router_api_key="test-key"))
    assert isinstance(container.capabilities, CapabilityRegistry)
    # Canonical slots + inbox baseline come for free with every engine.
    assert "inbox" in container.capabilities.installed("approval")
    assert container.capabilities.is_enabled("infra_action") is True


async def test_container_bootstraps_the_canonical_model_binding_and_client() -> None:
    container = await create_container(AgentConfig(router_api_key="k", workspace_id="ws-model"))

    assert container.model_chat_client is not None
    assert container.model_chat_egress is not None
    binding = await container.capability_effects.bindings.get(
        container.model_chat_binding.binding_id
    )
    assert binding is not None
    assert binding.workspace_id == "ws-model"
    assert binding.capability == "model.chat"


async def test_container_model_client_records_invocation(
    monkeypatch: Any,
) -> None:
    class _Response:
        status_code = 200
        headers: ClassVar[dict[str, str]] = {}

        def json(self) -> dict[str, Any]:
            return {
                "model": "container-model-v1",
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 3},
            }

    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None: ...

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *args: Any) -> None: ...

        async def post(self, *args: Any, **kwargs: Any) -> _Response:
            return _Response()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    container = await create_container(AgentConfig(router_api_key="k", workspace_id="ws-live"))

    body = await container.model_chat_client.complete(
        [{"role": "user", "content": "hello"}],
        "container-model",
        metadata={
            "run_id": "run-live",
            "node_run_id": "node-live",
            "attempt_id": "attempt-live",
            "effect_key": "container:model",
        },
    )

    assert body["choices"][0]["message"]["content"] == "ok"
    history = await container.capability_effects.invocation_store.list_effect(
        run_id="run-live",
        node_run_id="node-live",
        binding_id=container.model_chat_binding.binding_id,
        effect_key="container:model",
    )
    assert len(history) == 1
    assert history[0].binding.provider_name == "container-model"
    assert history[0].usage is not None
    assert history[0].usage.input_units == 2


async def test_each_container_gets_its_own_registry() -> None:
    a = await create_container(AgentConfig(router_api_key="k"))
    b = await create_container(AgentConfig(router_api_key="k"))
    assert a.capabilities is not b.capabilities
