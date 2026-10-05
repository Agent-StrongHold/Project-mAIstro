"""Hive request shaping over the Container's admitted model-call authority."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import aclosing, contextmanager
from contextvars import ContextVar
from typing import Any, Literal

from fastapi import HTTPException
from models.schemas import ChatCompletionRequest
from protocols.llm import LLMPort

from maistro.capabilities.admitted_model import AdmittedModelCalls
from maistro.capabilities.providers.llm_gateway import ModelChatRequest

_effect_key: ContextVar[str] = ContextVar("hive_model_effect", default="hive-chat:turn:0")


class GovernedModelFailure(HTTPException):
    """A failed model effect must escape tool and conversation success wrappers."""

    def __init__(self) -> None:
        super().__init__(
            status_code=503,
            detail="governed model call failed or its admission is unavailable",
        )


@contextmanager
def model_effect(effect_key: str) -> Iterator[None]:
    """Name a trusted logical call site, independent of clients and Attempts.

    Only service control flow selects these names. A failed or ambiguous call
    must retain its key; completed tool correction, continuation and synthesis
    are separate operations. Request extras and provider text select no keys.
    """
    token = _effect_key.set(effect_key)
    try:
        yield
    finally:
        _effect_key.reset(token)


class GovernedChatLLMPort:
    """Shape Hive calls without owning transport, admission or credentials."""

    def __init__(
        self,
        calls: AdmittedModelCalls,
        *,
        variant: Literal["auto", "responses", "chat_completions"],
        timeout_s: float = 120.0,
        sampling: bool = True,
        effect_suffix: str = "",
    ) -> None:
        self._calls = calls
        self._variant = variant
        self._timeout_s = timeout_s
        self._sampling = sampling
        self._effect_suffix = effect_suffix

    def _logical_effect(self) -> str:
        key = _effect_key.get()
        return f"{key}:{self._effect_suffix}" if self._effect_suffix else key

    def _request(self, req: ChatCompletionRequest) -> ModelChatRequest:
        return ModelChatRequest(
            model=req.model or "",
            messages=req.messages,
            tools=req.tools,
            temperature=req.temperature if self._sampling else None,
            max_tokens=req.max_tokens,
            tool_choice=getattr(req, "tool_choice", None),
            response_format=getattr(req, "response_format", None),
            api_variant=self._variant,
        )

    async def complete(self, req: ChatCompletionRequest) -> dict[str, Any]:
        try:
            result = await self._calls.complete(
                request=self._request(req),
                effect_key=self._logical_effect(),
                timeout_s=self._timeout_s,
            )
            choices = result.body.get("choices")
            message = (
                choices[0].get("message") if choices and isinstance(choices[0], dict) else None
            )
            if not isinstance(message, dict) or not (
                isinstance(message.get("content"), str)
                or message.get("tool_calls")
                or isinstance(message.get("refusal"), str)
            ):
                raise ValueError("model returned no assistant message")
            return result.body
        except Exception as exc:
            raise GovernedModelFailure() from exc

    async def stream(self, req: ChatCompletionRequest) -> AsyncIterator[dict[str, Any]]:
        try:
            async with aclosing(
                self._calls.stream(
                    request=self._request(req),
                    effect_key=self._logical_effect(),
                    timeout_s=self._timeout_s,
                )
            ) as chunks:
                async for chunk in chunks:
                    yield chunk
        except Exception as exc:
            raise GovernedModelFailure() from exc


def build_governed_port(
    *,
    timeout_s: float = 120.0,
    sampling: bool = True,
    effect_suffix: str = "",
    variant: Literal["auto", "responses", "chat_completions"] | None = None,
) -> LLMPort:
    from config import get_settings
    from services.engine import get_engine

    calls = getattr(get_engine().agent_port, "admitted_calls", None)
    if not isinstance(calls, AdmittedModelCalls):
        raise GovernedModelFailure()
    return GovernedChatLLMPort(
        calls,
        variant=get_settings().llm_http_variant if variant is None else variant,
        timeout_s=timeout_s,
        sampling=sampling,
        effect_suffix=effect_suffix,
    )
