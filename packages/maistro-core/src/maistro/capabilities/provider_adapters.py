"""The third-party model/provider adapter SDK (M9-E1, #961).

An out-of-tree provider package implements :class:`ProviderAdapter` plus a
declarative :class:`ProviderAdapterSpec`, and registers both through
:func:`register_adapter_models`. Registration is the only seam an adapter
needs; it adds the declared models to the canonical ADR-079 registry so
:class:`~maistro.providers.router.CostAwareRouter` selects them under the same
cost/latency/fallback policy as built-in models — no core routing edit, and no
second routing authority.

What an adapter can and cannot do is the point of this module:

- **Egress stays canonical.** An adapter normalizes requests and responses at
  the edge of :mod:`maistro.capabilities.providers.llm_gateway`, the one
  approved module that holds an HTTP client for a model endpoint. The adapter
  never owns a transport: no HTTP client import, no sockets, no retry loop.
- **Secrets stay canonical.** The spec has no field that could carry one
  (``extra="forbid"`` refuses ``api_key``-shaped declarations outright). The
  physical credential is resolved per call by
  :class:`~maistro.capabilities.credential_routing.CredentialRouting` from the
  scoped credential pool, and the approved transport injects it per the
  declared auth style. An adapter declares *how* a secret is presented, never
  the secret.
- **Policy stays canonical.** Provider selection, Binding authorization,
  policy evaluation, Invocation recording, quota, and resilience classification
  are unchanged by adapters: a model declared by an adapter is selected,
  authorized, invoked, recorded, and circuit-broken exactly like a built-in
  one (ADR-081226-6b46).
- **Unsupported means refused.** Capabilities an adapter does not declare
  (tools, structured output) fail as a typed
  :class:`~maistro.capabilities.types.Unavailable` resolution — explicitly,
  before any HTTP.

Registration runs :func:`run_adapter_conformance` — the same data-contract
suite shipped providers and out-of-tree adapters must pass — and refuses a
malformed adapter at wiring time instead of at 3 a.m. inside a Run.
The built-in :class:`ReferenceChatAdapter` is itself registered through this
SDK, so the reference and every external adapter are held to one contract.

Operator wiring mirrors :mod:`maistro.capabilities.model_binding_bootstrap`:
:func:`bootstrap_provider_adapters` reads ``AgentConfig.provider_adapters``
(deployment configuration, not adapter-package configuration), registers the
declared adapter's models, provisions its credential into the scoped pool under
the adapter's declared reference, and loads one ``model.chat`` Binding per
entry. A provider registry entry never authorizes itself: no configured
adapter produces an authorized Binding.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from maistro.capabilities.binding import Binding
from maistro.capabilities.providers.llm_gateway import MODEL_CHAT_CAPABILITY
from maistro.credentials.types import CredentialRecord
from maistro.providers.types import ModelMetadata, ModelTier

if TYPE_CHECKING:
    from collections.abc import Mapping

    from maistro.capabilities.effect_context import CapabilityEffectContext
    from maistro.capabilities.providers.llm_gateway import ModelChatRequest
    from maistro.providers.registry import InMemoryProviderRegistry
    from maistro.types.config import AdapterInstanceConfig, AgentConfig

    def _vulture_pydantic_contract_usage() -> None:
        """Keep reflection-owned Pydantic surface visible to production-only Vulture scans."""

        _ = ProviderAdapterSpec._validate_spec

    _ = _vulture_pydantic_contract_usage

#: Trust tier recorded for third-party adapter providers. The shipped gateway
#: is ``t1``; adapters are one step below it by declaration, and both remain
#: subject to the same Binding/policy ceiling.
ADAPTER_TRUST_TIER = "t2"

#: The id of the built-in reference adapter. It ships in this module and
#: registers through exactly the same seam an external package uses, so the
#: conformance suite's "where contracts overlap" claim is executed, not
#: asserted.
REFERENCE_ADAPTER_ID = "maistro.reference"

#: The one wire protocol this SDK transports. The OpenAI-compatible
#: chat-completions body is the canonical model wire protocol (the shipped
#: gateway speaks it, ``maistro.testing.faux_provider`` speaks it), so an
#: adapter normalizes *into* it. A provider that cannot must fail its
#: registration rather than smuggle in a second transport.
AdapterProtocolName = Literal["openai-chat-completions"]

_PROTOCOL_NAME: str = "openai-chat-completions"

logger = logging.getLogger("maistro.capabilities.provider_adapters")

#: Field names an adapter spec must never carry. ``extra="forbid"`` already
#: refuses them at parse time; the conformance suite re-asserts the empty
#: intersection so a foreign spec object cannot argue with the schema.
_SECRET_FIELD_NAMES = frozenset({"api_key", "apikey", "secret", "token", "password"})


class AdapterRegistrationError(RuntimeError):
    """An adapter package was refused at registration.

    Registration is fail-closed: a spec that validates, a model list that is
    internally consistent, and a conformance pass are all required before any
    model metadata enters the canonical registry.
    """


class AdapterCapabilities(BaseModel):
    """Feature flags an adapter (or one of its models) declares.

    Least authority by default: every flag defaults to ``False`` and a
    capability that is not declared is refused at resolution time. Flags may
    only narrow from adapter to model — a model cannot declare a capability
    its adapter does not.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    streaming: bool = False
    tools: bool = False
    structured_output: bool = False

    def supports(self, other: AdapterCapabilities) -> bool:
        """Whether ``other`` narrows (or equals) these adapter-level flags."""

        return (
            (not other.streaming or self.streaming)
            and (not other.tools or self.tools)
            and (not other.structured_output or self.structured_output)
        )


class AdapterModelSpec(BaseModel):
    """One model an adapter declares, with the metadata canonical routing needs.

    The fields mirror :class:`~maistro.providers.types.ModelMetadata` because
    registration maps 1:1 into the ADR-079 registry: cost drives the
    cost-aware router, latency drives tie-breaking, and ``fallback_to`` joins
    the model into the same ADR-038 fallback chains built-in models use.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    cost_per_1k_input: float = Field(ge=0)
    cost_per_1k_output: float = Field(ge=0)
    latency_p50_ms: int = Field(ge=0)
    tier: ModelTier = "balanced"
    reasoning_capable: bool = False
    max_tokens: int = Field(default=4096, ge=1)
    fallback_to: tuple[str, ...] = ()
    capabilities: AdapterCapabilities = Field(default_factory=AdapterCapabilities)


class AdapterAuthStyle:
    """How the approved transport presents the resolved credential.

    Declared, not coded: the adapter names a style, the transport applies the
    scoped secret. String constants keep adapter implementations
    dependency-free and the spec plain JSON.
    """

    BEARER = "bearer"
    HEADER = "header"
    QUERY = "query"

    ALL = (BEARER, HEADER, QUERY)


class AdapterErrorKind:
    """The canonical provider error taxonomy adapters classify statuses into.

    The kind selects which canonical exception the approved transport raises;
    resilience classification (cooldown/block per ADR-063) stays with
    :mod:`maistro.resilience.classifier`, reading the carried HTTP status.
    String constants keep adapter implementations dependency-free.
    """

    AUTH = "auth"
    RATE_LIMITED = "rate_limited"
    RETRYABLE = "retryable"
    PERMANENT = "permanent"

    ALL = (AUTH, RATE_LIMITED, RETRYABLE, PERMANENT)


class ProviderAdapterSpec(BaseModel):
    """The declarative manifest an out-of-tree provider package registers.

    This is discovery/config schema, auth requirements, and the error/timeout
    taxonomy in one immutable value. It intentionally has no secret field: a
    manifest that arrived with credential material in it is a misconfigured
    package, and ``extra="forbid"`` turns that into a validation error instead
    of a plaintext secret crossing the SDK boundary.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    adapter_id: str
    display_name: str
    #: The provider package's endpoint root. Adapters reach their own service
    #: through the approved transport only; the URL is declared here so the
    #: outbound-policy seam (ADR-082326-5386) guards every destination.
    base_url: str
    protocol: AdapterProtocolName = "openai-chat-completions"
    auth_style: str = AdapterAuthStyle.BEARER
    auth_scheme: str = "Bearer"
    auth_header_name: str = "Authorization"
    auth_query_param: str = "api_key"
    #: The physical credential pool this adapter consumes and the logical
    #: reference a Binding must authorize. Both are declarations; the secret
    #: itself is provisioned by operator configuration through
    #: :func:`bootstrap_provider_adapters` into the scoped credential router.
    credential_provider: str
    credential_ref: str
    timeout_s: float = Field(default=120.0, gt=0)
    capabilities: AdapterCapabilities = Field(default_factory=AdapterCapabilities)
    models: tuple[AdapterModelSpec, ...] = Field(min_length=1)
    #: Unauthenticated health probe path (``""`` disables probing). A probe is
    #: deliberately unauthenticated: it reports provider-level health to the
    #: canonical router (ADR-081226-6b46) and must never drag a secret outside
    #: credential resolution.
    health_path: str = ""

    @model_validator(mode="after")
    def _validate_spec(self) -> ProviderAdapterSpec:
        self._validate_identity()
        self._validate_transport()
        self._validate_models()
        if self.health_path and not self.health_path.startswith("/"):
            raise ValueError(f"adapter health_path must start with '/': {self.health_path!r}")
        return self

    def _validate_identity(self) -> None:
        for value, label in (
            (self.adapter_id, "adapter_id"),
            (self.display_name, "display_name"),
            (self.credential_provider, "credential_provider"),
            (self.credential_ref, "credential_ref"),
        ):
            if not value.strip():
                raise ValueError(f"adapter {label} must be a non-empty string")

    def _validate_transport(self) -> None:
        if not self.base_url.lower().startswith(("http://", "https://")):
            raise ValueError(f"adapter base_url must be an http(s) URL: {self.base_url!r}")
        if self.protocol != _PROTOCOL_NAME:
            raise ValueError(
                f"adapter protocol {self.protocol!r} is not supported by this SDK; the "
                f"only transported protocol is {_PROTOCOL_NAME!r} (unsupported declarations "
                "fail explicitly at registration, never mid-call)"
            )
        if self.auth_style not in AdapterAuthStyle.ALL:
            raise ValueError(
                f"adapter auth_style {self.auth_style!r} is not one of {AdapterAuthStyle.ALL}"
            )
        if self.auth_style == AdapterAuthStyle.HEADER and not self.auth_header_name.strip():
            raise ValueError("auth_style 'header' requires a non-empty auth_header_name")
        if self.auth_style == AdapterAuthStyle.QUERY and not self.auth_query_param.strip():
            raise ValueError("auth_style 'query' requires a non-empty auth_query_param")

    def _validate_models(self) -> None:
        names = [model.name for model in self.models]
        if any(not name.strip() for name in names):
            raise ValueError("adapter model names must be non-empty")
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"adapter declares duplicate model names: {duplicates}")
        for model in self.models:
            if not self.capabilities.supports(model.capabilities):
                raise ValueError(
                    f"model {model.name!r} declares capabilities its adapter does not: "
                    f"model={model.capabilities.model_dump()} "
                    f"adapter={self.capabilities.model_dump()}"
                )

    def to_model_metadata(self, model: AdapterModelSpec) -> ModelMetadata:
        """Map one declared model into canonical registry metadata."""

        return ModelMetadata(
            name=model.name,
            provider=self.adapter_id,
            cost_per_1k_input=model.cost_per_1k_input,
            cost_per_1k_output=model.cost_per_1k_output,
            latency_p50_ms=model.latency_p50_ms,
            tier=model.tier,
            reasoning_capable=model.reasoning_capable,
            max_tokens=model.max_tokens,
            fallback_to=model.fallback_to,
        )


@runtime_checkable
class ProviderAdapter(Protocol):
    """The normalization contract an out-of-tree provider package implements.

    Every hook is data-in/data-out over canonical shapes; none of them see a
    credential, a socket, or an event loop they did not bring. The approved
    transport calls these around its one HTTP call, so a hook that misbehaves
    fails the adapter's registration conformance instead of leaking a second
    egress path.
    """

    @property
    def spec(self) -> ProviderAdapterSpec: ...

    def normalize_request(self, model: str, request: ModelChatRequest) -> dict[str, object]:
        """Canonical chat request -> the provider's JSON payload."""
        ...

    def normalize_response(self, payload: Mapping[str, object]) -> dict[str, object]:
        """Provider response body -> the canonical chat-completions body."""
        ...

    def usage_from(self, payload: Mapping[str, object]) -> tuple[int, int] | None:
        """(input_tokens, output_tokens) the provider reported, or ``None``."""
        ...

    def error_kind_for(self, status: int) -> str:
        """Map one HTTP status to an :class:`AdapterErrorKind` constant."""
        ...

    def health_from(self, payload: Mapping[str, object]) -> bool:
        """Whether a health-probe payload reports a healthy provider."""
        ...


@dataclass(frozen=True)
class AdapterGatewayProvider:
    """Resolved slot-specific provider handle for one adapter model call.

    Sibling of
    :class:`~maistro.capabilities.providers.llm_gateway.LlmGatewayProvider`:
    the same resolved-provider surface (name/slot/trust tier/credential pool),
    so Binding snapshots, credential routing, and Invocation persistence treat
    an adapter model exactly like a gateway model.
    """

    spec: ProviderAdapterSpec
    adapter: ProviderAdapter
    model: str
    capabilities: AdapterCapabilities
    metadata: ModelMetadata | None = None

    @property
    def name(self) -> str:
        return self.model

    @property
    def slot(self) -> str:
        return MODEL_CHAT_CAPABILITY

    @property
    def trust_tier(self) -> str:
        return ADAPTER_TRUST_TIER

    @property
    def credential_provider(self) -> str:
        return self.spec.credential_provider


class ProviderAdapterCatalog:
    """Registered adapters and the model-name -> adapter index they create.

    Holds no credentials and no HTTP state: registration records facts, and
    resolution hands the approved transport everything it needs to run one
    governed call. Health probing is the only outbound surface, and it is
    unauthenticated by declaration.
    """

    def __init__(self) -> None:
        self._adapters: dict[str, ProviderAdapter] = {}
        self._models: dict[str, tuple[str, AdapterModelSpec]] = {}
        self._unhealthy: dict[str, bool] = {}

    def register(self, adapter: ProviderAdapter) -> tuple[ModelMetadata, ...]:
        """Validate, conformance-check, and record one adapter.

        Raises :class:`AdapterRegistrationError` on a duplicate id, a model
        name already owned by another adapter, or any conformance failure.
        Returns the canonical metadata for the declared models. Nothing is
        recorded when any check fails.
        """

        self._refuse_duplicate_id(adapter)
        self._refuse_conformance_failure(adapter)
        self._refuse_foreign_model_claims(adapter)
        spec = adapter.spec
        self._adapters[spec.adapter_id] = adapter
        for model in spec.models:
            self._models[model.name] = (spec.adapter_id, model)
        return tuple(spec.to_model_metadata(model) for model in spec.models)

    def _refuse_duplicate_id(self, adapter: ProviderAdapter) -> None:
        if adapter.spec.adapter_id in self._adapters:
            raise AdapterRegistrationError(
                f"adapter {adapter.spec.adapter_id!r} is already registered"
            )

    def _refuse_conformance_failure(self, adapter: ProviderAdapter) -> None:
        report = run_adapter_conformance(adapter)
        if not report.ok:
            failed = ", ".join(check.name for check in report.failures)
            raise AdapterRegistrationError(
                f"adapter {adapter.spec.adapter_id!r} failed registration conformance: {failed}"
            )

    def _refuse_foreign_model_claims(self, adapter: ProviderAdapter) -> None:
        spec = adapter.spec
        claimed = [
            name
            for name, (owner, _) in self._models.items()
            if any(model.name == name and owner != spec.adapter_id for model in spec.models)
        ]
        if claimed:
            raise AdapterRegistrationError(
                f"adapter {spec.adapter_id!r} claims already-owned model names: {sorted(claimed)}"
            )

    def registered(self, adapter_id: str) -> ProviderAdapter | None:
        """The registered adapter with ``adapter_id``, or ``None``."""

        return self._adapters.get(adapter_id)

    def entry(self, model_name: str) -> tuple[ProviderAdapter, AdapterModelSpec] | None:
        """The adapter and model spec behind a registered model name."""

        found = self._models.get(model_name)
        if found is None:
            return None
        adapter_id, model = found
        adapter = self._adapters.get(adapter_id)
        if adapter is None:  # pragma: no cover - registration keeps them paired
            return None
        return adapter, model

    def registered_ids(self) -> tuple[str, ...]:
        """Every registered adapter id, in registration order."""

        return tuple(self._adapters)

    def model_names(self, adapter_id: str) -> tuple[str, ...]:
        """The model names one registered adapter declares."""

        return tuple(name for name, (owner, _) in self._models.items() if owner == adapter_id)

    def resolve_provider(
        self,
        model_name: str,
        metadata: ModelMetadata | None,
    ) -> AdapterGatewayProvider | None:
        """The resolved provider handle for an adapter model, or ``None``."""

        found = self.entry(model_name)
        if found is None:
            return None
        adapter, model = found
        return AdapterGatewayProvider(
            spec=adapter.spec,
            adapter=adapter,
            model=model_name,
            capabilities=model.capabilities,
            metadata=metadata,
        )

    async def probe_all(self) -> dict[str, bool]:
        """Probe every adapter that declares a health path.

        Results are recorded via :meth:`note_health` and returned; an adapter
        without a declared probe is absent from the result and its recorded
        health never changes.
        """

        from maistro.capabilities.providers.llm_gateway import probe_adapter_health

        results: dict[str, bool] = {}
        for adapter_id, adapter in self._adapters.items():
            if not adapter.spec.health_path:
                continue
            results[adapter_id] = await probe_adapter_health(adapter)
            self.note_health(adapter_id, results[adapter_id])
        return results

    def note_health(self, adapter_id: str, healthy: bool) -> None:
        """Record one provider health/capacity signal for canonical selection.

        Health recorded here is read inside canonical provider resolution — the
        same fail-closed seam as registry availability, minus a second mutation
        path: an adapter that failed its probe resolves as unavailable until a
        later probe (or an explicit operator call) restores it.
        """

        if healthy:
            self._unhealthy.pop(adapter_id, None)
        else:
            self._unhealthy[adapter_id] = False

    def is_healthy(self, adapter_id: str) -> bool:
        """The latest recorded health for an adapter (unknown counts as healthy).

        Absence of a signal is optimistic on purpose: canonical resilience owns
        circuit state after real calls (ADR-038/ADR-063), and a provider that
        never declared a probe is not thereby unhealthy.
        """

        return self._unhealthy.get(adapter_id, True)

    def unhealthy_adapters(self) -> tuple[str, ...]:
        """Adapters whose latest probe failed."""

        return tuple(sorted(self._unhealthy))


async def register_adapter_models(
    catalog: ProviderAdapterCatalog,
    registry: InMemoryProviderRegistry,
    adapter: ProviderAdapter,
) -> tuple[ModelMetadata, ...]:
    """The one registration seam for an out-of-tree provider package.

    Validates and conformance-checks the adapter into ``catalog``, then adds
    its model metadata to the canonical ADR-079 ``registry``. A model name the
    registry already holds under a different provider is refused — registration
    never silently re-sources an existing routing entry. Re-registering the
    same adapter object re-syncs its registry rows (idempotent re-wiring);
    a *different* object under a registered id is refused. This call is the
    whole integration: nothing in :mod:`maistro.providers` or
    :mod:`maistro.router` changes for a new provider.
    """

    from maistro.providers.errors import ModelNotFoundError

    existing = catalog.registered(adapter.spec.adapter_id)
    if existing is not None and existing is not adapter:
        raise AdapterRegistrationError(
            f"adapter {adapter.spec.adapter_id!r} is already registered as a different "
            "object; one id is one implementation"
        )
    metadata = _declared_metadata(adapter)
    # Refuse a re-source BEFORE anything is recorded: a collision must leave
    # both the catalog and the registry exactly as they were.
    for model in metadata:
        try:
            current = await registry.get_model(model.name)
        except ModelNotFoundError:
            current = None
        if current is not None and current.provider != model.provider:
            raise AdapterRegistrationError(
                f"model {model.name!r} is already registered from provider "
                f"{current.provider!r}; refusing to re-source it to {model.provider!r}"
            )
    if existing is None:
        metadata = catalog.register(adapter)
    for model in metadata:
        registry.register_model(model)
    return metadata


def _declared_metadata(adapter: ProviderAdapter) -> tuple[ModelMetadata, ...]:
    """Metadata for an adapter already in the catalog (idempotent re-wiring)."""

    return tuple(adapter.spec.to_model_metadata(model) for model in adapter.spec.models)


@dataclass(frozen=True)
class ConformanceCheck:
    """One executed conformance assertion over an adapter."""

    name: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class AdapterConformanceReport:
    """The full conformance result for one adapter."""

    adapter_id: str
    checks: tuple[ConformanceCheck, ...]

    @property
    def ok(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def failures(self) -> tuple[ConformanceCheck, ...]:
        return tuple(check for check in self.checks if not check.passed)


_PROBE_MESSAGES: tuple[dict[str, object], ...] = ({"role": "user", "content": "conformance"},)

_PROBE_RESPONSE: dict[str, object] = {
    "model": "probe-model",
    "choices": [{"message": {"role": "assistant", "content": "ok"}}],
    "usage": {"prompt_tokens": 7, "completion_tokens": 3},
}

#: Statuses the shared error-taxonomy contract pins. Where the canonical
#: resilience classifier's behavior depends on the canonical exception type an
#: adapter's kind selects, the mapping must agree; classification of every
#: other status inside the taxonomy is the adapter's documented freedom.
_PINNED_ERROR_STATUSES: tuple[tuple[int, str], ...] = (
    (401, AdapterErrorKind.AUTH),
    (403, AdapterErrorKind.AUTH),
    (429, AdapterErrorKind.RATE_LIMITED),
)
_EXERCISED_ERROR_STATUSES = (400, 401, 402, 403, 404, 408, 409, 429, 500, 502, 503, 504)


def run_adapter_conformance(adapter: ProviderAdapter) -> AdapterConformanceReport:
    """Run the shared provider-adapter conformance suite.

    This is the suite the built-in reference adapter and every out-of-tree
    adapter pass where contracts overlap: declaration honesty, request/response
    normalization shapes, usage reporting, the pinned error taxonomy, health
    normalization, and the no-secret-surface rule. It executes at registration
    so a nonconforming adapter is refused before any model enters canonical
    routing, and it is importable so external test suites can run the identical
    checks against their own packages.
    """

    checks = (
        _check_spec_type(adapter),
        _check_no_secret_surface(adapter),
        _check_request_normalization(adapter),
        _check_response_normalization(adapter),
        _check_usage_reporting(adapter),
        _check_error_taxonomy(adapter),
        _check_health_normalization(adapter),
    )
    return AdapterConformanceReport(adapter_id=adapter.spec.adapter_id, checks=checks)


def _check_spec_type(adapter: ProviderAdapter) -> ConformanceCheck:
    spec = adapter.spec
    return ConformanceCheck(
        name="spec_type",
        passed=isinstance(spec, ProviderAdapterSpec),
        detail=f"spec is {type(spec).__name__}",
    )


def _check_no_secret_surface(adapter: ProviderAdapter) -> ConformanceCheck:
    spec = adapter.spec
    # __dict__ rather than model_fields alone: a schema change adding a secret
    # field and an attribute smuggled past validation both land on the
    # instance, and both must fail the suite.
    return ConformanceCheck(
        name="no_secret_surface",
        passed=not (set(spec.__dict__) & _SECRET_FIELD_NAMES),
        detail="spec declares no secret-shaped field",
    )


def _check_request_normalization(adapter: ProviderAdapter) -> ConformanceCheck:
    from maistro.capabilities.providers.llm_gateway import ModelChatRequest

    model_name = adapter.spec.models[0].name
    request = ModelChatRequest(model=model_name, messages=[dict(m) for m in _PROBE_MESSAGES])
    try:
        payload = adapter.normalize_request(model_name, request)
        json.dumps(payload, default=str)
    except Exception as exc:
        return ConformanceCheck(
            name="request_normalization",
            passed=False,
            detail=f"raised {type(exc).__name__}: {exc}",
        )
    shaped = isinstance(payload, dict) and payload.get("model") == model_name
    return ConformanceCheck(
        name="request_normalization",
        passed=shaped,
        detail="normalized payload is a JSON object naming the model"
        if shaped
        else f"payload {payload!r} is not a JSON object naming the model",
    )


def _check_response_normalization(adapter: ProviderAdapter) -> ConformanceCheck:
    try:
        body = adapter.normalize_response(dict(_PROBE_RESPONSE))
    except Exception as exc:
        return ConformanceCheck(
            name="response_normalization",
            passed=False,
            detail=f"raised {type(exc).__name__}: {exc}",
        )
    choices = body.get("choices") if isinstance(body, dict) else None
    shaped = isinstance(choices, list) and len(choices) > 0
    return ConformanceCheck(
        name="response_normalization",
        passed=shaped,
        detail="normalized body carries canonical choices"
        if shaped
        else f"normalized body {body!r} has no canonical choices",
    )


def _check_usage_reporting(adapter: ProviderAdapter) -> ConformanceCheck:
    try:
        # The transport feeds usage_from the adapter-normalized body (the same
        # body the Invocation persists), so the suite exercises exactly that
        # flow: normalize_response first, then report usage off the result.
        usage = adapter.usage_from(adapter.normalize_response(dict(_PROBE_RESPONSE)))
    except Exception as exc:
        return ConformanceCheck(
            name="usage_reporting", passed=False, detail=f"raised {type(exc).__name__}: {exc}"
        )
    return ConformanceCheck(
        name="usage_reporting",
        passed=usage == (7, 3),
        detail=f"usage_from(normalized probe) = {usage!r}, expected (7, 3)",
    )


def _check_error_taxonomy(adapter: ProviderAdapter) -> ConformanceCheck:
    taxonomy_failures: list[str] = []
    try:
        for status, expected in _PINNED_ERROR_STATUSES:
            if adapter.error_kind_for(status) != expected:
                taxonomy_failures.append(f"HTTP {status} must map to {expected!r}")
        for status in _EXERCISED_ERROR_STATUSES:
            if adapter.error_kind_for(status) not in AdapterErrorKind.ALL:
                taxonomy_failures.append(f"HTTP {status} mapped outside the canonical taxonomy")
    except Exception as exc:
        taxonomy_failures.append(f"raised {type(exc).__name__}: {exc}")
    return ConformanceCheck(
        name="error_taxonomy",
        passed=not taxonomy_failures,
        detail="; ".join(taxonomy_failures) or "pinned statuses map canonically",
    )


def _check_health_normalization(adapter: ProviderAdapter) -> ConformanceCheck:
    try:
        healthy = adapter.health_from({"status": "ok"})
    except Exception as exc:
        return ConformanceCheck(
            name="health_normalization", passed=False, detail=f"raised {type(exc).__name__}: {exc}"
        )
    return ConformanceCheck(
        name="health_normalization",
        passed=isinstance(healthy, bool),
        detail=f"health_from(probe) = {healthy!r}",
    )


class ReferenceChatAdapter:
    """The built-in reference provider, built on the public SDK contract.

    It normalizes the canonical chat-completions body to itself — the correct
    behavior for an OpenAI-compatible upstream — and exists so the conformance
    suite has an in-repo yardstick: whatever passes for the reference must pass
    for every external adapter too, because both register through
    :func:`register_adapter_models`.
    """

    def __init__(self, spec: ProviderAdapterSpec) -> None:
        self._spec = spec

    @property
    def spec(self) -> ProviderAdapterSpec:
        return self._spec

    def normalize_request(self, model: str, request: ModelChatRequest) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": model,
            "messages": [dict(message) for message in request.messages],
            "temperature": request.temperature,
            "stream": False,
        }
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if request.tools:
            payload["tools"] = [dict(tool) for tool in request.tools]
        if request.tool_choice:
            payload["tool_choice"] = request.tool_choice
        if request.response_format is not None:
            payload["response_format"] = dict(request.response_format)
        return payload

    def normalize_response(self, payload: Mapping[str, object]) -> dict[str, object]:
        return dict(payload)

    def usage_from(self, payload: Mapping[str, object]) -> tuple[int, int] | None:
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            return None
        try:
            return (
                int(usage.get("prompt_tokens", 0) or 0),
                int(usage.get("completion_tokens", 0) or 0),
            )
        except (TypeError, ValueError):
            return None

    def error_kind_for(self, status: int) -> str:
        if status in (401, 403):
            return AdapterErrorKind.AUTH
        if status == 429:
            return AdapterErrorKind.RATE_LIMITED
        if status >= 500 or status in (408, 409):
            return AdapterErrorKind.RETRYABLE
        return AdapterErrorKind.PERMANENT

    def health_from(self, payload: Mapping[str, object]) -> bool:
        return payload.get("status") in (None, "ok", "healthy")


def reference_adapter_spec() -> ProviderAdapterSpec:
    """The built-in reference adapter's spec, ready to register."""

    return ProviderAdapterSpec(
        adapter_id=REFERENCE_ADAPTER_ID,
        display_name="MAIstro reference chat adapter",
        base_url="http://litellm:4000",
        credential_provider="litellm",
        credential_ref="litellm-gateway",
        capabilities=AdapterCapabilities(tools=True, structured_output=True),
        models=(
            AdapterModelSpec(
                name="reference-chat",
                cost_per_1k_input=0.5,
                cost_per_1k_output=1.5,
                latency_p50_ms=900,
                tier="balanced",
            ),
        ),
    )


# --- Process-default composition (mirrors capabilities.effect_context) -------


_default_catalog: ProviderAdapterCatalog | None = None


def configure_default_adapter_catalog(catalog: ProviderAdapterCatalog) -> None:
    """Publish the Container-composed catalog as the process default.

    ``None`` stays the default until a container wires one, so a deployment
    with no adapter configuration behaves exactly like the pre-SDK gateway
    path.
    """

    global _default_catalog
    _default_catalog = catalog


def release_default_adapter_catalog(catalog: ProviderAdapterCatalog) -> None:
    """Withdraw one container's catalog at shutdown, identity-checked."""

    global _default_catalog
    if _default_catalog is catalog:
        _default_catalog = None


def reset_default_adapter_catalog() -> None:
    """Clear the process default (tests and isolated compositions)."""

    global _default_catalog
    _default_catalog = None


def default_adapter_catalog() -> ProviderAdapterCatalog | None:
    """The process default catalog, or ``None`` when none was configured.

    ``None`` means "no adapters exist", which routes every model through the
    shipped gateway exactly as before the SDK existed — absence never widens
    what a model call may do.
    """

    return _default_catalog


# --- Operator bootstrap ------------------------------------------------------


async def bootstrap_provider_adapters(
    config: AgentConfig,
    effects: CapabilityEffectContext,
    registry: InMemoryProviderRegistry,
    catalog: ProviderAdapterCatalog,
) -> tuple[Binding, ...]:
    """Load configured provider adapters into one canonical effect context.

    For every ``config.provider_adapters`` entry this resolves the adapter by
    id — ``maistro.reference`` self-registers here; any other id must already
    have been registered by the host through :func:`register_adapter_models`
    (an out-of-tree package's only seam) — wires its model metadata into the
    canonical registry, provisions the entry's ``adapter_key`` (deployment
    configuration, never adapter-package configuration) into the scoped
    credential router under the adapter's declared
    ``(credential_provider, credential_ref)``, and loads one ``model.chat``
    Binding authorizing exactly that reference.

    Authorization stays fail-closed exactly as in
    :func:`maistro.capabilities.model_binding_bootstrap.bootstrap_model_bindings`:
    an entry with no ``adapter_key`` still loads its Binding, but every call
    through it refuses at credential acquisition until an operator provisions
    one. A declared pin must name a model the adapter declares, and a
    ``credential_refs`` override may only restate the adapter's own reference —
    there is no production surface that registers any other reference, so
    allowing one would authorize a Binding that can never acquire a credential.
    """

    loaded: list[Binding] = []
    for declared in config.provider_adapters:
        adapter = await _entry_adapter(catalog, registry, declared)
        spec = adapter.spec
        workspace_id = declared.workspace_id.strip() or config.workspace_id
        credential_refs = _entry_credential_refs(declared, spec)
        _provision_entry_credential(effects, declared, spec, workspace_id)
        await _probe_entry_health(catalog, declared)
        await _entry_registry_rows(catalog, registry, declared, adapter)
        binding = Binding.model_validate(
            {
                "binding_id": declared.binding_id,
                "workspace_id": workspace_id,
                "project_id": declared.project_id,
                "capability": MODEL_CHAT_CAPABILITY,
                "provider_name": declared.provider_name,
                "disabled": declared.disabled,
                "credential_refs": credential_refs,
                "config": {"adapter_id": declared.adapter_id},
            }
        )
        loaded.append(await effects.bindings.put(binding))
    return tuple(loaded)


async def _entry_adapter(
    catalog: ProviderAdapterCatalog,
    registry: InMemoryProviderRegistry,
    declared: AdapterInstanceConfig,
) -> ProviderAdapter:
    """Resolve one configured entry's adapter, self-registering the reference."""

    from maistro.types.errors import ConfigError

    adapter = catalog.registered(declared.adapter_id)
    if adapter is not None:
        return adapter
    if declared.adapter_id == REFERENCE_ADAPTER_ID:
        reference = ReferenceChatAdapter(reference_adapter_spec())
        await register_adapter_models(catalog, registry, reference)
        return reference
    raise ConfigError(
        f"provider adapter {declared.adapter_id!r} is not registered "
        f"(registered: {catalog.registered_ids()}). Register out-of-tree provider packages "
        "through maistro.capabilities.provider_adapters.register_adapter_models before "
        "configuring Bindings for them."
    )


def _entry_credential_refs(
    declared: AdapterInstanceConfig, spec: ProviderAdapterSpec
) -> tuple[str, ...]:
    """The refs a Binding may authorize: the adapter's own reference, only."""

    from maistro.types.errors import ConfigError

    credential_refs = declared.credential_refs or (spec.credential_ref,)
    foreign = [ref for ref in credential_refs if ref != spec.credential_ref]
    if foreign:
        raise ConfigError(
            f"provider adapter Binding {declared.binding_id!r} declares credential_refs="
            f"{credential_refs!r}, but adapter {declared.adapter_id!r} declares exactly "
            f"{spec.credential_ref!r}. There is no production configuration surface that "
            f"registers a credential under {foreign!r}, so this Binding would authorize "
            "nothing and every call through it would fail at runtime with CredentialScopeError."
        )
    return credential_refs


def _validate_entry_pin(catalog: ProviderAdapterCatalog, declared: AdapterInstanceConfig) -> None:
    """Refuse a pin naming a model the adapter does not declare."""

    from maistro.types.errors import ConfigError

    if not declared.provider_name:
        return
    declared_models = catalog.model_names(declared.adapter_id)
    if declared.provider_name not in declared_models:
        raise ConfigError(
            f"provider adapter Binding {declared.binding_id!r} pins model "
            f"{declared.provider_name!r}, but adapter {declared.adapter_id!r} declares "
            f"{declared_models}"
        )


def _provision_entry_credential(
    effects: CapabilityEffectContext,
    declared: AdapterInstanceConfig,
    spec: ProviderAdapterSpec,
    workspace_id: str,
) -> None:
    """Register the operator-supplied secret under the adapter's declared refs."""

    if not declared.adapter_key:
        return
    effects.credentials.add(
        workspace_id=workspace_id,
        project_id=declared.project_id,
        record=CredentialRecord(
            key_id=spec.credential_ref,
            provider=spec.credential_provider,
            api_key=declared.adapter_key,
        ),
    )


async def _probe_entry_health(
    catalog: ProviderAdapterCatalog,
    declared: AdapterInstanceConfig,
) -> None:
    """Run the operator-requested boot probe and log what failed."""

    if not declared.probe_health_at_boot:
        return
    await catalog.probe_all()
    failed = catalog.unhealthy_adapters()
    if failed:
        logger.warning(
            "provider adapters failed their boot health probe: %s; their models refuse "
            "canonical selection until a probe recovers",
            failed,
        )


async def _entry_registry_rows(
    catalog: ProviderAdapterCatalog,
    registry: InMemoryProviderRegistry,
    declared: AdapterInstanceConfig,
    adapter: ProviderAdapter,
) -> None:
    """Make sure the entry's model metadata exists in the canonical registry."""

    from maistro.providers.errors import ModelNotFoundError

    _validate_entry_pin(catalog, declared)
    try:
        await registry.get_model(
            declared.provider_name or catalog.model_names(declared.adapter_id)[0]
        )
    except ModelNotFoundError:
        await register_adapter_models(catalog, registry, adapter)


__all__ = [
    "ADAPTER_TRUST_TIER",
    "REFERENCE_ADAPTER_ID",
    "AdapterAuthStyle",
    "AdapterCapabilities",
    "AdapterConformanceReport",
    "AdapterErrorKind",
    "AdapterGatewayProvider",
    "AdapterModelSpec",
    "AdapterProtocolName",
    "AdapterRegistrationError",
    "ConformanceCheck",
    "ProviderAdapter",
    "ProviderAdapterCatalog",
    "ProviderAdapterSpec",
    "ReferenceChatAdapter",
    "bootstrap_provider_adapters",
    "configure_default_adapter_catalog",
    "default_adapter_catalog",
    "reference_adapter_spec",
    "register_adapter_models",
    "release_default_adapter_catalog",
    "reset_default_adapter_catalog",
    "run_adapter_conformance",
]
