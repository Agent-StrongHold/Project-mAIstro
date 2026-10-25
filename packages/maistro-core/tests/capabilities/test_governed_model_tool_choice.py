"""Tool-choice transport through the real governed model egress (#1829)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

import maistro.capabilities.providers.llm_gateway as gateway
from maistro.capabilities.effect_context import (
    binding_scope_policy,
    new_in_memory_effect_context,
)
from maistro.capabilities.model_chat import GovernedLLMClient
from maistro.credentials.types import CredentialRecord
from maistro.observability.correlation import (
    bind_execution_context,
    detached_execution_context,
)
from maistro.providers.registry import InMemoryProviderRegistry
from maistro.providers.router import CostAwareRouter
from maistro.providers.types import ModelMetadata

pytestmark = pytest.mark.contract("behavioral")


@pytest.fixture
def governed(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[GovernedLLMClient, AsyncMock, list[dict[str, Any]]]:
    """Keep Binding, credentials and Invocation real; replace only gateway HTTP."""
    effects = new_in_memory_effect_context(policy_evaluator=binding_scope_policy)
    effects.credentials.add(
        workspace_id="ws-tool-choice",
        project_id="p1",
        record=CredentialRecord(
            key_id=gateway.DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
            provider=gateway.MODEL_GATEWAY_CREDENTIAL_PROVIDER,
            api_key="test-litellm-key",
        ),
    )
    registry = InMemoryProviderRegistry(
        models=[
            ModelMetadata(
                name="fast-model",
                provider="test-gw",
                cost_per_1k_input=0.5,
                cost_per_1k_output=1.0,
                latency_p50_ms=50,
            )
        ]
    )
    client = GovernedLLMClient(
        effects,
        registry=registry,
        router=CostAwareRouter(registry),
        endpoint=gateway.GatewayEndpoint(base_url="http://gw:4000"),
        workspace_id="ws-tool-choice",
        project_id="p1",
    )
    payloads: list[dict[str, Any]] = []

    class _GatewayClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None: ...

        async def __aenter__(self) -> _GatewayClient:
            return self

        async def __aexit__(self, *args: Any) -> None: ...

        async def post(self, url: str, **kwargs: Any) -> httpx.Response:
            assert url == "http://gw:4000/v1/chat/completions"
            assert kwargs["headers"]["Authorization"] == "Bearer test-litellm-key"
            payloads.append(deepcopy(kwargs["json"]))
            return httpx.Response(
                200,
                json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
            )

    monkeypatch.setattr(httpx, "AsyncClient", _GatewayClient)
    recorded = AsyncMock(wraps=client._egress.complete)
    monkeypatch.setattr(client._egress, "complete", recorded)
    return client, recorded, payloads


async def _complete(
    client: GovernedLLMClient, messages: list[dict[str, Any]], **kwargs: Any
) -> dict[str, Any]:
    """Supply explicit canonical context without changing the #1827 identity seam."""
    with (
        detached_execution_context(),
        bind_execution_context(
            run_id="run-tool-choice",
            node_run_id="node-tool-choice",
            attempt_id="attempt-tool-choice",
        ),
    ):
        client.set_turn("run-tool-choice")
        try:
            return await client.complete(messages, "fast-model", **kwargs)
        finally:
            client.clear_turn()


@pytest.mark.parametrize("choice", ["none", "auto", "required", "provider:custom/value", " \t "])
async def test_explicit_tool_choice_survives_governed_adapter(
    governed: tuple[GovernedLLMClient, AsyncMock, list[dict[str, Any]]], choice: str
) -> None:
    client, recorded, payloads = governed
    messages = [{"role": "user", "content": "Use the approved tool"}]
    tools = [{"type": "function", "function": {"name": "lookup", "parameters": {}}}]
    original = deepcopy((messages, tools))

    result = await _complete(
        client,
        messages,
        tools=tools,
        tool_choice=choice,
        temperature=0.15,
        max_tokens=96,
    )

    recorded.assert_awaited_once()
    request = recorded.await_args.kwargs["request"]
    assert isinstance(request, gateway.ModelChatRequest)
    assert request.tool_choice == choice
    assert request.model_dump(exclude={"tool_choice", "response_format"}) == {
        "model": "fast-model",
        "messages": messages,
        "temperature": 0.15,
        "max_tokens": 96,
        "tools": tools,
    }
    assert payloads == [
        {
            "model": "fast-model",
            "messages": messages,
            "temperature": 0.15,
            "stream": False,
            "max_tokens": 96,
            "tools": tools,
            "tool_choice": choice,
        }
    ]
    assert result["choices"][0]["message"]["content"] == "ok"
    assert (messages, tools) == original


@pytest.mark.parametrize(
    "kwargs",
    [{}, {"tool_choice": None}, {"tool_choice": ""}],
    ids=["omitted", "none", "empty"],
)
async def test_conversation_payload_still_omits_tools_and_absent_choice(
    governed: tuple[GovernedLLMClient, AsyncMock, list[dict[str, Any]]],
    kwargs: dict[str, Any],
) -> None:
    client, recorded, payloads = governed
    messages = [{"role": "user", "content": "Just chat"}]

    await _complete(client, messages, **kwargs)

    recorded.assert_awaited_once()
    request = recorded.await_args.kwargs["request"]
    assert request.tools is None
    assert request.tool_choice in (None, "")
    assert payloads == [
        {
            "model": "fast-model",
            "messages": messages,
            "temperature": 0.7,
            "stream": False,
        }
    ]


@pytest.mark.parametrize(
    "choice", [None, "", "none", "auto", "required", "provider:custom/value", " \t "]
)
def test_direct_request_preserves_other_fields_and_selected_model(choice: str | None) -> None:
    fields: dict[str, Any] = {
        "model": "requested-model",
        "messages": [{"role": "user", "content": "Return JSON"}],
        "temperature": 0.25,
        "max_tokens": 128,
        "tools": [{"type": "function", "function": {"name": "lookup", "parameters": {}}}],
        "response_format": {"type": "json_object"},
    }
    original = deepcopy(fields)
    baseline = gateway.ModelChatRequest(**fields)
    request = gateway.ModelChatRequest(**fields, tool_choice=choice)
    before = request.model_dump(mode="json")
    provider = gateway.LlmGatewayProvider(None, model="selected-model")
    expected = {**fields, "model": "selected-model", "stream": False}

    assert gateway._chat_payload(provider, baseline) == expected
    if choice:
        expected["tool_choice"] = choice
    assert gateway._chat_payload(provider, request) == expected
    assert request.model_dump(exclude={"tool_choice"}) == baseline.model_dump(
        exclude={"tool_choice"}
    )
    assert request.model_dump(mode="json") == before
    assert fields == original
