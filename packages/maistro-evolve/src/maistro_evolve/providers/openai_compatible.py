"""OpenAI-compatible chat completions provider for Evolve experiments."""

from __future__ import annotations

import os
from typing import Any

import httpx


class OpenAICompatibleProvider:
    """Async `llm_call` adapter for OpenAI-compatible `/chat/completions` APIs."""

    def __init__(
        self,
        *,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        api_key_env: str | None = None,
        timeout_seconds: float = 120.0,
        allow_unauthenticated: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._model = model or _first_env("MAISTRO_OPENAI_MODEL", "OPENAI_MODEL")
        self._base_url = (
            base_url
            or _first_env("MAISTRO_OPENAI_BASE_URL", "OPENAI_BASE_URL", "LITELLM_BASE_URL")
            or "https://api.openai.com/v1"
        ).rstrip("/")
        self._api_key = (
            api_key
            or (_env_value(api_key_env) if api_key_env else None)
            or _first_env(
                "MAISTRO_OPENAI_API_KEY",
                "OPENAI_API_KEY",
                "LITELLM_API_KEY",
                "LITELLM_VIRTUAL_KEY",
            )
        )
        self._timeout_seconds = timeout_seconds
        self._allow_unauthenticated = allow_unauthenticated
        self._transport = transport

    async def __call__(
        self,
        prompt_or_messages: str | list[dict[str, Any]],
        **kwargs: Any,
    ) -> str:
        if not self._model:
            raise RuntimeError(
                "OpenAI-compatible provider requires --model or MAISTRO_OPENAI_MODEL/OPENAI_MODEL."
            )
        if not self._api_key and not self._allow_unauthenticated:
            raise RuntimeError(
                "OpenAI-compatible provider requires an API key. Set MAISTRO_OPENAI_API_KEY, "
                "OPENAI_API_KEY, LITELLM_API_KEY, LITELLM_VIRTUAL_KEY, or pass "
                "--allow-unauthenticated-provider for a local gateway."
            )

        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        body: dict[str, Any] = {
            "model": self._model,
            "messages": _messages(prompt_or_messages),
        }
        if "temperature" in kwargs and kwargs["temperature"] is not None:
            body["temperature"] = kwargs["temperature"]
        if "max_tokens" in kwargs and kwargs["max_tokens"] is not None:
            body["max_tokens"] = kwargs["max_tokens"]

        # Deliberately NOT `maistro.http.shared_client`, despite the pooling
        # win everywhere else: maistro-evolve does not depend on maistro-core,
        # and taking that dependency to pool a single call site would couple a
        # standalone optimizer to the whole core runtime. `limits` is set here
        # instead so the pool is at least explicit rather than httpx's default.
        async with httpx.AsyncClient(
            timeout=self._timeout_seconds,
            transport=self._transport,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=50),
        ) as client:
            try:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers=headers,
                    json=body,
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                detail = exc.response.text[-2000:]
                raise RuntimeError(
                    f"OpenAI-compatible provider failed with HTTP {exc.response.status_code}: {detail}"
                ) from exc
            except httpx.HTTPError as exc:
                raise RuntimeError(f"OpenAI-compatible provider request failed: {exc}") from exc

        data = response.json()
        content = _extract_content(data)
        return content.strip()


def _messages(prompt_or_messages: str | list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(prompt_or_messages, str):
        return [{"role": "user", "content": prompt_or_messages}]
    return prompt_or_messages


def _extract_content(data: Any) -> str:
    if not isinstance(data, dict):
        raise RuntimeError("OpenAI-compatible provider returned non-object JSON.")
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("OpenAI-compatible provider response has no choices.")
    first = choices[0]
    if not isinstance(first, dict):
        raise RuntimeError("OpenAI-compatible provider choice is not an object.")
    message = first.get("message")
    if not isinstance(message, dict):
        raise RuntimeError("OpenAI-compatible provider choice has no message object.")
    content = message.get("content")
    if not isinstance(content, str):
        raise RuntimeError("OpenAI-compatible provider message content is not a string.")
    return content


def _first_env(*names: str) -> str | None:
    for name in names:
        value = _env_value(name)
        if value is not None:
            return value
    return None


def _env_value(name: str | None) -> str | None:
    if not name:
        return None
    value = os.environ.get(name)
    if value is None or not value.strip():
        return None
    return value
