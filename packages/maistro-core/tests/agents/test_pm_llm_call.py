"""Tests for maistro.agents.pm_llm_call — PM-fleet LLM gateway adapter."""

from __future__ import annotations

import httpx
import pytest

from maistro.agents.pm_llm_call import (
    _resolve_api_key,
    _resolve_base_url,
    _resolve_model,
    maistro_llm_call,
)
from maistro.http import override_transport


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "LITELLM_URL",
        "LITELLM_BASE_URL",
        "LITELLM_PROXY_URL",
        "LITELLM_MASTER_KEY",
        "LITELLM_PROXY_KEY",
        "DEFAULT_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)


class TestResolveBaseUrl:
    def test_uses_litellm_url_first(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LITELLM_URL", "http://a/")
        monkeypatch.setenv("LITELLM_BASE_URL", "http://b")
        assert _resolve_base_url() == "http://a"

    def test_falls_back_to_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LITELLM_BASE_URL", "http://b/")
        assert _resolve_base_url() == "http://b"

    def test_falls_back_to_proxy_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LITELLM_PROXY_URL", "http://c/")
        assert _resolve_base_url() == "http://c"

    def test_empty_when_unset(self) -> None:
        assert _resolve_base_url() == ""


class TestResolveApiKey:
    def test_uses_master_key_first(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LITELLM_MASTER_KEY", "mk")
        monkeypatch.setenv("LITELLM_PROXY_KEY", "pk")
        assert _resolve_api_key() == "mk"

    def test_falls_back_to_proxy_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LITELLM_PROXY_KEY", "pk")
        assert _resolve_api_key() == "pk"

    def test_empty_when_unset(self) -> None:
        assert _resolve_api_key() == ""


class TestResolveModel:
    def test_explicit_model_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEFAULT_MODEL", "env-model")
        assert _resolve_model("explicit-model") == "explicit-model"

    def test_falls_back_to_default_model_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEFAULT_MODEL", "env-model")
        assert _resolve_model(None) == "env-model"

    def test_empty_default_model_env_falls_back_to_sonnet(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DEFAULT_MODEL", "")
        assert _resolve_model(None) == "claude-sonnet-4-6"

    def test_no_model_no_env_falls_back_to_sonnet(self) -> None:
        assert _resolve_model(None) == "claude-sonnet-4-6"

    def test_strips_openai_prefix(self) -> None:
        assert _resolve_model("openai:gpt-4") == "gpt-4"


class TestMaistroLlmCall:
    @pytest.mark.asyncio
    async def test_raises_when_gateway_not_configured(self) -> None:
        with pytest.raises(RuntimeError, match="LLM gateway not configured"):
            await maistro_llm_call([{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_success_returns_content(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LITELLM_URL", "http://gw")
        monkeypatch.setenv("LITELLM_MASTER_KEY", "key")

        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["headers"] = dict(request.headers)
            captured["body"] = request.read()
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "the response"}}]},
            )

        transport = httpx.MockTransport(handler)
        with override_transport(transport):
            result = await maistro_llm_call(
                [{"role": "user", "content": "hi"}], model="claude-sonnet-4-6"
            )

        assert result == "the response"
        assert captured["url"] == "http://gw/v1/chat/completions"
        assert captured["headers"]["authorization"] == "Bearer key"  # type: ignore[index]

    @pytest.mark.asyncio
    async def test_temperature_included_when_provided(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LITELLM_URL", "http://gw")
        monkeypatch.setenv("LITELLM_MASTER_KEY", "key")

        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            captured["body"] = json.loads(request.read())
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

        transport = httpx.MockTransport(handler)
        with override_transport(transport):
            await maistro_llm_call([{"role": "user", "content": "hi"}], temperature=0.5)

        body = captured["body"]
        assert body["temperature"] == 0.5  # type: ignore[index]

    @pytest.mark.asyncio
    async def test_json_mode_false_omits_response_format(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LITELLM_URL", "http://gw")
        monkeypatch.setenv("LITELLM_MASTER_KEY", "key")

        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            captured["body"] = json.loads(request.read())
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

        transport = httpx.MockTransport(handler)
        with override_transport(transport):
            await maistro_llm_call([{"role": "user", "content": "hi"}], json_mode=False)

        body = captured["body"]
        assert "response_format" not in body  # type: ignore[operator]

    @pytest.mark.asyncio
    async def test_error_status_raises_with_body_excerpt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LITELLM_URL", "http://gw")
        monkeypatch.setenv("LITELLM_MASTER_KEY", "key")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text="unauthorized: bad key")

        transport = httpx.MockTransport(handler)
        with (
            override_transport(transport),
            pytest.raises(RuntimeError, match="LLM gateway 401"),
        ):
            await maistro_llm_call([{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_on_response_hook_receives_body_and_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LITELLM_URL", "http://gw")
        monkeypatch.setenv("LITELLM_MASTER_KEY", "key")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"x-ratelimit-remaining-requests": "10"},
                json={
                    "choices": [{"message": {"content": "ok"}}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 7},
                },
            )

        captured: dict[str, object] = {}

        def on_response(data: dict, response: httpx.Response) -> None:
            captured["data"] = data
            captured["headers"] = dict(response.headers)

        transport = httpx.MockTransport(handler)
        with override_transport(transport):
            result = await maistro_llm_call(
                [{"role": "user", "content": "hi"}], on_response=on_response
            )

        assert result == "ok"
        assert captured["data"]["usage"] == {"prompt_tokens": 5, "completion_tokens": 7}  # type: ignore[index]
        assert captured["headers"]["x-ratelimit-remaining-requests"] == "10"  # type: ignore[index]

    @pytest.mark.asyncio
    async def test_on_response_hook_failure_is_swallowed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LITELLM_URL", "http://gw")
        monkeypatch.setenv("LITELLM_MASTER_KEY", "key")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

        def broken_hook(data: dict, response: httpx.Response) -> None:
            raise RuntimeError("recording hook blew up")

        transport = httpx.MockTransport(handler)
        with override_transport(transport):
            # Must not raise -- a broken instrumentation hook can't take down
            # a call that already succeeded.
            result = await maistro_llm_call(
                [{"role": "user", "content": "hi"}], on_response=broken_hook
            )

        assert result == "ok"

    @pytest.mark.asyncio
    async def test_no_hook_is_a_no_op(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LITELLM_URL", "http://gw")
        monkeypatch.setenv("LITELLM_MASTER_KEY", "key")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

        transport = httpx.MockTransport(handler)
        with override_transport(transport):
            result = await maistro_llm_call([{"role": "user", "content": "hi"}])

        assert result == "ok"
