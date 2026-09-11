from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Any, Literal

import httpx
from models.schemas import ChatCompletionRequest

from maistro.capabilities.invocation import EffectNotApplied
from maistro.capabilities.model_chat import (
    GovernedModelChatClient,
    build_model_chat_client,
)
from maistro.capabilities.providers.llm_gateway import GatewayEndpoint


def stub_completion(req: ChatCompletionRequest) -> dict[str, Any]:
    from uuid import uuid4

    return {
        "id": str(uuid4()),
        "model": req.model,
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": (
                        "(stub) Set LITELLM_API_BASE (…/v1) and LITELLM_API_KEY to call your gateway "
                        "through the governed model adapter."
                    ),
                }
            }
        ],
    }


def _normalize_to_chat_completions(body: dict[str, Any]) -> dict[str, Any]:
    """Keep the historical Responses-to-chat shape at the ingress adapter."""
    if "choices" in body:
        return body
    parts: list[str] = []
    for item in body.get("output") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            if content.get("type") in ("output_text", "input_text") and "text" in content:
                parts.append(str(content["text"]))
            elif isinstance(content.get("text"), str):
                parts.append(content["text"])
    text = "".join(parts).strip() or "(gateway returned /responses JSON without extractable text)"
    return {
        "id": str(body.get("id", "")),
        "model": str(body.get("model", "")),
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "_hive_protocol": "responses",
    }


def _responses_event_to_chunk(ev: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize a Responses event; the Provider owns transport, not this UX shape."""
    event_type = ev.get("type", "")
    if event_type == "response.output_text.delta" and ev.get("delta"):
        return {"choices": [{"delta": {"content": ev["delta"]}, "finish_reason": None}]}
    if event_type in (
        "response.reasoning_summary_text.delta",
        "response.reasoning_text.delta",
    ) and ev.get("delta"):
        return {"choices": [{"delta": {"reasoning_content": ev["delta"]}, "finish_reason": None}]}
    if event_type in ("response.completed", "response.output_text.done"):
        return {"choices": [{"delta": {}, "finish_reason": "stop"}]}
    return None


class StubLLMPort:
    async def complete(self, req: ChatCompletionRequest) -> dict[str, Any]:
        return stub_completion(req)

    async def stream(self, req: ChatCompletionRequest) -> AsyncIterator[dict[str, Any]]:
        text = stub_completion(req)["choices"][0]["message"]["content"]
        for word in text.split(" "):
            yield {"choices": [{"delta": {"content": word + " "}, "finish_reason": None}]}
        yield {"choices": [{"delta": {}, "finish_reason": "stop"}]}


class HttpOpenAIProtocolLLM:
    """Compatibility LLM port over canonical Capability/Provider/Binding/Invocation.

    The name remains for downstream imports. It owns no HTTP client; physical
    model dispatch is performed by maistro-core's approved gateway Provider.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        variant: Literal["auto", "responses", "chat_completions"],
        client: GovernedModelChatClient | None = None,
    ) -> None:
        self._variant = variant
        self._client = client or build_model_chat_client(
            endpoint=GatewayEndpoint(base_url=base_url, api_key=api_key),
            protocol=variant,
        )

    @staticmethod
    def _compat_error(exc: EffectNotApplied) -> httpx.HTTPStatusError:
        status = 500
        if "status=" in str(exc):
            with suppress(IndexError, ValueError):
                status = int(str(exc).split("status=", 1)[1].split()[0])
        request = httpx.Request("POST", "governed://model-chat")
        return httpx.HTTPStatusError(
            str(exc), request=request, response=httpx.Response(status, request=request)
        )

    async def complete(self, req: ChatCompletionRequest) -> dict[str, Any]:
        try:
            body = await self._client.complete(
                [dict(message) for message in req.messages],
                req.model,
                tools=req.tools,
                tool_choice=getattr(req, "tool_choice", None),
                max_tokens=req.max_tokens,
                temperature=req.temperature,
                response_format=getattr(req, "response_format", None),
                metadata={"workspace_id": getattr(req, "workspace_id", "")},
            )
        except EffectNotApplied as exc:
            raise self._compat_error(exc) from exc
        return _normalize_to_chat_completions(body)

    async def stream(self, req: ChatCompletionRequest) -> AsyncIterator[dict[str, Any]]:
        try:
            async for chunk in self._client.stream_chunks(
                [dict(message) for message in req.messages],
                req.model,
                tools=req.tools,
                tool_choice=getattr(req, "tool_choice", None),
                max_tokens=req.max_tokens,
                temperature=req.temperature,
                response_format=getattr(req, "response_format", None),
                metadata={"workspace_id": getattr(req, "workspace_id", "")},
            ):
                yield chunk
        except EffectNotApplied as exc:
            raise self._compat_error(exc) from exc
