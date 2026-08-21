from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from maistro_evolve.executable_terminal_runner import build_provider
from maistro_evolve.providers import CodexCliProvider, OpenAICompatibleProvider


@pytest.mark.asyncio
async def test_openai_compatible_provider_posts_chat_completion() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "[]"}}]})

    provider = OpenAICompatibleProvider(
        model="test-model",
        base_url="https://gateway.example/v1/",
        api_key="secret",
        transport=httpx.MockTransport(handler),
    )

    response = await provider("hello", temperature=0.0, max_tokens=20)

    assert response == "[]"
    assert captured["url"] == "https://gateway.example/v1/chat/completions"
    assert captured["authorization"] == "Bearer secret"
    assert captured["body"] == {
        "model": "test-model",
        "messages": [{"role": "user", "content": "hello"}],
        "temperature": 0.0,
        "max_tokens": 20,
    }


@pytest.mark.asyncio
async def test_openai_compatible_provider_requires_api_key_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "MAISTRO_OPENAI_API_KEY",
        "OPENAI_API_KEY",
        "LITELLM_API_KEY",
        "LITELLM_VIRTUAL_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    provider = OpenAICompatibleProvider(
        model="test-model",
        base_url="http://localhost:4000/v1",
        transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
    )

    with pytest.raises(RuntimeError, match="requires an API key"):
        await provider("hello")


def test_runner_build_provider_selects_codex() -> None:
    provider = build_provider(provider_name="codex", model="test-model")

    assert isinstance(provider, CodexCliProvider)


def test_runner_build_provider_selects_openai_compatible() -> None:
    provider = build_provider(
        provider_name="openai-compatible",
        model="test-model",
        allow_unauthenticated_provider=True,
    )

    assert isinstance(provider, OpenAICompatibleProvider)
