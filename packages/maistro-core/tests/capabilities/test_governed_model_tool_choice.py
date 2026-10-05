"""Tool-choice transport through the real governed model egress (#1829)."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from tests._admitted_model_fixture import setup

import maistro.capabilities.providers.llm_gateway as gateway
from maistro.capabilities.model_chat import GovernedLLMClient
from maistro.http import set_test_transport
from maistro.observability.correlation import (
    bind_execution_context,
    detached_execution_context,
)
from maistro.providers.registry import InMemoryProviderRegistry
from maistro.providers.types import ModelMetadata

pytestmark = pytest.mark.contract("behavioral")


@pytest.fixture
async def governed(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[GovernedLLMClient, AsyncMock, list[dict[str, Any]], tuple[str, str, str]]:
    """Keep Binding, credentials and Invocation real; replace only gateway HTTP."""
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
    s = await setup(registry=registry, key="test-litellm-key")
    client = GovernedLLMClient(s.calls)
    payloads: list[dict[str, Any]] = []

    def transport(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://gateway.fixture/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-litellm-key"
        payloads.append(json.loads(request.content))
        return httpx.Response(
            200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
        )

    set_test_transport(httpx.MockTransport(transport))
    recorded = AsyncMock(wraps=s.calls.complete)
    monkeypatch.setattr(s.calls, "complete", recorded)
    # The transport assertions below still exercise the real governed boundary;
    # the fixture now supplies persisted admission instead of correlation alone.
    return client, recorded, payloads, s.identity


async def _complete(
    client: GovernedLLMClient,
    messages: list[dict[str, Any]],
    identity: tuple[str, str, str],
    **kwargs: Any,
) -> dict[str, Any]:
    """Supply explicit canonical context without changing the #1827 identity seam."""
    with (
        detached_execution_context(),
        bind_execution_context(
            run_id=identity[0],
            node_run_id=identity[1],
            attempt_id=identity[2],
        ),
    ):
        client.set_turn(identity[0])
        try:
            return await client.complete(messages, "fast-model", **kwargs)
        finally:
            client.clear_turn()


@pytest.mark.parametrize("choice", ["none", "auto", "required", "provider:custom/value", " \t "])
async def test_explicit_tool_choice_survives_governed_adapter(
    governed: tuple[GovernedLLMClient, AsyncMock, list[dict[str, Any]], tuple[str, str, str]],
    choice: str,
) -> None:
    client, recorded, payloads, identity = governed
    messages = [{"role": "user", "content": "Use the approved tool"}]
    tools = [{"type": "function", "function": {"name": "lookup", "parameters": {}}}]
    original = deepcopy((messages, tools))

    result = await _complete(
        client,
        messages,
        identity,
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
    governed: tuple[GovernedLLMClient, AsyncMock, list[dict[str, Any]], tuple[str, str, str]],
    kwargs: dict[str, Any],
) -> None:
    client, recorded, payloads, identity = governed
    messages = [{"role": "user", "content": "Just chat"}]

    await _complete(client, messages, identity, **kwargs)

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
