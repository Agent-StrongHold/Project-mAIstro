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

    @property
    def _base(self) -> str:
        base = self.base_url.rstrip("/")
        return base if base.endswith("/v1") else base + "/v1"

    def authorization_header(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers


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
    """Provider-neutral chat request shape crossing the Invocation boundary."""

    model_config = ConfigDict(extra="forbid")

    model: str = ""
    messages: list[dict[str, object]] = Field(default_factory=list)
    temperature: float = 0.7
    max_tokens: int | None = None
    tools: list[dict[str, object]] | None = None


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

    payload: dict[str, object] = {
        "model": provider.name,
        "messages": [dict(message) for message in request.messages],
        "temperature": request.temperature,
        "stream": False,
    }
    if request.max_tokens is not None:
        payload["max_tokens"] = request.max_tokens
    if request.tools:
        payload["tools"] = [dict(tool) for tool in request.tools]

    try:
        async with shared_client(timeout=endpoint.timeout_s) as client:
            response = await client.post(
                f"{endpoint._base}/chat/completions",
                headers=endpoint.authorization_header(),
                json=payload,  # type: ignore[arg-type]
            )
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        raise EffectNotApplied(f"model gateway unreachable, no effect occurred: {exc}") from exc

    if response.status_code == 401:
        raise PermissionError("llm_auth_failed status=401 (check gateway credentials)")
    if response.status_code == 429:
        raise RuntimeError("llm_rate_limited status=429")
    if response.status_code >= 400:
        raise RuntimeError(f"llm_http_error status={response.status_code}")
    body = response.json()
    if not isinstance(body, dict):
        raise RuntimeError("model gateway returned a non-object response body")
    return body


__all__ = [
    "MODEL_CHAT_CAPABILITY",
    "GatewayEndpoint",
    "LlmGatewayProvider",
    "ModelChatRequest",
    "execute_model_chat",
]
