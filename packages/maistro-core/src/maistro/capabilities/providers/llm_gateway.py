"""The one approved Provider implementation for model egress (#56).

Every shipped model call must cross the governed Provider/Binding/Invocation
boundary (ADR-081226-6b46), and the boundary needs exactly one module that is
allowed to hold an HTTP client for a model endpoint. This is that module. It
owns the OpenAI-compatible gateway protocol (chat/completions) — the one wire
protocol both the shipped gateway and every third-party adapter registered
through the M9-E1 SDK (:mod:`maistro.capabilities.provider_adapters`) are
transported over — plus the unauthenticated provider health probe. It owns
nothing else: authorization is a resolved
:class:`~maistro.capabilities.binding.Binding`, lifecycle/audit is the
canonical Invocation, and model selection/fallback policy stays with
:mod:`maistro.providers` (ADR-079).

A third-party adapter changes what a request/response *looks like* at this
edge (through its normalization hooks) and how the resolved credential is
presented (through its declared auth style); it cannot change where the call
crosses the boundary, how it is authorized, recorded, quota-charged, or how
its failures are classified — that is what "provider cannot bypass canonical
routing/egress/security policy" means in code.

The call itself goes through :func:`maistro.http.shared_client`, so the
outbound-policy seam (ADR-082326-5386) still guards the destination. Connection
failures are reported as :class:`EffectNotApplied` -- the gateway was never
reached, so no external effect occurred and the Invocation may fail retryably.
"""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from maistro.capabilities.binding import ResolvedCapabilityProvider
from maistro.capabilities.invocation import EffectNotApplied
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
    messages: list[dict[str, object]] = Field(default_factory=list)
    # None preserves callers which intentionally leave sampling to the Provider.
    temperature: float | None = 0.7
    max_tokens: int | None = None
    tools: list[dict[str, object]] | None = None
    tool_choice: str | None = None
    response_format: dict[str, object] | None = None


def _adapter_request_headers(spec: Any, *, api_key: str) -> dict[str, str]:
    """Present a resolved credential per the adapter's declared auth style.

    ``spec`` is a :class:`~maistro.capabilities.provider_adapters.ProviderAdapterSpec`;
    it is typed loosely because importing the SDK at module level would close
    an import cycle (the SDK imports this module's capability constant). The
    secret only ever arrives from credential resolution; an adapter declaring
    a style without a resolved credential sends unauthenticated and fails at
    the provider, exactly like the gateway path with an empty key.
    """

    from maistro.capabilities.provider_adapters import AdapterAuthStyle

    headers = {"Content-Type": "application/json"}
    if not api_key:
        return headers
    if spec.auth_style == AdapterAuthStyle.BEARER:
        headers["Authorization"] = f"{spec.auth_scheme} {api_key}".strip()
    elif spec.auth_style == AdapterAuthStyle.HEADER:
        headers[str(spec.auth_header_name)] = f"{spec.auth_scheme} {api_key}".strip()
    return headers


def _adapter_query_params(spec: Any, *, api_key: str) -> dict[str, str] | None:
    """Query-string credential presentation for the ``query`` auth style."""

    from maistro.capabilities.provider_adapters import AdapterAuthStyle

    if spec.auth_style == AdapterAuthStyle.QUERY and api_key:
        return {str(spec.auth_query_param): api_key}
    return None


def _adapter_error(spec: Any, adapter: Any, status: int) -> Exception:
    """Raise the canonical exception the adapter's taxonomy kind selects.

    The adapter maps a status to an :class:`~maistro.capabilities.provider_adapters.
    AdapterErrorKind` constant; this module owns which canonical exception that
    kind becomes, so an adapter can classify but never invent an error type the
    canonical resilience classifier does not know (it reads ``status_code`` off
    :class:`LlmAuthError`/:class:`LlmHttpError` for cooldown/block decisions).
    """

    from maistro.capabilities.provider_adapters import AdapterErrorKind

    kind = adapter.error_kind_for(status)
    if kind == AdapterErrorKind.AUTH:
        return LlmAuthError(
            f"llm_auth_failed status={status} (adapter {spec.adapter_id!r} "
            "rejected the resolved credential)",
            status_code=status,
        )
    if kind == AdapterErrorKind.RATE_LIMITED:
        return LlmHttpError(
            f"llm_rate_limited status={status} (adapter {spec.adapter_id!r})",
            status_code=status,
        )
    return LlmHttpError(
        f"llm_http_error status={status} (adapter {spec.adapter_id!r}, kind={kind!r})",
        status_code=status,
    )


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


def _checked_body(response: Any) -> dict[str, object]:
    """Map gateway statuses to the error shapes the shipped model paths raise."""

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
    """Perform the one governed model HTTP call and return the canonical body.

    Only :class:`LlmGatewayProvider` and
    :class:`~maistro.capabilities.provider_adapters.AdapterGatewayProvider`
    handles may cross this seam; a foreign provider type is a wiring error, not
    a silent alternate egress. Both are transported over the same single POST:
    an adapter contributes its normalized payload, its declared credential
    presentation, its timeout, and its error taxonomy — never a second
    transport, a second authorization path, or a second Invocation.
    """

    from maistro.capabilities.provider_adapters import AdapterGatewayProvider

    if not isinstance(request, ModelChatRequest):
        raise TypeError(f"model-chat Invocation received a foreign request: {type(request)!r}")

    adapter_provider: AdapterGatewayProvider | None = None
    if isinstance(provider, AdapterGatewayProvider):
        adapter_provider = provider
        preflight = _adapter_preflight(adapter_provider, request, endpoint)
    elif isinstance(provider, LlmGatewayProvider):
        preflight = _gateway_preflight(provider, request, endpoint)
    else:
        raise TypeError(f"model-chat Invocation resolved a non-gateway provider: {provider!r}")

    try:
        async with shared_client(timeout=preflight.timeout_s) as client:
            # params only crosses when an adapter declared query-style auth, so
            # a caller-side double of the HTTP client with a strict post()
            # signature sees exactly the gateway-era call shape. The splat (not
            # a plain params= kwarg) is what keeps that shape; mypy cannot fold
            # a heterogeneous splat into httpx's positional signature.
            query_kwargs: dict[str, dict[str, str]] = (
                {"params": preflight.params} if preflight.params is not None else {}
            )
            response = await client.post(
                f"{preflight.url_base}/chat/completions",
                headers=preflight.headers,
                json=preflight.payload,
                **query_kwargs,  # type: ignore[arg-type]
            )
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        raise EffectNotApplied(f"model gateway unreachable, no effect occurred: {exc}") from exc

    if adapter_provider is not None:
        if response.status_code >= 400:
            raise _adapter_error(
                adapter_provider.spec, adapter_provider.adapter, response.status_code
            )
        body = _json_body(response)
        return adapter_provider.adapter.normalize_response(body)
    return _checked_body(response)


class _ModelCallPreflight:
    """Everything the one governed POST needs before it is issued.

    Built by :func:`_adapter_preflight` or :func:`_gateway_preflight`; the
    transport itself stays a single code path for both provider kinds.
    """

    __slots__ = ("headers", "params", "payload", "timeout_s", "url_base")

    def __init__(
        self,
        *,
        url_base: str,
        timeout_s: float,
        payload: dict[str, object],
        headers: dict[str, str],
        params: dict[str, str] | None,
    ) -> None:
        self.url_base = url_base
        self.timeout_s = timeout_s
        self.payload = payload
        self.headers = headers
        self.params = params


def _adapter_preflight(
    adapter_provider: Any,
    request: ModelChatRequest,
    endpoint: GatewayEndpoint,
) -> _ModelCallPreflight:
    """Resolve one adapter-backed call's destination, payload, and auth.

    Pre-effect adapter code: a normalizer that refuses this particular runtime
    input has not yet caused any external effect, so the refusal must read as
    not-applied (safe to reconcile and retry) rather than UNKNOWN — the same
    rule as the unreachable-endpoint branch in :func:`execute_model_chat`.
    """

    spec = adapter_provider.spec
    try:
        payload = adapter_provider.adapter.normalize_request(adapter_provider.name, request)
    except Exception as exc:
        raise EffectNotApplied(
            f"adapter {spec.adapter_id!r} refused the request before any HTTP "
            f"effect occurred: {type(exc).__name__}: {exc}"
        ) from exc
    api_key = endpoint.api_key
    return _ModelCallPreflight(
        url_base=spec.base_url.rstrip("/"),
        timeout_s=spec.timeout_s,
        payload=payload,
        headers=_adapter_request_headers(spec, api_key=api_key),
        params=_adapter_query_params(spec, api_key=api_key),
    )


def _gateway_preflight(
    provider: LlmGatewayProvider,
    request: ModelChatRequest,
    endpoint: GatewayEndpoint,
) -> _ModelCallPreflight:
    """Resolve the shipped-gateway call's destination, payload, and auth."""

    return _ModelCallPreflight(
        url_base=endpoint._base,
        timeout_s=endpoint.timeout_s,
        payload=_chat_payload(provider, request),
        headers=endpoint.authorization_header(),
        params=None,
    )


def _json_body(response: Any) -> dict[str, object]:
    """The response body as a JSON object, or a loud runtime failure."""

    body = response.json()
    if not isinstance(body, dict):
        raise RuntimeError("model gateway returned a non-object response body")
    return body


async def probe_adapter_health(adapter: Any) -> bool:
    """Run one adapter-declared unauthenticated health probe.

    Provider health is provider-level signal (ADR-081226-6b46), not an
    Invocation: it reports whether the provider endpoint answers, and the
    result feeds canonical availability through the registry's
    ``mark_unavailable`` ratchet (ADR-038). The probe is deliberately
    unauthenticated — a provider whose probe needs a secret does not declare a
    ``health_path`` — so the credential boundary stays inside credential
    resolution. The URL is dynamic from the spec, which is why the probe is
    transport-owned by this module: the same one approved seam, a GET rather
    than a chat POST, still behind the shared outbound-policy client.

    ``adapter`` is a :class:`~maistro.capabilities.provider_adapters.ProviderAdapter`;
    loosely typed for the same import-cycle reason as the auth helpers.
    """

    spec = adapter.spec
    if not spec.health_path:
        return True
    try:
        async with shared_client(timeout=min(spec.timeout_s, 10.0)) as client:
            response = await client.get(f"{spec.base_url.rstrip('/')}{spec.health_path}")
    except httpx.HTTPError:
        return False
    if response.status_code >= 400:
        return False
    try:
        body = _json_body(response)
    except (RuntimeError, ValueError):
        return False
    try:
        return bool(adapter.health_from(body))
    except Exception:
        return False


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
    "execute_model_chat",
    "probe_adapter_health",
    "register_provider_models",
]
