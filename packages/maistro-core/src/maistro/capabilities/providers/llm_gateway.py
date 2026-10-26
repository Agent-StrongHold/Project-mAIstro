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

import json
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from maistro.capabilities.binding import ResolvedCapabilityProvider
from maistro.capabilities.invocation import EffectNotApplied
from maistro.capabilities.providers.extension_attribution import log_fields_suffix
from maistro.http import shared_client
from maistro.providers.types import ModelMetadata
from maistro.resilience.context_probe import ContextProbe
from maistro.resilience.rate_coordination import RateLimitCoordinator

if TYPE_CHECKING:
    from maistro.capabilities.provider_adapters import AdapterGatewayProvider

#: The canonical capability every governed model call requests.
MODEL_CHAT_CAPABILITY = "model.chat"
#: The physical credential pool used by the approved LiteLLM gateway Provider.
MODEL_GATEWAY_CREDENTIAL_PROVIDER = "litellm"
#: Default key identity for AgentConfig.litellm_key when a Binding names no
#: narrower credential refs. It is an authorization reference, never a secret.
DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF = "litellm-gateway"

_GATEWAY_TRUST_TIER = "t1"

logger = logging.getLogger(__name__)
#: Cross-instance 429 coordination for the approved gateway Provider (#2318).
_GATEWAY_RATE_LIMITS = RateLimitCoordinator()
#: Adaptive context-window probe for models that omit a declared max (#2318).
_CONTEXT_PROBE = ContextProbe()
_GATEWAY_RATE_LIMIT_SCOPE = MODEL_GATEWAY_CREDENTIAL_PROVIDER


def _adapter_identity_suffix(spec: Any) -> str:
    """The declared package identity, as an error-message suffix.

    Empty for a package that declares no identity (M9-I1, #976): legacy
    adapters keep their message shape, while declaring packages make every
    error traceable to the exact version and publisher without a registry
    lookup — the message travels with the Invocation evidence, so the
    identity of the failing package is readable even after that package is
    upgraded or removed.
    """

    if not getattr(spec, "version", ""):
        return ""
    return f" {spec.version} (publisher {spec.publisher!r})"


def _adapter_log_fields(adapter_provider: Any) -> dict[str, str]:
    """Flat log fields naming the adapter package behind one governed call.

    Declared identity becomes the canonical extension-attribution fields; a
    legacy adapter logs only its id, so the line never claims an identity the
    package did not declare. No field here carries request, payload, or
    credential material — identity only.
    """

    attribution = adapter_provider.extension_attribution
    if attribution is not None:
        fields: dict[str, str] = attribution.to_log_fields()
        return fields
    return {"adapter_id": str(adapter_provider.spec.adapter_id)}


class GatewayEndpoint(BaseModel):
    """Where the one approved model Provider sends traffic; secrets stay here.

    ``base_url`` is the gateway root (a ``/v1`` suffix is appended when absent,
    matching the shipped LiteLLM gateway convention). A consumer holding a
    configured API prefix opts into ``base_url_is_api_base`` to retain its exact
    path. This leaves adapter-owned SDK URLs unchanged. The API key never enters
    a Binding, Invocation request, or persisted result. Governed production
    model egress replaces ``api_key`` with the scoped credential selected from
    the resolved Binding before it crosses the physical executor seam.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    base_url: str
    api_key: str = ""
    organization: str = ""
    project: str = ""
    timeout_s: float = 120.0
    append_v1: bool = True
    base_url_is_api_base: bool = False

    @property
    def _base(self) -> str:
        base = self.base_url.rstrip("/")
        if not self.append_v1 or self.base_url_is_api_base or base.endswith("/v1"):
            return base
        return base + "/v1"

    def authorization_header(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.organization:
            headers["OpenAI-Organization"] = self.organization
        if self.project:
            headers["OpenAI-Project"] = self.project
        return headers


class ProviderRegistrationError(RuntimeError):
    """The gateway rejected or could not receive provider registration."""


class LlmAuthError(EffectNotApplied, PermissionError):
    """The gateway rejected the request as unauthenticated/unauthorized.

    Carries ``status_code`` so :func:`maistro.credentials.router._status_from_error`
    and :func:`maistro.resilience.classifier.classify_error` can read the real
    HTTP status directly from the exception (both check ``status_code`` first)
    instead of falling through to an unclassified error that never cools or
    blocks the offending credential (#1079 finding 5). It is also an
    :class:`~maistro.capabilities.invocation.EffectNotApplied` so a rejected
    gateway credential fails the Invocation retryably: the gateway answered,
    so no model-completion effect occurred.
    """

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class LlmHttpError(EffectNotApplied, RuntimeError):
    """The gateway rejected the request with a non-auth HTTP error status.

    Carries ``status_code`` for the same reason as :class:`LlmAuthError`.
    Also an :class:`~maistro.capabilities.invocation.EffectNotApplied`: a
    rejected gateway response means no model completion occurred, so the
    Invocation is FAILED (retryable) rather than UNKNOWN.
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
    """Provider-neutral chat request shape crossing the Invocation boundary.

    ``protocol`` and ``stream`` are provider protocol details, not alternate
    egress authorities. They let compatibility/domain adapters retain their
    response shape while this Provider remains the only model HTTP owner.
    """

    model_config = ConfigDict(extra="forbid")

    model: str = ""
    messages: list[dict[str, object]] = Field(default_factory=list)
    # None preserves callers which intentionally leave sampling to the Provider.
    temperature: float | None = 0.7
    max_tokens: int | None = None
    tools: list[dict[str, object]] | None = None
    tool_choice: str | None = None
    response_format: dict[str, object] | None = None
    protocol: str = "chat_completions"
    stream: bool = False


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
    identity = _adapter_identity_suffix(spec)
    if kind == AdapterErrorKind.AUTH:
        return LlmAuthError(
            f"llm_auth_failed status={status} (adapter {spec.adapter_id!r}{identity} "
            "rejected the resolved credential)",
            status_code=status,
        )
    if kind == AdapterErrorKind.RATE_LIMITED:
        return LlmHttpError(
            f"llm_rate_limited status={status} (adapter {spec.adapter_id!r}{identity})",
            status_code=status,
        )
    return LlmHttpError(
        f"llm_http_error status={status} (adapter {spec.adapter_id!r}{identity}, kind={kind!r})",
        status_code=status,
    )


def _chat_payload(provider: LlmGatewayProvider, request: ModelChatRequest) -> dict[str, object]:
    """Merge the resolved model with the governed request into a gateway body."""

    payload: dict[str, object] = {
        "model": provider.name,
        "messages": [dict(message) for message in request.messages],
        "stream": request.stream,
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


def _stream_usage(event: dict[str, object]) -> dict[str, int] | None:
    """Normalize one SSE event's usage report to OpenAI token fields.

    chat.completions streams usage as ``prompt_tokens``/``completion_tokens``
    (a terminal chunk with empty choices); the Responses protocol reports
    ``input_tokens``/``output_tokens`` inside its ``response.completed``
    event. ``None`` means this event carried no measurement, which is the
    truthful reading — an unmeasured stream must not read as zero.
    """

    usage = event.get("usage")
    if not isinstance(usage, dict):
        completed = event.get("response")
        usage = completed.get("usage") if isinstance(completed, dict) else None
        if not isinstance(usage, dict):
            return None
    prompt = usage.get("prompt_tokens", usage.get("input_tokens"))
    completion = usage.get("completion_tokens", usage.get("output_tokens"))
    if not isinstance(prompt, int) or not isinstance(completion, int):
        return None
    return {"prompt_tokens": prompt, "completion_tokens": completion}


class _StreamSummary:
    """Accumulates the terminal summary while the stream's chunks pass by live.

    The Invocation terminalizes on this summary — assembled content, last
    finish reason, last usage report, and the chunk list a deduplicated replay
    needs — exactly as it terminalizes on a non-streaming body (SPEC-285).
    """

    __slots__ = ("_chunks", "_content_parts", "_finish_reason", "_usage")

    def __init__(self) -> None:
        self._chunks: list[dict[str, object]] = []
        self._content_parts: list[str] = []
        self._finish_reason: object = None
        self._usage: dict[str, int] | None = None

    def absorb(self, chunk: dict[str, object]) -> None:
        """Fold one normalized chunk into the summary."""

        self._chunks.append(chunk)
        choices = chunk.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            self._absorb_choice(choices[0])

    def _absorb_choice(self, choice: dict[str, object]) -> None:
        delta = choice.get("delta")
        piece = delta.get("content") if isinstance(delta, dict) else None
        if isinstance(piece, str):
            self._content_parts.append(piece)
        if choice.get("finish_reason") is not None:
            self._finish_reason = choice.get("finish_reason")

    def observe_usage(self, event: dict[str, object]) -> None:
        """Record the last usage measurement any raw event carried."""

        self._usage = _stream_usage(event) or self._usage

    def body(self) -> dict[str, object]:
        """The terminal summary body the Invocation result records."""

        body: dict[str, object] = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "".join(self._content_parts),
                    },
                    "finish_reason": self._finish_reason,
                }
            ],
            "_stream_chunks": self._chunks,
        }
        if self._usage is not None:
            body["usage"] = self._usage
        return body


async def _stream_body(
    response: httpx.Response,
    *,
    responses: bool,
    on_chunk: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    """Pump a provider SSE body to ``on_chunk`` live and return the summary.

    Every parsed chunk reaches ``on_chunk`` while the wire is still producing,
    so the consumer of a governed stream sees tokens as the provider emits
    them (SPEC-285). The Invocation is unaffected: it was admitted before this
    dispatch and terminalizes on the returned summary after full consumption,
    exactly as the non-streaming body terminalizes.
    """

    summary = _StreamSummary()
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
        if not isinstance(event, dict):
            continue
        chunk = _responses_event_to_chunk(event) if responses else event
        if chunk is None:
            continue
        summary.absorb(chunk)
        summary.observe_usage(event)
        if on_chunk is not None:
            on_chunk(chunk)
    return summary.body()


def _checked_body(response: Any) -> dict[str, object]:
    """Map gateway statuses to retryable, truthful Invocation failures."""

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


async def _dispatch_adapter_model_chat(
    adapter_provider: AdapterGatewayProvider,
    request: ModelChatRequest,
    endpoint: GatewayEndpoint,
) -> dict[str, object]:
    """Transport one adapter-provider call over its declared preflight shape."""

    preflight = _adapter_preflight(adapter_provider, request, endpoint)
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
    if response.status_code >= 400:
        raise _adapter_error(adapter_provider.spec, adapter_provider.adapter, response.status_code)
    body = _json_body(response)
    fields = _adapter_log_fields(adapter_provider)
    logger.info(
        "extension adapter model call: adapter=%s model=%s %s",
        adapter_provider.spec.adapter_id,
        adapter_provider.model,
        log_fields_suffix(fields),
        extra=fields,
    )
    return adapter_provider.adapter.normalize_response(body)


async def _post_model_chat(
    client: httpx.AsyncClient,
    provider: LlmGatewayProvider,
    request: ModelChatRequest,
    endpoint: GatewayEndpoint,
    selected: str,
    *,
    on_chunk: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    """Perform one POST (or streamed POST) under the selected protocol."""

    responses = selected == "responses"
    if responses:
        url = f"{endpoint._base}/responses"
        payload = _responses_payload(provider, request)
    else:
        gateway = _gateway_preflight(provider, request, endpoint)
        url = f"{gateway.url_base}/chat/completions"
        payload = gateway.payload
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
            body = await _stream_body(streamed, responses=responses, on_chunk=on_chunk)
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


async def _dispatch_gateway_model_chat(
    provider: LlmGatewayProvider,
    request: ModelChatRequest,
    endpoint: GatewayEndpoint,
    *,
    on_chunk: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    """Transport one shipped-Provider call, selecting the request's protocol."""

    protocol = request.protocol
    if protocol not in {"chat_completions", "responses", "auto"}:
        raise ValueError(f"unsupported model gateway protocol: {protocol!r}")

    try:
        async with shared_client(timeout=endpoint.timeout_s) as client:
            if protocol == "auto" and not request.tools:
                try:
                    return await _post_model_chat(
                        client, provider, request, endpoint, "responses", on_chunk=on_chunk
                    )
                except EffectNotApplied as exc:
                    if "status=401" in str(exc):
                        raise
                    return await _post_model_chat(
                        client, provider, request, endpoint, "chat_completions", on_chunk=on_chunk
                    )
            return await _post_model_chat(
                client, provider, request, endpoint, protocol, on_chunk=on_chunk
            )
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        raise EffectNotApplied(f"model gateway unreachable, no effect occurred: {exc}") from exc


async def execute_model_chat(
    provider: ResolvedCapabilityProvider,
    request: object,
    *,
    endpoint: GatewayEndpoint,
    on_chunk: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    """Perform the one governed model HTTP call and return the canonical body.

    Only :class:`LlmGatewayProvider` and
    :class:`~maistro.capabilities.provider_adapters.AdapterGatewayProvider`
    handles may cross this seam; a foreign provider type is a wiring error, not
    a silent alternate egress. An adapter contributes its normalized payload,
    its declared credential presentation, its timeout, and its error taxonomy
    over one POST. The shipped gateway Provider picks its protocol (Responses
    first under ``auto``, then chat.completions) and may stream, but always
    through this one seam — never a second transport, a second authorization
    path, or a second Invocation.

    ``on_chunk`` is the streaming observer (SPEC-285): when the request
    streams, the gateway's normalized chunks are handed to it as they arrive,
    before the Invocation terminalizes. It is a progress side channel only —
    it cannot alter authorization, admission, dedup, or the terminal record.
    Adapter-backed calls keep their buffered JSON contract and ignore it.
    """

    from maistro.capabilities.provider_adapters import AdapterGatewayProvider

    if not isinstance(request, ModelChatRequest):
        raise TypeError(f"model-chat Invocation received a foreign request: {type(request)!r}")

    if isinstance(provider, AdapterGatewayProvider):
        return await _dispatch_adapter_model_chat(provider, request, endpoint)
    if not isinstance(provider, LlmGatewayProvider):
        raise TypeError(f"model-chat Invocation resolved a non-gateway provider: {provider!r}")
    return await _dispatch_gateway_model_chat(provider, request, endpoint, on_chunk=on_chunk)


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
            f"adapter {spec.adapter_id!r}"
            f"{_adapter_identity_suffix(spec)} refused the request before any HTTP "
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


def reset_gateway_resilience_state() -> None:
    """Clear process-local gateway resilience state between tests or recycle."""
    _GATEWAY_RATE_LIMITS.clear_all()
    _CONTEXT_PROBE.clear()


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
    "reset_gateway_resilience_state",
]
