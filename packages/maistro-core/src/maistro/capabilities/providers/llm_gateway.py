"""The one approved Provider implementation for model egress (#56).

Every shipped model call must cross the governed Provider/Binding/Invocation
boundary (ADR-081226-6b46), and the boundary needs exactly one module that is
allowed to hold an HTTP client for a model endpoint. This is that module. It
owns Chat Completions and tool-free Responses gateway protocols. Authorization
is a resolved :class:`~maistro.capabilities.binding.Binding`,
lifecycle/audit is the canonical Invocation, and model selection/fallback
policy stays with :mod:`maistro.providers` (ADR-079).

The call itself goes through :func:`maistro.http.shared_client`, so the
outbound-policy seam (ADR-082326-5386) still guards the destination. Connection
failures are reported as :class:`EffectNotApplied` -- the gateway was never
reached, so no external effect occurred and the Invocation may fail retryably.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from maistro.capabilities.binding import ResolvedCapabilityProvider
from maistro.capabilities.invocation import EffectNotApplied
from maistro.capabilities.providers.model_stream_protocol import (
    ChatStreamAccumulator,
    ModelStreamProtocolError,
    parse_chunk,
    sse_data,
)
from maistro.capabilities.providers.responses_protocol import (
    ResponsesStream,
    normalize_response,
    response_text_format,
)
from maistro.http import shared_client
from maistro.providers.types import ModelMetadata

#: The canonical capability every governed model call requests.
MODEL_CHAT_CAPABILITY = "model.chat"
#: The physical credential pool used by the approved LiteLLM gateway Provider.
MODEL_GATEWAY_CREDENTIAL_PROVIDER = "litellm"
#: Default key identity for AgentConfig.litellm_key when a Binding names no
#: narrower credential refs. It is an authorization reference, never a secret.
DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF = "litellm-gateway"

_GATEWAY_TRUST_TIER = "t1"


class GatewayEndpoint(BaseModel):
    """Where the one approved model Provider sends traffic; secrets stay here.

    ``base_url`` is the gateway root (a ``/v1`` suffix is appended when absent,
    matching the shipped LiteLLM gateway convention). The API key never enters
    a Binding, Invocation request, or persisted result. Governed production
    model egress replaces ``api_key`` with the scoped credential selected from
    the resolved Binding before it crosses the physical executor seam.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    base_url: str
    api_key: str = ""
    timeout_s: float = 120.0

    @property
    def _base(self) -> str:
        base = self.base_url.rstrip("/")
        return base if base.endswith("/v1") else base + "/v1"

    def authorization_header(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers


class ProviderRegistrationError(RuntimeError):
    """The gateway rejected or could not receive provider registration."""


class LlmAuthError(PermissionError):
    """The gateway rejected the request as unauthenticated/unauthorized.

    Carries ``status_code`` so :func:`maistro.credentials.router._status_from_error`
    and :func:`maistro.resilience.classifier.classify_error` can read the real
    HTTP status directly from the exception (both check ``status_code`` first)
    instead of falling through to an unclassified error that never cools or
    blocks the offending credential (#1079 finding 5).
    """

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class LlmHttpError(RuntimeError):
    """The gateway rejected the request with a non-auth HTTP error status.

    Carries ``status_code`` for the same reason as :class:`LlmAuthError`.
    """

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class LlmGatewayProvider:
    """Slot-specific resolved Provider handle for one model-chat call.

    ``name`` is the selected model alias (or the Binding's pinned provider
    name), so the persisted :class:`ResolvedBinding` records exactly which
    model the governed call used. ``credential_provider`` names the physical
    gateway pool instead of the upstream model vendor: MAIstro authenticates to
    LiteLLM, while LiteLLM owns the OpenAI/Anthropic/etc. credentials behind it.
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
    def credential_provider(self) -> str:
        return MODEL_GATEWAY_CREDENTIAL_PROVIDER

    @property
    def metadata(self) -> ModelMetadata | None:
        return self._metadata


class ModelChatRequest(BaseModel):
    """Provider-neutral chat request shape crossing the Invocation boundary."""

    model_config = ConfigDict(extra="forbid")

    model: str = ""
    # Existing consumers keep Chat; ingress fallback is an explicit caller policy.
    api_variant: Literal["chat_completions", "responses", "auto"] = "chat_completions"
    messages: list[dict[str, object]] = Field(default_factory=list)
    # None preserves callers which intentionally leave sampling to the Provider.
    temperature: float | None = 0.7
    max_tokens: int | None = None
    tools: list[dict[str, object]] | None = None
    tool_choice: str | None = None
    response_format: dict[str, object] | None = None


class UnsupportedModelIngress(EffectNotApplied):
    """The configured gateway explicitly attested rejection before dispatch.

    This is a MAIstro extension, not an assumed LiteLLM error convention. The
    exact envelope is checked below; ordinary status codes prove nothing.
    Only the locally selected model and ingress enter persisted error text.
    """

    def __init__(self, *, model: str) -> None:
        super().__init__("gateway rejected responses ingress before model dispatch")
        self.model = model


def _uses_responses(request: ModelChatRequest, provider: LlmGatewayProvider) -> bool:
    """Choose only from operator-declared lanes when that evidence is present."""
    responses = request.api_variant in {"responses", "auto"} and not request.tools
    supported = provider.metadata.supported_ingresses if provider.metadata is not None else None
    if supported is None:
        return responses
    if request.api_variant == "auto" and "responses" not in supported:
        responses = False
    lane = "responses" if responses else "chat_completions"
    if lane not in supported:
        raise EffectNotApplied("model ingress is explicitly excluded by operator capabilities")
    return responses


def _protocol_payload(provider: LlmGatewayProvider, request: ModelChatRequest) -> dict[str, object]:
    if not _uses_responses(request, provider):
        return _chat_payload(provider, request)
    payload: dict[str, object] = {
        "model": provider.name,
        "input": [dict(message) for message in request.messages],
        "stream": False,
    }
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.max_tokens is not None:
        payload["max_output_tokens"] = request.max_tokens
    if request.response_format is not None:
        payload["text"] = {"format": response_text_format(request.response_format)}
    return payload


def _check_ingress(response: Any, provider: LlmGatewayProvider, request: ModelChatRequest) -> None:
    """Recognize only a versioned rejection with explicit non-dispatch proof.

    The trusted gateway must produce this envelope itself before any upstream
    model dispatch; passing through a provider's arbitrary error is forbidden.
    Deployed support must be verified separately. No status-only heuristic is
    used, and auth/quota failures cannot activate this protocol fallback.
    """
    if not _uses_responses(request, provider) or response.status_code != 501:
        return
    _check_rejection_body(response.content, provider)


def _check_rejection_body(content: bytes, provider: LlmGatewayProvider) -> None:
    if len(content) > 4096:
        return
    try:
        body = json.loads(content, object_pairs_hook=_unique_object)
    except (ValueError, UnicodeDecodeError):
        return
    expected = {
        "error": {
            "type": "maistro.unsupported_ingress.v1",
            "ingress": "responses",
            "model": provider.name,
            "dispatch": "not_started",
            "effect": "not_applied",
        }
    }
    if body == expected:
        raise UnsupportedModelIngress(model=provider.name)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("duplicate rejection evidence field")
    return result


async def _check_stream_ingress(
    response: Any, provider: LlmGatewayProvider, request: ModelChatRequest
) -> None:
    if not _uses_responses(request, provider) or response.status_code != 501:
        return
    content = bytearray()
    async for part in response.aiter_bytes():
        content.extend(part)
        if len(content) > 4096:
            return
    _check_rejection_body(bytes(content), provider)


def _chat_payload(provider: LlmGatewayProvider, request: ModelChatRequest) -> dict[str, object]:
    """Merge the resolved model with the governed request into a gateway body."""

    payload: dict[str, object] = {
        "model": provider.name,
        "messages": [dict(message) for message in request.messages],
        "stream": False,
    }
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.max_tokens is not None:
        payload["max_tokens"] = request.max_tokens
    if request.tools:
        payload["tools"] = [dict(tool) for tool in request.tools]
    if request.tool_choice:
        payload["tool_choice"] = request.tool_choice
    if request.response_format is not None:
        payload["response_format"] = dict(request.response_format)
    return payload


def _check_status(response: Any) -> None:
    """Map gateway statuses without consuming a successful streaming body."""

    if response.status_code == 401:
        raise LlmAuthError(
            "llm_auth_failed status=401 (check gateway credentials)", status_code=401
        )
    if response.status_code == 429:
        raise LlmHttpError("llm_rate_limited status=429", status_code=429)
    if response.status_code >= 400:
        raise LlmHttpError(
            f"llm_http_error status={response.status_code}", status_code=response.status_code
        )


def _checked_body(response: Any) -> dict[str, object]:
    """Map gateway statuses to the error shapes the shipped model paths raise."""
    _check_status(response)
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


async def execute_model_chat(
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

    responses = _uses_responses(request, provider)
    url = f"{endpoint._base}/responses"
    if not responses:
        url = f"{endpoint._base}/chat/completions"
    try:
        async with shared_client(timeout=endpoint.timeout_s) as client:
            response = await client.post(
                url,
                headers=endpoint.authorization_header(),
                json=_protocol_payload(provider, request),
            )
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        raise EffectNotApplied(f"model gateway unreachable, no effect occurred: {exc}") from exc

    _check_ingress(response, provider, request)
    body = _checked_body(response)
    result = normalize_response(body) if responses else body
    # Result evidence is owned by this Provider, never by upstream JSON. It
    # records the dispatched lane for replay, not UNKNOWN dispatch provenance.
    return {**result, "_maistro_ingress": "responses" if responses else "chat_completions"}


async def execute_model_chat_stream(
    provider: ResolvedCapabilityProvider,
    request: object,
    *,
    endpoint: GatewayEndpoint,
    on_chunk: Callable[[dict[str, Any]], Awaitable[None]],
) -> dict[str, Any]:
    """Consume real gateway SSE inside one canonical Invocation executor.

    The callback is awaited before reading more events, providing backpressure.
    Raw deltas are forwarded; only the final assembled body is persisted by the
    existing Invocation owner. EOF without protocol completion is not success.
    """
    if not isinstance(provider, LlmGatewayProvider):
        raise TypeError("model-chat stream resolved a non-gateway provider")
    if not isinstance(request, ModelChatRequest):
        raise TypeError("model-chat stream received a foreign request")
    responses = _uses_responses(request, provider)
    ingress = "responses" if responses else "chat_completions"
    payload = _protocol_payload(provider, request)
    payload["stream"] = True
    if not responses:
        payload["stream_options"] = {"include_usage": True}
    url = f"{endpoint._base}/responses"
    if not responses:
        url = f"{endpoint._base}/chat/completions"
    response_started = False
    try:
        async with (
            shared_client(timeout=endpoint.timeout_s) as client,
            client.stream(
                "POST",
                url,
                headers=endpoint.authorization_header(),
                json=payload,
            ) as response,
        ):
            response_started = True
            await _check_stream_ingress(response, provider, request)
            _check_status(response)
            result = await _consume_stream(response, ingress, on_chunk)
            return {**result, "_maistro_ingress": ingress}
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        if response_started:
            raise
        raise EffectNotApplied("model gateway unreachable, no stream effect occurred") from exc


async def _consume_stream(
    response: Any,
    ingress: str,
    on_chunk: Callable[[dict[str, Any]], Awaitable[None]],
) -> dict[str, Any]:
    chat = ChatStreamAccumulator()
    responses = ResponsesStream() if ingress == "responses" else None
    async for data in sse_data(response.aiter_lines()):
        if data == "[DONE]":
            if responses is not None:
                break
            return chat.finish()
        event = _gateway_event(data, ingress)
        if responses is not None:
            chunk = responses.add(event)
            if chunk is not None:
                await on_chunk(chunk)
            if responses.result is not None:
                return responses.result
        else:
            chat.add(event)
            await on_chunk(event)
    raise ModelStreamProtocolError("model stream ended without protocol completion")


def _gateway_event(data: str, ingress: str) -> dict[str, Any]:
    """An upstream event cannot forge Provider-owned ingress metadata."""
    event = parse_chunk(data)
    if "_maistro_ingress" in event:
        event["_maistro_ingress"] = ingress
    return event


__all__ = [
    "DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF",
    "MODEL_CHAT_CAPABILITY",
    "MODEL_GATEWAY_CREDENTIAL_PROVIDER",
    "GatewayEndpoint",
    "LlmAuthError",
    "LlmGatewayProvider",
    "LlmHttpError",
    "ModelChatRequest",
    "ProviderRegistrationError",
    "UnsupportedModelIngress",
    "execute_model_chat",
    "execute_model_chat_stream",
    "register_provider_models",
]
