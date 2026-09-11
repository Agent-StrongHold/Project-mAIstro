"""The one approved Provider implementation for model egress (#56).

Every shipped model call must cross the governed Provider/Binding/Invocation
boundary (ADR-081226-6b46), and the boundary needs exactly one module that is
allowed to hold an HTTP client for a model endpoint. This is that module. It
owns the OpenAI-compatible gateway protocol (chat/completions) and nothing
else: authorization is a resolved :class:`~maistro.capabilities.binding.Binding`,
lifecycle/audit is the canonical Invocation, and model selection/fallback
policy stays with :mod:`maistro.providers` (ADR-079).

The call itself goes through :func:`maistro.http.shared_client`, so the
outbound-policy seam (ADR-082326-5386) still guards the destination. Connection
failures are reported as :class:`EffectNotApplied` -- the gateway was never
reached, so no external effect occurred and the Invocation may fail retryably.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from maistro.capabilities.binding import ResolvedCapabilityProvider
from maistro.capabilities.invocation import EffectNotApplied
from maistro.http import shared_client
from maistro.providers.types import ModelMetadata

#: The canonical capability every governed model call requests.
MODEL_CHAT_CAPABILITY = "model.chat"

_GATEWAY_TRUST_TIER = "t1"


class GatewayEndpoint(BaseModel):
    """Where the one approved model Provider sends traffic; secrets stay here.

    ``base_url`` is the gateway root (a ``/v1`` suffix is appended when absent,
    matching the shipped LiteLLM gateway convention). The API key never enters
    a Binding, Invocation request, or persisted result.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    base_url: str
    api_key: str = ""
    timeout_s: float = 120.0
    append_v1: bool = True

    @property
    def _base(self) -> str:
        base = self.base_url.rstrip("/")
        return base if not self.append_v1 or base.endswith("/v1") else base + "/v1"

    def authorization_header(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers


class GatewayAuthError(EffectNotApplied, PermissionError):
    """Authentication failed before a model completion was accepted."""


class ProviderRegistrationError(RuntimeError):
    """The gateway rejected or could not receive provider registration."""


class LlmGatewayProvider:
    """Slot-specific resolved Provider handle for one model-chat call.

    ``name`` is the selected model alias (or the Binding's pinned provider
    name), so the persisted :class:`ResolvedBinding` records exactly which
    model the governed call used.
    """

    def __init__(self, metadata: ModelMetadata | None, *, model: str) -> None:
        self._metadata = metadata
        self._model = model

    @property
    def name(self) -> str:
        return self._model

    @property
    def slot(self) -> str:
        return MODEL_CHAT_CAPABILITY

    @property
    def trust_tier(self) -> str:
        return _GATEWAY_TRUST_TIER

    @property
    def metadata(self) -> ModelMetadata | None:
        return self._metadata


class ModelChatRequest(BaseModel):
    """Provider-neutral chat request shape crossing the Invocation boundary.

    ``protocol`` and ``stream`` are provider protocol details, not alternate
    egress authorities. They let compatibility/domain adapters retain their
    response shape while this Provider remains the only model HTTP owner.
    """

    model_config = ConfigDict(extra="forbid")

    model: str = ""
    messages: list[dict[str, object]] = Field(default_factory=list)
    temperature: float = 0.7
    max_tokens: int | None = None
    tools: list[dict[str, object]] | None = None
    tool_choice: str | None = None
    response_format: dict[str, object] | None = None
    protocol: str = "chat_completions"
    stream: bool = False


def _chat_payload(provider: LlmGatewayProvider, request: ModelChatRequest) -> dict[str, object]:
    """Merge the resolved model with the governed request into a gateway body."""

    payload: dict[str, object] = {
        "model": provider.name,
        "messages": [dict(message) for message in request.messages],
        "temperature": request.temperature,
        "stream": request.stream,
    }
    if request.max_tokens is not None:
        payload["max_tokens"] = request.max_tokens
    if request.tools:
        payload["tools"] = [dict(tool) for tool in request.tools]
    if request.tool_choice is not None:
        payload["tool_choice"] = request.tool_choice
    if request.response_format is not None:
        payload["response_format"] = dict(request.response_format)
    return payload


def _responses_payload(
    provider: LlmGatewayProvider, request: ModelChatRequest
) -> dict[str, object]:
    """Build the OpenAI Responses protocol payload inside the Provider."""

    return {
        "model": provider.name,
        "input": [dict(message) for message in request.messages],
        "stream": request.stream,
    }


def _responses_event_to_chunk(event: dict[str, object]) -> dict[str, object] | None:
    event_type = event.get("type", "")
    delta = event.get("delta")
    if event_type == "response.output_text.delta" and delta:
        return {"choices": [{"delta": {"content": delta}, "finish_reason": None}]}
    if (
        event_type in {"response.reasoning_summary_text.delta", "response.reasoning_text.delta"}
        and delta
    ):
        return {"choices": [{"delta": {"reasoning_content": delta}, "finish_reason": None}]}
    if event_type in {"response.completed", "response.output_text.done"}:
        return {"choices": [{"delta": {}, "finish_reason": "stop"}]}
    return None


async def _stream_body(response: httpx.Response, *, responses: bool) -> dict[str, object]:
    """Buffer a stream so Invocation can terminalize after the Provider call."""

    chunks: list[dict[str, object]] = []
    async for line in response.aiter_lines():
        if not line or not line.startswith("data:"):
            continue
        data = line[len("data:") :].strip()
        if data == "[DONE]":
            break
        try:
            event = json.loads(data)
        except (TypeError, ValueError):
            continue
        if isinstance(event, dict):
            chunk = _responses_event_to_chunk(event) if responses else event
            if chunk is not None:
                chunks.append(chunk)
    return {
        "choices": [{"message": {"role": "assistant", "content": ""}}],
        "_stream_chunks": chunks,
    }


def _checked_body(response: Any) -> dict[str, object]:
    """Map gateway statuses to retryable, truthful Invocation failures."""

    if response.status_code == 401:
        raise GatewayAuthError("llm_auth_failed status=401 (check gateway credentials)")
    if response.status_code == 429:
        raise EffectNotApplied("llm_rate_limited status=429")
    if response.status_code >= 400:
        raise EffectNotApplied(f"llm_http_error status={response.status_code}")
    body = response.json()
    if not isinstance(body, dict):
        raise RuntimeError("model gateway returned a non-object response body")
    return body


async def register_provider_models(
    endpoint: GatewayEndpoint,
    *,
    models: tuple[str, ...],
    api_key: str,
) -> None:
    """Register provider models through the gateway's Provider admin seam.

    Registration is Provider-internal setup, not a model completion. It stays
    beside the approved gateway Provider so control-plane callers cannot own a
    second HTTP implementation or accidentally persist the transient key.
    """

    admin_base = endpoint.base_url.rstrip("/")
    if admin_base.endswith("/v1"):
        admin_base = admin_base[:-3].rstrip("/")
    try:
        async with shared_client(timeout=30.0) as client:
            for model in models:
                response = await client.post(
                    f"{admin_base}/model/new",
                    headers=endpoint.authorization_header(),
                    json={
                        "model_name": model,
                        "litellm_params": {"model": model, "api_key": api_key},
                    },
                )
                if response.status_code >= 400:
                    raise ProviderRegistrationError(
                        f"LiteLLM registration failed for {model}: HTTP {response.status_code}"
                    )
    except ProviderRegistrationError:
        raise
    except httpx.HTTPError as exc:
        raise ProviderRegistrationError(f"LiteLLM gateway unreachable: {exc}") from exc


async def execute_model_chat(  # noqa: C901 - protocol fallback stays below one Provider
    provider: ResolvedCapabilityProvider,
    request: object,
    *,
    endpoint: GatewayEndpoint,
) -> dict[str, object]:
    """Perform the one governed model HTTP call and return the gateway body.

    Only :class:`LlmGatewayProvider` handles may cross this seam; a foreign
    provider type is a wiring error, not a silent alternate egress.
    """

    if not isinstance(provider, LlmGatewayProvider):
        raise TypeError(f"model-chat Invocation resolved a non-gateway provider: {provider!r}")
    if not isinstance(request, ModelChatRequest):
        raise TypeError(f"model-chat Invocation received a foreign request: {type(request)!r}")

    protocol = request.protocol
    if protocol not in {"chat_completions", "responses", "auto"}:
        raise ValueError(f"unsupported model gateway protocol: {protocol!r}")

    async def _post(client: httpx.AsyncClient, selected: str) -> dict[str, object]:
        responses = selected == "responses"
        url = f"{endpoint._base}/responses" if responses else f"{endpoint._base}/chat/completions"
        payload = (
            _responses_payload(provider, request) if responses else _chat_payload(provider, request)
        )
        if request.stream:
            async with client.stream(
                "POST",
                url,
                headers=endpoint.authorization_header(),
                json=payload,
            ) as streamed:
                if not streamed.is_success:
                    await streamed.aread()
                    _checked_body(streamed)
                body = await _stream_body(streamed, responses=responses)
                body["_provider_response_headers"] = dict(streamed.headers)
                return body
        response = await client.post(
            url,
            headers=endpoint.authorization_header(),
            json=payload,
        )
        body = _checked_body(response)
        body["_provider_response_headers"] = dict(getattr(response, "headers", {}))
        return body

    try:
        async with shared_client(timeout=endpoint.timeout_s) as client:
            if protocol == "auto" and not request.tools:
                try:
                    return await _post(client, "responses")
                except EffectNotApplied as exc:
                    if "status=401" in str(exc):
                        raise
                    return await _post(client, "chat_completions")
            return await _post(client, protocol)
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        raise EffectNotApplied(f"model gateway unreachable, no effect occurred: {exc}") from exc


__all__ = [
    "MODEL_CHAT_CAPABILITY",
    "GatewayEndpoint",
    "LlmGatewayProvider",
    "ModelChatRequest",
    "ProviderRegistrationError",
    "execute_model_chat",
    "register_provider_models",
]
