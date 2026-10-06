"""Third-party provider adapter SDK (M9-E1, #961).

Acceptance coverage, each test naming the criterion it pins:

- an out-of-tree provider package registers models without editing core
  routing code — ``register_adapter_models`` is the whole integration, and the
  cost-aware router selects adapter models under canonical policy;
- secrets resolve through the canonical credential authority, never adapter
  plaintext config — the spec refuses secret-shaped fields, the transport
  injects the scoped credential per the declared auth style, and an adapter
  hook never sees the secret;
- provider errors, usage, and streaming map to canonical interfaces — adapter
  taxonomy raises canonical ``LlmAuthError``/``LlmHttpError`` with real HTTP
  statuses, usage reaches the canonical Invocation (with the adapter hook
  first), and the canonical stream contract yields one canonical body;
- a provider cannot bypass canonical routing/egress/security policy — adapter
  calls cross the same Binding/Invocation boundary, a foreign provider handle
  is a TypeError, and an unhealthy adapter feeds canonical availability
  instead of a private circuit breaker;
- unsupported features fail explicitly — undeclared tools/structured-output
  refuse as typed unavailable resolutions before any HTTP;
- the built-in reference adapter and a third-party-style adapter pass the same
  conformance suite, and the suite catches lying adapters.
"""

from __future__ import annotations

from typing import Any

import aiosqlite
import httpx
import pytest

from maistro.capabilities.binding import Binding
from maistro.capabilities.binding_store import SqliteBindingStore
from maistro.capabilities.effect_context import (
    CapabilityEffectContext,
    binding_scope_policy,
    new_effect_context,
    new_in_memory_effect_context,
)
from maistro.capabilities.invocation import (
    CapabilityUnavailable,
    InvocationStatus,
)
from maistro.capabilities.model_chat import (
    MODEL_CHAT_CAPABILITY,
    ModelChatEgress,
    ModelChatRequest,
    resolve_model_chat_provider,
)
from maistro.capabilities.provider_adapters import (
    AdapterErrorKind,
    AdapterGatewayProvider,
    AdapterRegistrationError,
    ProviderAdapterCatalog,
    ProviderAdapterSpec,
    ReferenceChatAdapter,
    bootstrap_provider_adapters,
    configure_default_adapter_catalog,
    default_adapter_catalog,
    reference_adapter_spec,
    register_adapter_models,
    registry_availability_sync,
    release_default_adapter_catalog,
    reset_default_adapter_catalog,
    run_adapter_conformance,
)
from maistro.capabilities.providers.llm_gateway import (
    GatewayEndpoint,
    LlmAuthError,
    LlmGatewayProvider,
    LlmHttpError,
    probe_adapter_health,
)
from maistro.capabilities.types import Unavailable
from maistro.credentials.types import CredentialRecord
from maistro.providers.errors import ModelNotFoundError
from maistro.providers.registry import InMemoryProviderRegistry
from maistro.providers.router import CostAwareRouter
from maistro.providers.types import ModelMetadata, RouterBudget, RoutingTask
from maistro.types.errors import ConfigError


def _spec(**overrides: Any) -> ProviderAdapterSpec:
    """A minimal valid third-party adapter spec, overridden per test."""

    values: dict[str, Any] = {
        "adapter_id": "acme.models",
        "display_name": "Acme inference",
        "base_url": "https://api.acme.example/v1",
        "credential_provider": "acme",
        "credential_ref": "acme-primary",
        "models": (
            {
                "name": "acme-mini",
                "cost_per_1k_input": 0.1,
                "cost_per_1k_output": 0.4,
                "latency_p50_ms": 120,
                "tier": "fast",
            },
            {
                "name": "acme-big",
                "cost_per_1k_input": 2.0,
                "cost_per_1k_output": 8.0,
                "latency_p50_ms": 900,
                "tier": "powerful",
            },
        ),
    }
    values.update(overrides)
    return ProviderAdapterSpec.model_validate(values)


class AcmeAdapter(ReferenceChatAdapter):
    """A fabricated out-of-tree adapter: SDK hooks over an Acme-style body.

    It differs from the reference exactly where a real third party would: its
    provider reports usage under ``token_counts`` and marks its stream healthy
    with a ``ready`` flag. Everything else stays the canonical passthrough.
    """

    def normalize_response(self, payload: dict[str, object]) -> dict[str, object]:
        body = dict(payload)
        counts = body.pop("token_counts", None)
        if isinstance(counts, dict):
            body["usage"] = counts
        return body

    def usage_from(self, payload: dict[str, object]) -> tuple[int, int] | None:
        # Reads the NORMALIZED canonical body — the same body the governed
        # transport hands back and the Invocation persists.
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            return None
        try:
            return (
                int(usage.get("input", usage.get("prompt_tokens", 0)) or 0),
                int(usage.get("output", usage.get("completion_tokens", 0)) or 0),
            )
        except (TypeError, ValueError):
            return None

    def error_kind_for(self, status: int) -> str:
        # Pinned to canonical classification (see ``_PINNED_ERROR_STATUSES``):
        # a third party classifies within the taxonomy, it cannot contradict
        # what the canonical resilience classifier does with the status.
        if status in (401, 403):
            return AdapterErrorKind.AUTH
        if status == 429:
            return AdapterErrorKind.RATE_LIMITED
        if status >= 500:
            return AdapterErrorKind.RETRYABLE
        return AdapterErrorKind.PERMANENT

    def health_from(self, payload: dict[str, object]) -> bool:
        return payload.get("ready") is True


async def _catalog_with(
    adapter: ReferenceChatAdapter | AcmeAdapter,
    registry: InMemoryProviderRegistry | None = None,
) -> tuple[ProviderAdapterCatalog, InMemoryProviderRegistry]:
    catalog = ProviderAdapterCatalog()
    store = registry if registry is not None else InMemoryProviderRegistry()
    await register_adapter_models(catalog, store, adapter)
    return catalog, store


# --- Declarative spec: discovery/config schema, fail-closed ------------------


def test_valid_spec_defaults_to_least_authority() -> None:
    spec = _spec()
    assert spec.capabilities.tools is False
    assert spec.capabilities.structured_output is False
    assert spec.capabilities.streaming is False
    assert spec.models[0].capabilities.tools is False
    assert spec.protocol == "openai-chat-completions"
    assert [model.name for model in spec.models] == ["acme-mini", "acme-big"]


def test_spec_refuses_duplicate_model_names() -> None:
    values = _spec().model_dump()
    values["models"] = (values["models"][0], values["models"][0])
    with pytest.raises(ValueError, match="duplicate model names"):
        ProviderAdapterSpec.model_validate(values)


def test_spec_refuses_model_capable_beyond_adapter() -> None:
    with pytest.raises(ValueError, match="capabilities its adapter does not"):
        _spec(
            models=(
                {
                    "name": "acme-mini",
                    "cost_per_1k_input": 0.1,
                    "cost_per_1k_output": 0.4,
                    "latency_p50_ms": 120,
                    "capabilities": {"tools": True},
                },
            )
        )


@pytest.mark.parametrize(
    ("auth_style", "field"),
    [("header", "auth_header_name"), ("query", "auth_query_param")],
)
def test_spec_auth_style_requires_its_parameter_name(auth_style: str, field: str) -> None:
    values = _spec(auth_style=auth_style).model_dump()
    values[field] = " "
    with pytest.raises(ValueError, match=field):
        ProviderAdapterSpec.model_validate(values)


def test_spec_refuses_non_http_base_url() -> None:
    with pytest.raises(ValueError, match=r"http\(s\) URL"):
        _spec(base_url="ftp://api.acme.example")


@pytest.mark.ac("SPEC-284/AC-2")
def test_spec_refuses_secret_fields_it_did_not_declare() -> None:
    """A manifest arriving with credential material is a misconfigured package."""

    values = _spec().model_dump()
    values["api_key"] = "sk-live-secret"
    with pytest.raises(ValueError):
        ProviderAdapterSpec.model_validate(values)


def test_spec_refuses_unsupported_protocol_explicitly() -> None:
    values = _spec().model_dump()
    values["protocol"] = "acme-private-protocol"
    # the Literal schema itself refuses before the SDK validator runs; either
    # way an unsupported protocol is a loud registration-time failure
    with pytest.raises(ValueError, match="openai-chat-completions"):
        ProviderAdapterSpec.model_validate(values)


def test_spec_refuses_relative_health_path() -> None:
    with pytest.raises(ValueError, match="health_path"):
        _spec(health_path="healthz")


# --- Conformance: one suite for built-in reference and third-party -----------


@pytest.mark.contract("behavioral")
@pytest.mark.ac("SPEC-284/AC-6")
async def test_builtin_reference_adapter_passes_conformance_and_registers() -> None:
    adapter = ReferenceChatAdapter(reference_adapter_spec())
    report = run_adapter_conformance(adapter)
    assert report.ok, [check.detail for check in report.failures]
    catalog, store = await _catalog_with(adapter)
    assert catalog.registered_ids() == ("maistro.reference",)
    assert store.is_available("reference-chat")


@pytest.mark.contract("behavioral")
@pytest.mark.ac("SPEC-284/AC-6")
async def test_third_party_style_adapter_passes_the_same_conformance_suite() -> None:
    adapter = AcmeAdapter(_spec())
    report = run_adapter_conformance(adapter)
    assert report.ok, [check.detail for check in report.failures]
    catalog, store = await _catalog_with(adapter)
    assert catalog.model_names("acme.models") == ("acme-mini", "acme-big")
    assert store.is_available("acme-mini")


@pytest.mark.ac("SPEC-284/AC-6")
def test_conformance_catches_an_adapter_lying_about_usage() -> None:
    class LyingUsage(AcmeAdapter):
        def usage_from(self, payload: dict[str, object]) -> tuple[int, int] | None:
            return (0, 0)

    report = run_adapter_conformance(LyingUsage(_spec()))
    failed = {check.name for check in report.failures}
    assert "usage_reporting" in failed
    assert not report.ok


@pytest.mark.ac("SPEC-284/AC-6")
def test_conformance_catches_an_adapter_outside_the_error_taxonomy() -> None:
    class RenegadeErrors(AcmeAdapter):
        def error_kind_for(self, status: int) -> str:
            if status == 401:
                return AdapterErrorKind.RETRYABLE  # must stay AUTH
            return super().error_kind_for(status)

    report = run_adapter_conformance(RenegadeErrors(_spec()))
    assert "error_taxonomy" in {check.name for check in report.failures}


def test_conformance_catches_a_response_normalizer_dropping_choices() -> None:
    class Lossy(AcmeAdapter):
        def normalize_response(self, payload: dict[str, object]) -> dict[str, object]:
            return {"usage": {"prompt_tokens": 1, "completion_tokens": 1}}

    report = run_adapter_conformance(Lossy(_spec()))
    assert "response_normalization" in {check.name for check in report.failures}


@pytest.mark.ac("SPEC-284/AC-6")
def test_conformance_catches_a_spec_carrying_a_secret_field() -> None:
    spec = _spec()
    # Simulate a spec that arrived with secret material on it (a schema-less
    # smuggle): the suite must see the attribute on the instance.
    object.__setattr__(spec, "__dict__", {**spec.__dict__, "api_key": "leaked"})
    assert spec.__dict__["api_key"] == "leaked"

    class Leaky(ReferenceChatAdapter):
        @property
        def spec(self) -> ProviderAdapterSpec:
            return spec  # type: ignore[return-value]

    report = run_adapter_conformance(Leaky(_spec()))
    assert "no_secret_surface" in {check.name for check in report.failures}


def test_conformance_refuses_a_raising_normalization_hook() -> None:
    class Exploding(AcmeAdapter):
        def normalize_request(self, model: str, request: Any) -> dict[str, object]:
            raise RuntimeError("adapter bug")

    report = run_adapter_conformance(Exploding(_spec()))
    assert "request_normalization" in {check.name for check in report.failures}


# --- Registration: the out-of-tree seam, no core routing edits ---------------


@pytest.mark.ac("SPEC-284/AC-1")
async def test_registration_places_models_in_canonical_registry_and_routing() -> None:
    catalog, store = await _catalog_with(AcmeAdapter(_spec()))
    router = CostAwareRouter(store)
    # acme-mini is cheapest AND lowest-latency: canonical policy selects an
    # adapter model exactly as it would a built-in one.
    selected = await router.select(RoutingTask(task_type="general"))
    assert selected.name == "acme-mini"
    assert selected.provider == "acme.models"
    # budget steering works over adapter models too
    powerful = await router.select(RoutingTask(task_type="general"), RouterBudget(reasoning=False))
    assert powerful.name in {"acme-mini", "acme-big"}
    resolved = catalog.resolve_provider("acme-big", await store.get_model("acme-big"))
    assert resolved is not None
    assert resolved.slot == MODEL_CHAT_CAPABILITY
    assert resolved.trust_tier == "t2"
    assert resolved.credential_provider == "acme"


async def test_registration_refuses_a_duplicate_adapter_id() -> None:
    catalog, store = await _catalog_with(AcmeAdapter(_spec()))
    with pytest.raises(AdapterRegistrationError, match="already registered"):
        await register_adapter_models(catalog, store, AcmeAdapter(_spec()))


async def test_registration_refuses_a_different_object_under_a_registered_id() -> None:
    catalog, store = await _catalog_with(AcmeAdapter(_spec()))
    impostor = AcmeAdapter(_spec(base_url="https://evil.example"))
    with pytest.raises(AdapterRegistrationError, match="different object"):
        await register_adapter_models(catalog, store, impostor)


async def test_registration_refuses_re_sourcing_an_existing_model_name() -> None:
    store = InMemoryProviderRegistry(
        models=[
            ModelMetadata(
                name="acme-mini",
                provider="someone-else",
                cost_per_1k_input=1.0,
                cost_per_1k_output=1.0,
                latency_p50_ms=100,
            )
        ]
    )
    catalog = ProviderAdapterCatalog()
    with pytest.raises(AdapterRegistrationError, match="re-source"):
        await register_adapter_models(catalog, store, AcmeAdapter(_spec()))
    assert catalog.registered_ids() == ()


async def test_registration_failure_records_nothing() -> None:
    class LyingUsage(AcmeAdapter):
        def usage_from(self, payload: dict[str, object]) -> tuple[int, int] | None:
            return (0, 0)

    catalog = ProviderAdapterCatalog()
    store = InMemoryProviderRegistry()
    with pytest.raises(AdapterRegistrationError, match="conformance"):
        await register_adapter_models(catalog, store, LyingUsage(_spec()))
    assert catalog.registered_ids() == ()
    with pytest.raises(ModelNotFoundError):
        await store.get_model("acme-mini")


async def test_reregistering_the_same_adapter_object_re_syncs_registry_rows() -> None:
    catalog = ProviderAdapterCatalog()
    store = InMemoryProviderRegistry()
    adapter = AcmeAdapter(_spec())
    await register_adapter_models(catalog, store, adapter)
    store.mark_unavailable("acme-mini")
    assert not store.is_available("acme-mini")
    await register_adapter_models(catalog, store, adapter)
    # re-sync re-registers metadata; availability stays an operator/router call
    assert (await store.get_model("acme-mini")).provider == "acme.models"


# --- Governed egress: canonical interfaces end to end ------------------------


class _CapturedGateway:
    """Stands in for the shared HTTP client and records what crossed it."""

    def __init__(
        self,
        response: dict[str, object] | None = None,
        *,
        status: int = 200,
        raise_on_post: Exception | None = None,
    ) -> None:
        self.response = (
            response
            if response is not None
            else {
                "model": "acme-mini-2026-01",
                "choices": [{"message": {"role": "assistant", "content": "hi"}}],
                "token_counts": {"input": 100, "output": 20},
            }
        )
        self.status = status
        self.raise_on_post = raise_on_post
        self.requests: list[dict[str, Any]] = []

    def client(self) -> Any:
        gateway = self

        class _Resp:
            def __init__(self, gateway: _CapturedGateway) -> None:
                self.status_code = gateway.status

            def json(self) -> Any:
                return gateway.response

        class _Client:
            # the shared-client pool checks is_closed on a cache hit
            is_closed = False

            async def __aenter__(self) -> _Client:
                return self

            async def __aexit__(self, *a: Any) -> None:
                return None

            async def aclose(self) -> None:
                return None

            async def post(self, url: str, **kwargs: Any) -> _Resp:
                gateway.requests.append({"url": url, **kwargs})
                if gateway.raise_on_post is not None:
                    raise gateway.raise_on_post
                return _Resp(gateway)

            async def get(self, url: str, **kwargs: Any) -> _Resp:
                gateway.requests.append({"url": url, **kwargs})
                return _Resp(gateway)

        return _Client()


def _acme_response(**overrides: Any) -> dict[str, object]:
    body: dict[str, object] = {
        "model": "acme-mini-2026-01",
        "choices": [{"message": {"role": "assistant", "content": "hi"}}],
        "token_counts": {"input": 100, "output": 20},
    }
    body.update(overrides)
    return body


def _effects(
    *,
    key_id: str = "acme-primary",
    provider: str = "acme",
    api_key: str = "resolved-acme-secret",
) -> CapabilityEffectContext:
    effects = new_in_memory_effect_context(policy_evaluator=binding_scope_policy)
    effects.credentials.add(
        workspace_id="ws1",
        project_id="p1",
        record=CredentialRecord(key_id=key_id, provider=provider, api_key=api_key),
    )
    return effects


def _binding(provider_name: str = "acme-mini", config: dict[str, object] | None = None) -> Binding:
    return Binding(
        workspace_id="ws1",
        project_id="p1",
        capability=MODEL_CHAT_CAPABILITY,
        provider_name=provider_name,
        credential_refs=("acme-primary",),
        config=config or {},
    )


def _egress(
    effects: CapabilityEffectContext,
    catalog: ProviderAdapterCatalog,
    store: InMemoryProviderRegistry,
) -> ModelChatEgress:
    return ModelChatEgress(
        effects,
        registry=store,
        router=CostAwareRouter(store),
        endpoint=GatewayEndpoint(base_url="http://litellm:4000"),
        adapters=catalog,
    )


@pytest.mark.contract("boundary")
@pytest.mark.ac("SPEC-284/AC-3")
async def test_adapter_call_records_canonical_invocation_with_usage_and_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _CapturedGateway(_acme_response())
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: captured.client())
    catalog, store = await _catalog_with(AcmeAdapter(_spec()))
    effects = _effects()

    result = await _egress(effects, catalog, store).complete(
        binding=_binding(config={"adapter_id": "acme.models"}),
        run_id="r1",
        node_run_id="nr1",
        attempt_id="a1",
        effect_key="test:acme",
        request=ModelChatRequest(
            model="acme-mini", messages=[{"role": "user", "content": "hello"}]
        ),
    )

    # usage came from the adapter's hook (token_counts, not OpenAI usage)
    assert result.usage is not None
    assert result.usage.input_units == 100
    assert result.usage.output_units == 20
    # cost from canonical registry metadata: 100*0.1/1000 + 20*0.4/1000
    assert result.usage.cost_cents == pytest.approx(0.01 + 0.008)
    assert result.usage.provider == "acme.models"
    assert result.usage.model_version == "acme-mini-2026-01"

    stored = await effects.invocation_store.get(result.invocation_id)
    assert stored is not None
    assert stored.status is InvocationStatus.COMPLETED
    assert stored.binding.provider_name == "acme-mini"
    assert stored.binding.provider_trust_tier == "t2"
    assert stored.binding.config == {"adapter_id": "acme.models"}
    assert stored.usage == result.usage

    # the wire carried the adapter's normalized payload over the canonical path
    assert len(captured.requests) == 1
    sent = captured.requests[0]
    assert sent["url"] == "https://api.acme.example/v1/chat/completions"
    assert sent["json"]["model"] == "acme-mini"
    # the canonical interface out: the adapter-normalized body (the provider's
    # token_counts moved into the canonical usage shape by the adapter)
    assert result.body["usage"] == {"input": 100, "output": 20}
    assert "token_counts" not in result.body


@pytest.mark.contract("boundary")
@pytest.mark.ac("SPEC-284/AC-2")
async def test_adapter_never_sees_the_secret_and_payload_carries_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_payloads: list[dict[str, Any]] = []

    class Snooping(AcmeAdapter):
        def normalize_request(self, model: str, request: Any) -> dict[str, object]:
            payload = super().normalize_request(model, request)
            seen_payloads.append(dict(payload))
            return payload

    captured = _CapturedGateway(_acme_response())
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: captured.client())
    catalog, store = await _catalog_with(Snooping(_spec()))
    effects = _effects(api_key="resolved-acme-secret")

    await _egress(effects, catalog, store).complete(
        binding=_binding(),
        run_id="r1",
        node_run_id="nr1",
        attempt_id="a1",
        effect_key="test:acme",
        request=ModelChatRequest(model="acme-mini", messages=[{"role": "user", "content": "h"}]),
    )

    # the hook received no credential argument at all: one registration
    # conformance probe per declared model plus the one governed call, all
    # secret-free
    assert [p["messages"] for p in seen_payloads] == [
        [{"role": "user", "content": "conformance"}],
        [{"role": "user", "content": "conformance"}],
        [{"role": "user", "content": "h"}],
    ]
    # the transport presented the scoped credential per the declared style
    sent = captured.requests[0]
    assert sent["headers"]["Authorization"] == "Bearer resolved-acme-secret"
    flat = repr(seen_payloads) + repr(sent["json"])
    assert "resolved-acme-secret" not in flat


async def test_query_auth_style_carries_the_credential_in_params_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _CapturedGateway(_acme_response())
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: captured.client())
    catalog, store = await _catalog_with(AcmeAdapter(_spec(auth_style="query")))
    effects = _effects(api_key="resolved-acme-secret")

    await _egress(effects, catalog, store).complete(
        binding=_binding(),
        run_id="r1",
        node_run_id="nr1",
        attempt_id="a1",
        effect_key="test:acme",
        request=ModelChatRequest(model="acme-mini", messages=[{"role": "user", "content": "h"}]),
    )

    sent = captured.requests[0]
    assert sent["params"] == {"api_key": "resolved-acme-secret"}
    assert "Authorization" not in sent["headers"]


async def test_header_auth_style_uses_the_declared_header_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _CapturedGateway(_acme_response())
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: captured.client())
    catalog, store = await _catalog_with(
        AcmeAdapter(_spec(auth_style="header", auth_header_name="X-Api-Key", auth_scheme=""))
    )
    effects = _effects(api_key="resolved-acme-secret")

    await _egress(effects, catalog, store).complete(
        binding=_binding(),
        run_id="r1",
        node_run_id="nr1",
        attempt_id="a1",
        effect_key="test:acme",
        request=ModelChatRequest(model="acme-mini", messages=[{"role": "user", "content": "h"}]),
    )

    sent = captured.requests[0]
    assert sent["headers"]["X-Api-Key"] == "resolved-acme-secret"
    assert "Authorization" not in sent["headers"]


@pytest.mark.parametrize(
    ("status", "exc_type", "code"),
    [
        (401, LlmAuthError, 401),
        (403, LlmAuthError, 403),
        (429, LlmHttpError, 429),
        (500, LlmHttpError, 500),
        (418, LlmHttpError, 418),
    ],
)
@pytest.mark.contract("behavioral")
@pytest.mark.ac("SPEC-284/AC-3")
async def test_adapter_error_taxonomy_raises_canonical_typed_errors(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    exc_type: type[Exception],
    code: int,
) -> None:
    captured = _CapturedGateway(_acme_response(), status=status)
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: captured.client())
    catalog, store = await _catalog_with(AcmeAdapter(_spec()))
    effects = _effects()

    with pytest.raises(exc_type) as excinfo:
        await _egress(effects, catalog, store).complete(
            binding=_binding(),
            run_id="r1",
            node_run_id="nr1",
            attempt_id="a1",
            effect_key="test:acme",
            request=ModelChatRequest(
                model="acme-mini", messages=[{"role": "user", "content": "h"}]
            ),
        )
    assert excinfo.value.status_code == code  # type: ignore[attr-defined]


async def test_unreachable_adapter_endpoint_is_retryable_not_applied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from maistro.capabilities.invocation import EffectNotApplied

    captured = _CapturedGateway(raise_on_post=httpx.ConnectError("adapter down"))
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: captured.client())
    catalog, store = await _catalog_with(AcmeAdapter(_spec()))
    effects = _effects()

    with pytest.raises(EffectNotApplied, match="no effect occurred"):
        await _egress(effects, catalog, store).complete(
            binding=_binding(),
            run_id="r1",
            node_run_id="nr1",
            attempt_id="a1",
            effect_key="test:acme",
            request=ModelChatRequest(
                model="acme-mini", messages=[{"role": "user", "content": "h"}]
            ),
        )


@pytest.mark.ac("SPEC-284/AC-5")
async def test_undeclared_tool_support_fails_explicitly_before_any_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _CapturedGateway(_acme_response())
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: captured.client())
    catalog, store = await _catalog_with(AcmeAdapter(_spec()))  # acme-mini: no tools
    effects = _effects()

    with pytest.raises(CapabilityUnavailable) as excinfo:
        await _egress(effects, catalog, store).complete(
            binding=_binding(),
            run_id="r1",
            node_run_id="nr1",
            attempt_id="a1",
            effect_key="test:acme",
            request=ModelChatRequest(
                model="acme-mini",
                messages=[{"role": "user", "content": "h"}],
                tools=[{"type": "function", "function": {"name": "ping"}}],
            ),
        )
    assert "does not declare" in str(excinfo.value)
    assert "explicitly" in str(excinfo.value)
    assert captured.requests == []


@pytest.mark.ac("SPEC-284/AC-5")
async def test_undeclared_structured_output_fails_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _CapturedGateway(_acme_response())
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: captured.client())
    catalog, store = await _catalog_with(AcmeAdapter(_spec()))
    effects = _effects()

    with pytest.raises(CapabilityUnavailable, match="structured output"):
        await _egress(effects, catalog, store).complete(
            binding=_binding(),
            run_id="r1",
            node_run_id="nr1",
            attempt_id="a1",
            effect_key="test:acme",
            request=ModelChatRequest(
                model="acme-mini",
                messages=[{"role": "user", "content": "h"}],
                response_format={"type": "json_object"},
            ),
        )
    assert captured.requests == []


async def test_declared_capabilities_pass_through_to_the_normalized_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _CapturedGateway(_acme_response(model="acme-big-2026-01"))
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: captured.client())
    capable = _spec(
        capabilities={"tools": True, "structured_output": True},
        models=(
            {
                "name": "acme-mini",
                "cost_per_1k_input": 0.1,
                "cost_per_1k_output": 0.4,
                "latency_p50_ms": 120,
                "tier": "fast",
            },
            {
                "name": "acme-big",
                "cost_per_1k_input": 2.0,
                "cost_per_1k_output": 8.0,
                "latency_p50_ms": 900,
                "tier": "powerful",
                "capabilities": {"tools": True, "structured_output": True},
            },
        ),
    )
    catalog, store = await _catalog_with(AcmeAdapter(capable))
    effects = _effects()

    result = await _egress(effects, catalog, store).complete(
        binding=_binding(provider_name="acme-big"),
        run_id="r1",
        node_run_id="nr1",
        attempt_id="a1",
        effect_key="test:acme",
        request=ModelChatRequest(
            model="acme-big",
            messages=[{"role": "user", "content": "h"}],
            tools=[{"type": "function", "function": {"name": "ping"}}],
            response_format={"type": "json_object"},
        ),
    )
    assert captured.requests[0]["json"]["tools"] == [
        {"type": "function", "function": {"name": "ping"}}
    ]
    assert captured.requests[0]["json"]["response_format"] == {"type": "json_object"}
    assert result.usage is not None


@pytest.mark.contract("boundary")
@pytest.mark.ac("SPEC-284/AC-4")
async def test_foreign_provider_handle_is_a_wiring_error_not_an_egress() -> None:
    class Rogue:
        """Impersonates a resolved provider but is neither gateway nor adapter."""

        name = "rogue"
        slot = MODEL_CHAT_CAPABILITY
        trust_tier = "t1"
        credential_provider = "rogue"

    with pytest.raises(TypeError, match="non-gateway provider"):
        from maistro.capabilities.providers.llm_gateway import execute_model_chat

        await execute_model_chat(
            Rogue(),  # type: ignore[arg-type]
            ModelChatRequest(model="rogue", messages=[]),
            endpoint=GatewayEndpoint(base_url="http://rogue.example", api_key="k"),
        )


async def test_unavailable_adapter_model_refuses_instead_of_falling_back() -> None:
    catalog, store = await _catalog_with(AcmeAdapter(_spec()))
    store.mark_unavailable("acme-mini")
    resolver = resolve_model_chat_provider(store, CostAwareRouter(store), adapters=catalog)
    resolved = await resolver(_binding())
    assert isinstance(resolved, Unavailable)
    assert "unavailable" in resolved.reason
    assert "does not fall back" in resolved.reason


@pytest.mark.ac("SPEC-284/AC-4")
async def test_router_selection_resolves_adapter_provider_for_unpinned_calls() -> None:
    catalog, store = await _catalog_with(AcmeAdapter(_spec()))
    resolver = resolve_model_chat_provider(store, CostAwareRouter(store), adapters=catalog)
    resolved = await resolver(_binding(provider_name=""))
    assert isinstance(resolved, AdapterGatewayProvider)
    assert resolved.name == "acme-mini"


@pytest.mark.ac("SPEC-284/AC-4")
async def test_unpinned_adapter_binding_stays_within_its_declared_adapter() -> None:
    """A faster foreign model must not win a credential-scoped Binding.

    The binding authorizes only acme's credential reference, so routing to
    the gateway or another adapter would resolve fine and then fail at
    credential acquisition (CredentialScopeError). Selection is scoped to
    the adapter recorded on the Binding.
    """

    store = InMemoryProviderRegistry(
        models=[
            ModelMetadata(
                name="gateway-model",
                provider="litellm",
                cost_per_1k_input=1.0,
                cost_per_1k_output=1.0,
                latency_p50_ms=100,
            )
        ]
    )
    catalog, store = await _catalog_with(AcmeAdapter(_spec()), store)
    faster = ReferenceChatAdapter(
        _spec(
            adapter_id="rival.models",
            display_name="Rival inference",
            credential_provider="rival",
            credential_ref="rival-primary",
            models=(
                {
                    "name": "rival-mini",
                    "cost_per_1k_input": 0.1,
                    "cost_per_1k_output": 0.4,
                    "latency_p50_ms": 60,
                    "tier": "fast",
                },
            ),
        )
    )
    await register_adapter_models(catalog, store, faster)
    resolver = resolve_model_chat_provider(store, CostAwareRouter(store), adapters=catalog)

    resolved = await resolver(_binding(provider_name="", config={"adapter_id": "acme.models"}))
    assert isinstance(resolved, AdapterGatewayProvider)
    assert resolved.name == "acme-mini"

    # An adapter with no eligible models is Unavailable, never re-scoped
    # wider to the models some other adapter could serve.
    empty = await resolver(_binding(provider_name="", config={"adapter_id": "absent.models"}))
    assert isinstance(empty, Unavailable)
    assert "no eligible model" in empty.reason


async def test_pinned_gateway_model_still_resolves_gateway_provider() -> None:
    store = InMemoryProviderRegistry(
        models=[
            ModelMetadata(
                name="gateway-model",
                provider="litellm",
                cost_per_1k_input=1.0,
                cost_per_1k_output=1.0,
                latency_p50_ms=100,
            )
        ]
    )
    catalog, _ = await _catalog_with(AcmeAdapter(_spec()), store)
    resolver = resolve_model_chat_provider(store, CostAwareRouter(store), adapters=catalog)
    binding = Binding(
        workspace_id="ws1",
        project_id="p1",
        capability=MODEL_CHAT_CAPABILITY,
        provider_name="gateway-model",
        credential_refs=("litellm-gateway",),
    )
    resolved = await resolver(binding)
    assert isinstance(resolved, LlmGatewayProvider)


# --- Process-default composition --------------------------------------------


def test_default_catalog_absence_keeps_gateway_only_behavior() -> None:
    reset_default_adapter_catalog()
    assert default_adapter_catalog() is None


def test_configure_and_release_default_catalog() -> None:
    catalog = ProviderAdapterCatalog()
    configure_default_adapter_catalog(catalog)
    assert default_adapter_catalog() is catalog

    release_default_adapter_catalog(catalog)
    assert default_adapter_catalog() is None
    reset_default_adapter_catalog()


def test_nested_catalog_close_restores_outer() -> None:
    """Closing an inner container hands the default back to the outer one.

    With the former single slot, B's configure overwrote A and B's release
    cleared the slot entirely, so egress clients built while A was still
    open silently lost adapter resolution (#1362, same rule as the
    effect-context stack).
    """

    reset_default_adapter_catalog()
    outer = ProviderAdapterCatalog()
    inner = ProviderAdapterCatalog()
    configure_default_adapter_catalog(outer)
    configure_default_adapter_catalog(inner)
    assert default_adapter_catalog() is inner

    release_default_adapter_catalog(inner)
    assert default_adapter_catalog() is outer

    release_default_adapter_catalog(outer)
    assert default_adapter_catalog() is None
    reset_default_adapter_catalog()


def test_republish_moves_catalog_to_top_without_duplicate() -> None:
    reset_default_adapter_catalog()
    outer = ProviderAdapterCatalog()
    inner = ProviderAdapterCatalog()
    configure_default_adapter_catalog(outer)
    configure_default_adapter_catalog(inner)
    configure_default_adapter_catalog(outer)
    assert default_adapter_catalog() is outer

    release_default_adapter_catalog(outer)
    assert default_adapter_catalog() is inner
    release_default_adapter_catalog(inner)
    assert default_adapter_catalog() is None
    reset_default_adapter_catalog()


# --- Health/capacity signals exposed to the canonical router -----------------


async def test_unhealthy_probe_refuses_canonical_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unhealthy(adapter: Any) -> bool:
        return False

    monkeypatch.setattr(
        "maistro.capabilities.providers.llm_gateway.probe_adapter_health", unhealthy
    )
    catalog, store = await _catalog_with(AcmeAdapter(_spec(health_path="/healthz")))
    await catalog.probe_adapter("acme.models")
    assert not catalog.is_healthy("acme.models")
    resolver = resolve_model_chat_provider(store, CostAwareRouter(store), adapters=catalog)
    resolved = await resolver(_binding())
    assert isinstance(resolved, Unavailable)
    assert "health" in resolved.reason


async def test_recovery_probe_restores_canonical_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcomes = [False, True]

    async def flapping(adapter: Any) -> bool:
        return outcomes.pop(0)

    monkeypatch.setattr("maistro.capabilities.providers.llm_gateway.probe_adapter_health", flapping)
    catalog, store = await _catalog_with(AcmeAdapter(_spec(health_path="/healthz")))
    catalog.set_availability_sync(registry_availability_sync(store))
    await catalog.probe_adapter("acme.models")
    assert not catalog.is_healthy("acme.models")
    assert not store.is_available("acme-mini")  # excluded from routing up front
    await catalog.probe_adapter("acme.models")
    assert catalog.is_healthy("acme.models")
    assert store.is_available("acme-mini")  # recovery restores routing
    resolver = resolve_model_chat_provider(store, CostAwareRouter(store), adapters=catalog)
    resolved = await resolver(_binding())
    assert isinstance(resolved, AdapterGatewayProvider)


async def test_unpinned_routing_falls_through_unhealthy_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One unhealthy adapter cannot take unpinned model traffic offline.

    With the availability sync wired, the cost-aware router skips the
    unhealthy adapter's models during selection and falls through to the
    healthy candidate instead of resolving one and refusing after the fact.
    """

    async def unhealthy(adapter: Any) -> bool:
        return False

    monkeypatch.setattr(
        "maistro.capabilities.providers.llm_gateway.probe_adapter_health", unhealthy
    )
    catalog, store = await _catalog_with(AcmeAdapter(_spec(health_path="/healthz")))
    # A healthy gateway alternative with worse latency: without the sync the
    # router deterministically prefers acme-mini (120ms) and resolution would
    # refuse; with it, selection never picks the unhealthy adapter's model.
    store.register_model(
        ModelMetadata(
            name="gateway-mini",
            provider="litellm",
            cost_per_1k_input=0.2,
            cost_per_1k_output=0.8,
            latency_p50_ms=300,
            tier="fast",
        )
    )
    catalog.set_availability_sync(registry_availability_sync(store))
    await catalog.probe_adapter("acme.models")
    assert not store.is_available("acme-mini")
    resolver = resolve_model_chat_provider(store, CostAwareRouter(store), adapters=catalog)
    resolved = await resolver(_binding(provider_name=""))
    assert isinstance(resolved, LlmGatewayProvider)
    assert resolved.name == "gateway-mini"


async def test_adapter_without_a_declared_probe_is_never_marked_unhealthy() -> None:
    catalog, store = await _catalog_with(AcmeAdapter(_spec()))
    await catalog.probe_adapter("acme.models")
    assert catalog.is_healthy("acme.models")
    resolver = resolve_model_chat_provider(store, CostAwareRouter(store), adapters=catalog)
    assert isinstance(await resolver(_binding()), AdapterGatewayProvider)


async def test_probe_adapter_health_follows_the_adapter_hook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from maistro.http import aclose_shared_clients

    captured = _CapturedGateway({"ready": True})
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: captured.client())
    adapter = AcmeAdapter(_spec(health_path="/healthz"))
    assert await probe_adapter_health(adapter) is True
    assert captured.requests[0]["url"] == "https://api.acme.example/v1/healthz"

    await aclose_shared_clients()
    captured = _CapturedGateway({"ready": False})
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: captured.client())
    assert await probe_adapter_health(AcmeAdapter(_spec(health_path="/healthz"))) is False

    await aclose_shared_clients()
    captured = _CapturedGateway({"ready": True}, status=503)
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: captured.client())
    assert await probe_adapter_health(AcmeAdapter(_spec(health_path="/healthz"))) is False

    await aclose_shared_clients()
    # an adapter that declares no probe is healthy by declaration, no HTTP
    captured = _CapturedGateway()
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: captured.client())
    assert await probe_adapter_health(AcmeAdapter(_spec())) is True
    assert captured.requests == []


async def test_probe_transport_failure_reads_unhealthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Failing:
        async def __aenter__(self) -> _Failing:
            return self

        async def __aexit__(self, *a: Any) -> None:
            return None

        async def get(self, *a: Any, **kw: Any) -> Any:
            raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: _Failing())
    adapter = AcmeAdapter(_spec(health_path="/healthz"))
    assert await probe_adapter_health(adapter) is False


# --- Operator bootstrap: secret authority and fail-closed wiring -------------


def _adapter_config(**overrides: Any) -> Any:
    from maistro.types.config import AdapterInstanceConfig

    values: dict[str, Any] = {
        "adapter_id": "acme.models",
        "binding_id": "binding-acme",
        "project_id": "p1",
        "workspace_id": "ws1",
        "adapter_key": "op-supplied-secret",
    }
    values.update(overrides)
    return AdapterInstanceConfig.model_validate(values)


class _ConfigShim:
    """The slice of AgentConfig bootstrap reads."""

    def __init__(self, entries: list[Any], workspace_id: str = "ws1") -> None:
        self.provider_adapters = entries
        self.workspace_id = workspace_id


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("adapter_id", ""),
        ("binding_id", "   "),
        ("project_id", ""),
    ],
)
def test_adapter_config_refuses_blank_identity_or_scope_fields(field: str, value: str) -> None:
    """Adapter wiring identity/scope fields are non-empty by validation."""

    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="non-empty"):
        _adapter_config(**{field: value})


@pytest.mark.parametrize("blank", ["", "  "])
def test_adapter_config_refuses_a_blank_credential_reference(blank: str) -> None:
    """A whitespace credential reference would authorize nothing: refuse."""

    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="adapter wiring refs cannot contain empty"):
        _adapter_config(credential_refs=("acme-primary", blank))


async def test_container_close_withdraws_its_published_adapter_catalog() -> None:
    """The container that published the process-default catalog withdraws it.

    Close must release exactly this container's catalog (identity-checked), so
    a shutdown does not leave adapter destinations pointing at a torn-down
    composition. create_container always publishes its catalog — even an
    unconfigured deployment's empty one — so this exercises the real wiring,
    not a hand-built dataclass.
    """

    from maistro.container import create_container
    from maistro.types.config import AgentConfig

    reset_default_adapter_catalog()
    assert default_adapter_catalog() is None
    container = await create_container(AgentConfig(router_api_key="test-key"))
    assert default_adapter_catalog() is container.provider_adapter_catalog

    try:
        await container.aclose()
        assert container.closed
        assert default_adapter_catalog() is None
    finally:
        reset_default_adapter_catalog()  # isolation for other suites


async def test_container_close_without_a_catalog_leaves_the_default_alone() -> None:
    """A container holding no catalog must not withdraw anyone else's.

    The False arc of the close-time guard: releasing the process default is
    conditional on this container actually publishing one, so a catalog-less
    shutdown leaves the process default exactly as it was.
    """

    from maistro.container import create_container
    from maistro.types.config import AgentConfig

    reset_default_adapter_catalog()
    container = await create_container(AgentConfig(router_api_key="test-key"))
    published = container.provider_adapter_catalog
    assert published is not None
    # Simulate the not-published composition: this container holds no catalog.
    container.provider_adapter_catalog = None
    try:
        await container.aclose()
        assert container.closed
        assert default_adapter_catalog() is published  # close withdrew nothing
    finally:
        reset_default_adapter_catalog()  # isolation for other suites


@pytest.mark.ac("SPEC-284/AC-2")
async def test_bootstrap_loads_binding_and_provisions_credential_via_authority() -> None:
    catalog, store = await _catalog_with(AcmeAdapter(_spec()))
    effects = new_in_memory_effect_context(policy_evaluator=binding_scope_policy)

    loaded = await bootstrap_provider_adapters(
        _ConfigShim([_adapter_config()]), effects, store, catalog
    )

    assert len(loaded) == 1
    binding = loaded[0]
    assert binding.capability == MODEL_CHAT_CAPABILITY
    assert binding.provider_name == ""
    assert binding.credential_refs == ("acme-primary",)
    assert binding.config == {"adapter_id": "acme.models"}
    # the secret lives in the canonical credential authority, under the
    # adapter's declared pool + reference, in exactly the Binding's scope
    record = await effects.credentials.acquire(
        workspace_id="ws1",
        project_id="p1",
        provider="acme",
        credential_refs=("acme-primary",),
    )
    assert record.api_key == "op-supplied-secret"
    # the Binding itself carries no secret material
    assert "op-supplied-secret" not in binding.model_dump_json()


async def test_bootstrap_restarts_idempotently_against_a_durable_binding_store() -> None:
    """A second boot over SQLite reuses the stored created_at, so the store's
    immutability check sees an identical definition instead of rejecting the
    re-registration as a changed one."""

    catalog, registry = await _catalog_with(AcmeAdapter(_spec()))
    async with aiosqlite.connect(":memory:") as conn:
        store = SqliteBindingStore(conn)
        await store.ensure_schema()
        effects = new_effect_context(binding_store=store, policy_evaluator=binding_scope_policy)

        first = await bootstrap_provider_adapters(
            _ConfigShim([_adapter_config()]), effects, registry, catalog
        )
        second = await bootstrap_provider_adapters(
            _ConfigShim([_adapter_config()]), effects, registry, catalog
        )

        assert second[0].created_at == first[0].created_at
        assert await store.get("binding-acme") == first[0]


async def test_bootstrap_pinned_model_resolves_after_registration() -> None:
    catalog, store = await _catalog_with(AcmeAdapter(_spec()))
    effects = new_in_memory_effect_context(policy_evaluator=binding_scope_policy)
    await bootstrap_provider_adapters(
        _ConfigShim([_adapter_config(provider_name="acme-big")]), effects, store, catalog
    )
    resolver = resolve_model_chat_provider(store, CostAwareRouter(store), adapters=catalog)
    resolved = await resolver(_binding(provider_name="acme-big"))
    assert isinstance(resolved, AdapterGatewayProvider)


async def test_bootstrap_refuses_an_unregistered_adapter_id() -> None:
    catalog = ProviderAdapterCatalog()
    store = InMemoryProviderRegistry()
    effects = new_in_memory_effect_context(policy_evaluator=binding_scope_policy)
    with pytest.raises(ConfigError, match="not registered"):
        await bootstrap_provider_adapters(
            _ConfigShim([_adapter_config(adapter_id="ghost.provider")]),
            effects,
            store,
            catalog,
        )


async def test_bootstrap_refuses_a_pin_outside_the_adapters_models() -> None:
    catalog, store = await _catalog_with(AcmeAdapter(_spec()))
    effects = new_in_memory_effect_context(policy_evaluator=binding_scope_policy)
    with pytest.raises(ConfigError, match="declares"):
        await bootstrap_provider_adapters(
            _ConfigShim([_adapter_config(provider_name="not-acme")]), effects, store, catalog
        )


@pytest.mark.ac("SPEC-284/AC-2")
async def test_bootstrap_refuses_a_foreign_credential_reference() -> None:
    catalog, store = await _catalog_with(AcmeAdapter(_spec()))
    effects = new_in_memory_effect_context(policy_evaluator=binding_scope_policy)
    with pytest.raises(ConfigError, match="authorize nothing"):
        await bootstrap_provider_adapters(
            _ConfigShim([_adapter_config(credential_refs=("some-other-ref",))]),
            effects,
            store,
            catalog,
        )


async def test_bootstrap_without_a_key_stays_fail_closed_at_acquisition() -> None:
    catalog, store = await _catalog_with(AcmeAdapter(_spec()))
    effects = new_in_memory_effect_context(policy_evaluator=binding_scope_policy)
    await bootstrap_provider_adapters(
        _ConfigShim([_adapter_config(adapter_key="")]), effects, store, catalog
    )
    from maistro.credentials.router import CredentialScopeError

    with pytest.raises(CredentialScopeError):
        await effects.credentials.acquire(
            workspace_id="ws1",
            project_id="p1",
            provider="acme",
            credential_refs=("acme-primary",),
        )


async def test_bootstrap_self_registers_the_builtin_reference_adapter() -> None:
    catalog = ProviderAdapterCatalog()
    store = InMemoryProviderRegistry()
    effects = new_in_memory_effect_context(policy_evaluator=binding_scope_policy)
    await bootstrap_provider_adapters(
        _ConfigShim(
            [
                _adapter_config(
                    adapter_id="maistro.reference",
                    binding_id="binding-ref",
                    credential_refs=(),
                )
            ]
        ),
        effects,
        store,
        catalog,
    )
    assert catalog.registered_ids() == ("maistro.reference",)
    assert (await store.get_model("reference-chat")).provider == "maistro.reference"


# --- Repair round: declared-URL honesty, taxonomy pins, scoped probes --------


@pytest.mark.parametrize(
    "url",
    [
        "http://",  # no host: a prefix check passes, httpx would not
        "https://",  # ditto
        "api.acme.example/v1",  # not absolute http(s)
        "https://user:secret@api.acme.example",  # credential material in the URL
        "http://[::1",  # unparseable IPv6
    ],
)
def test_spec_refuses_malformed_or_userinfo_base_urls(url: str) -> None:
    """A real parse, not a prefix check; userinfo is secret material."""

    with pytest.raises(ValueError, match="base_url"):
        _spec(base_url=url)


@pytest.mark.contract("behavioral")
async def test_registration_refuses_a_non_json_serializable_payload() -> None:
    """Conformance must use the transport's encoder rules, not a lenient one.

    ``json=`` on the shared client serializes with the standard encoder; an
    adapter whose payload carries a ``Decimal`` passes a ``default=str``
    conformance probe and then fails before its first real HTTP request.
    """

    from decimal import Decimal

    class DecimalPayload(AcmeAdapter):
        def normalize_request(self, model: str, request: Any) -> dict[str, object]:
            payload = super().normalize_request(model, request)
            if model == "acme-big":
                payload["weight"] = Decimal("0.5")
            return payload

    report = run_adapter_conformance(DecimalPayload(_spec()))
    failed = [check for check in report.checks if check.name == "request_normalization"]
    assert failed and not failed[0].passed
    assert "acme-big" in failed[0].detail

    catalog = ProviderAdapterCatalog()
    with pytest.raises(AdapterRegistrationError, match="request_normalization"):
        await register_adapter_models(catalog, InMemoryProviderRegistry(), DecimalPayload(_spec()))
    assert catalog.registered_ids() == ()  # nothing recorded on refusal


@pytest.mark.contract("behavioral")
async def test_registration_refuses_an_adapter_failing_on_a_later_model() -> None:
    """Conformance exercises every declared model, not only ``models[0]``.

    Registration publishes every model, so a model-specific normalizer bug
    must fail registration for that model instead of surfacing on its first
    production request.
    """

    class Selective(AcmeAdapter):
        def normalize_request(self, model: str, request: Any) -> dict[str, object]:
            if model == "acme-big":
                raise RuntimeError("big model needs a payload this adapter cannot build")
            return super().normalize_request(model, request)

    catalog = ProviderAdapterCatalog()
    with pytest.raises(AdapterRegistrationError, match="request_normalization"):
        await register_adapter_models(catalog, InMemoryProviderRegistry(), Selective(_spec()))
    assert catalog.registered_ids() == ()


@pytest.mark.ac("SPEC-284/AC-3")
def test_conformance_refuses_a_taxonomy_contradicting_canonical_classification() -> None:
    """A provider may classify within the taxonomy, never against it.

    Canonical resilience treats HTTP 500 as retryable; an adapter declaring
    it permanent would be advertising an override of canonical policy the
    adapter seam does not have.
    """

    class Overriding(AcmeAdapter):
        def error_kind_for(self, status: int) -> str:
            if status == 500:
                return AdapterErrorKind.PERMANENT
            return super().error_kind_for(status)

    report = run_adapter_conformance(Overriding(_spec()))
    failed = [check for check in report.checks if check.name == "error_taxonomy"]
    assert failed and not failed[0].passed
    assert "500" in failed[0].detail


@pytest.mark.ac("SPEC-284/AC-3")
def test_reference_error_taxonomy_matches_canonical_classification() -> None:
    from maistro.capabilities.provider_adapters import _PINNED_ERROR_STATUSES

    adapter = ReferenceChatAdapter(reference_adapter_spec())
    for status, kind in _PINNED_ERROR_STATUSES:
        assert adapter.error_kind_for(status) == kind, status


def test_reference_payload_omits_an_unset_temperature() -> None:
    """``None`` leaves sampling to the Provider (same rule as the gateway)."""

    adapter = ReferenceChatAdapter(reference_adapter_spec())
    unset = adapter.normalize_request(
        "reference-chat",
        ModelChatRequest(
            model="reference-chat",
            messages=[{"role": "user", "content": "h"}],
            temperature=None,
        ),
    )
    assert "temperature" not in unset
    set_explicitly = adapter.normalize_request(
        "reference-chat",
        ModelChatRequest(
            model="reference-chat",
            messages=[{"role": "user", "content": "h"}],
            temperature=0.2,
        ),
    )
    assert set_explicitly["temperature"] == 0.2


async def test_reference_model_declares_the_adapters_tools_and_structured_output() -> None:
    """Resolution enforces model-level flags, so the reference model must
    restate the adapter's declaration or refuse the requests it supports."""

    spec = reference_adapter_spec()
    assert spec.models[0].capabilities.tools is True
    assert spec.models[0].capabilities.structured_output is True

    catalog, store = await _catalog_with(ReferenceChatAdapter(spec))
    resolver = resolve_model_chat_provider(store, CostAwareRouter(store), adapters=catalog)
    resolved = await resolver(
        _binding(
            provider_name="reference-chat",
            config={"adapter_id": "maistro.reference"},
        )
    )
    assert isinstance(resolved, AdapterGatewayProvider)
    assert resolved.capabilities.tools is True
    assert resolved.capabilities.structured_output is True


async def test_bootstrap_registers_the_reference_adapter_at_the_deployment_url() -> None:
    """The reference adapter honors ``AgentConfig.litellm_url`` like the
    shipped gateway path, instead of always dialing the Compose hostname."""

    catalog = ProviderAdapterCatalog()
    store = InMemoryProviderRegistry()
    effects = new_in_memory_effect_context(policy_evaluator=binding_scope_policy)
    shim = _ConfigShim([_adapter_config(adapter_id="maistro.reference", binding_id="binding-ref")])
    shim.litellm_url = "http://gateway.internal:8080"
    await bootstrap_provider_adapters(shim, effects, store, catalog)

    registered = catalog.registered("maistro.reference")
    assert registered is not None
    assert registered.spec.base_url == "http://gateway.internal:8080"


async def test_boot_probe_covers_only_the_configured_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``probe_health_at_boot`` on one entry probes that adapter only."""

    probed: list[str] = []

    async def tracking(adapter: Any) -> bool:
        probed.append(adapter.spec.adapter_id)
        return True

    monkeypatch.setattr("maistro.capabilities.providers.llm_gateway.probe_adapter_health", tracking)
    catalog, store = await _catalog_with(AcmeAdapter(_spec(health_path="/healthz")))
    await register_adapter_models(
        catalog,
        store,
        AcmeAdapter(
            _spec(
                adapter_id="beta.models",
                credential_provider="beta",
                credential_ref="beta-primary",
                health_path="/healthz",
                models=(
                    {
                        "name": "beta-mini",
                        "cost_per_1k_input": 0.1,
                        "cost_per_1k_output": 0.4,
                        "latency_p50_ms": 150,
                        "tier": "fast",
                    },
                ),
            )
        ),
    )
    effects = new_in_memory_effect_context(policy_evaluator=binding_scope_policy)
    await bootstrap_provider_adapters(
        _ConfigShim([_adapter_config(probe_health_at_boot=True)]), effects, store, catalog
    )
    assert probed == ["acme.models"]  # beta.models was never asked for a probe


async def test_probe_adapter_for_an_unknown_id_reads_healthy() -> None:
    catalog = ProviderAdapterCatalog()
    assert await catalog.probe_adapter("nobody.models") is True
    assert catalog.is_healthy("nobody.models") is True


async def test_bootstrap_scopes_the_binding_to_the_declared_node_and_policies() -> None:
    """``node_id``/``policy_refs`` mirror ModelBindingConfig: an adapter
    credential can be scoped to one node with operator-chosen policies."""

    catalog, store = await _catalog_with(AcmeAdapter(_spec()))
    effects = new_in_memory_effect_context(policy_evaluator=binding_scope_policy)
    loaded = await bootstrap_provider_adapters(
        _ConfigShim([_adapter_config(node_id="summarize", policy_refs=("policy/egress-default",))]),
        effects,
        store,
        catalog,
    )
    assert loaded[0].node_id == "summarize"
    assert loaded[0].policy_refs == ("policy/egress-default",)


def test_adapter_config_refuses_a_blank_policy_reference() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="adapter wiring refs cannot contain empty"):
        _adapter_config(policy_refs=("policy/ok", "  "))


@pytest.mark.ac("SPEC-284/AC-4")
async def test_bootstrap_allows_the_configured_adapter_origin() -> None:
    """The operator-named endpoint joins the outbound policy's origins.

    Without this, a private (RFC1918/loopback/in-cluster) adapter origin is
    refused by the SSRF guard on every call while the equally private
    ``litellm_url`` sails through.
    """

    from maistro.security.outbound import current_outbound_policy

    # A distinct origin so the before-assert cannot depend on test order:
    # bootstrap is not the only test that seeds the process-global policy.
    catalog, store = await _catalog_with(
        AcmeAdapter(_spec(base_url="https://private.acme.internal"))
    )
    effects = new_in_memory_effect_context(policy_evaluator=binding_scope_policy)
    before = current_outbound_policy()
    assert not before.allows("https://private.acme.internal/chat/completions")
    await bootstrap_provider_adapters(_ConfigShim([_adapter_config()]), effects, store, catalog)
    assert current_outbound_policy().allows("https://private.acme.internal/chat/completions")


async def test_pre_effect_normalization_refusal_records_not_applied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A normalizer refusing a runtime input has caused no external effect,
    so the refusal must read as not-applied (safe to reconcile and retry),
    never UNKNOWN."""

    from maistro.capabilities.invocation import EffectNotApplied

    class Refusing(AcmeAdapter):
        def normalize_request(self, model: str, request: Any) -> dict[str, object]:
            # Conformance's probe message passes; this particular runtime
            # input is the one the adapter refuses.
            if any("refuse-me" in str(message.get("content", "")) for message in request.messages):
                raise ValueError("unsupported input shape")
            return super().normalize_request(model, request)

    captured = _CapturedGateway(_acme_response())
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: captured.client())
    catalog, store = await _catalog_with(Refusing(_spec()))
    effects = _effects()

    with pytest.raises(EffectNotApplied, match="before any HTTP"):
        await _egress(effects, catalog, store).complete(
            binding=_binding(),
            run_id="r2",
            node_run_id="nr2",
            attempt_id="a2",
            effect_key="test:acme-refused",
            request=ModelChatRequest(
                model="acme-mini", messages=[{"role": "user", "content": "refuse-me"}]
            ),
        )
    assert captured.requests == []  # nothing crossed the transport


async def test_create_container_accepts_a_host_registered_adapter_catalog() -> None:
    """The production composition root accepts an out-of-tree catalog.

    A host that registered third-party adapters on its own catalog hands it
    to ``create_container``; a configured entry against that id resolves
    instead of failing with an empty-catalog ConfigError.
    """

    from maistro.container import create_container
    from maistro.types.config import AgentConfig

    catalog = ProviderAdapterCatalog()
    await register_adapter_models(catalog, InMemoryProviderRegistry(), AcmeAdapter(_spec()))
    config = AgentConfig(
        router_api_key="test-key",
        provider_adapters=[_adapter_config().model_dump()],
    )
    container = await create_container(config, provider_adapter_catalog=catalog)
    try:
        resolved = await container.capability_effects.bindings.resolve(
            "binding-acme",
            workspace_id="ws1",
            project_id="p1",
            node_id="summarize",
            capability=MODEL_CHAT_CAPABILITY,
        )
        assert resolved.provider_name == ""
        assert resolved.config == {"adapter_id": "acme.models"}
    finally:
        await container.aclose()
        reset_default_adapter_catalog()
