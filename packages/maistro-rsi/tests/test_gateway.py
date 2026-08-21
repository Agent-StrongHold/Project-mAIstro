"""Tests for `maistro_rsi.gateway.make_gateway_llm_call` — request shape and
the cumulative usage counters that close the quota-burn feedback loop. Uses
httpx.MockTransport; no real network."""

from __future__ import annotations

import json

import httpx
import pytest

from maistro_rsi.gateway import make_gateway_llm_call


@pytest.fixture(autouse=True)
def gateway_env(monkeypatch):
    monkeypatch.setenv("LITELLM_URL", "http://gateway:4000")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "vk-secret")


class _CapturingTransport(httpx.MockTransport):
    def __init__(self, response_body: dict) -> None:
        self.requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return httpx.Response(200, json=response_body)

        super().__init__(handler)


@pytest.mark.asyncio
async def test_request_shape_and_usage_accumulation(monkeypatch):
    body = {
        "choices": [{"message": {"content": "the answer"}}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7},
    }
    transport = _CapturingTransport(body)
    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr("maistro_rsi.gateway.httpx.AsyncClient", client_factory)

    llm_call = make_gateway_llm_call("groq/kimi-k2")
    assert llm_call.usage_input == 0
    assert llm_call.usage_output == 0

    messages = [{"role": "user", "content": "q"}]
    result = await llm_call(messages, temperature=0.7, max_tokens=128)
    assert result == "the answer"

    request = transport.requests[0]
    assert str(request.url) == "http://gateway:4000/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer vk-secret"
    payload = json.loads(request.content)
    assert payload["model"] == "groq/kimi-k2"
    assert payload["messages"] == messages
    assert payload["temperature"] == 0.7
    assert payload["max_tokens"] == 128

    # usage accumulates across calls — RsiCycle reads these counters to
    # scheduler.record_attempt, closing the quota-burn loop
    await llm_call(messages)
    assert llm_call.usage_input == 22
    assert llm_call.usage_output == 14


@pytest.mark.asyncio
async def test_on_response_hook_receives_body_and_response(monkeypatch):
    body = {
        "choices": [{"message": {"content": "the answer"}}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7},
    }
    transport = _CapturingTransport(body)
    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr("maistro_rsi.gateway.httpx.AsyncClient", client_factory)

    captured = {}

    def on_response(data, response):
        captured["data"] = data
        captured["status"] = response.status_code

    llm_call = make_gateway_llm_call("groq/kimi-k2", on_response=on_response)
    result = await llm_call([{"role": "user", "content": "q"}])

    assert result == "the answer"
    assert captured["data"]["usage"] == {"prompt_tokens": 11, "completion_tokens": 7}
    assert captured["status"] == 200


@pytest.mark.asyncio
async def test_on_response_hook_failure_is_swallowed(monkeypatch):
    body = {"choices": [{"message": {"content": "the answer"}}]}
    transport = _CapturingTransport(body)
    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr("maistro_rsi.gateway.httpx.AsyncClient", client_factory)

    def broken_hook(data, response):
        raise RuntimeError("recording hook blew up")

    llm_call = make_gateway_llm_call("groq/kimi-k2", on_response=broken_hook)
    result = await llm_call([{"role": "user", "content": "q"}])

    assert result == "the answer"


@pytest.mark.asyncio
async def test_unconfigured_gateway_raises(monkeypatch):
    monkeypatch.delenv("LITELLM_URL", raising=False)
    monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
    monkeypatch.delenv("LITELLM_PROXY_URL", raising=False)
    llm_call = make_gateway_llm_call("m")
    with pytest.raises(RuntimeError, match="not configured"):
        await llm_call([{"role": "user", "content": "q"}])
