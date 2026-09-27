"""Provider-scoped LLM circuit breakers (#1203).

A failure on provider A must not open the breaker for provider B. Models that
share a provider share one breaker. The shared gateway breaker opens only for
connectivity failures and is the higher-level domain that may block everyone.
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest

from maistro.agents.circuit_breaker import (
    SHARED_GATEWAY_DOMAIN,
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
    LlmCircuitPool,
    failure_domain,
    llm_breakers,
    llm_circuit,
    llm_health_detail,
)
from maistro.agents.conductor import ConductorCall, _run_with_retry
from maistro.agents.types import LLMProviderError
from maistro.capabilities.binding import Binding
from maistro.capabilities.model_chat import resolve_model_chat_provider
from maistro.capabilities.providers.llm_gateway import MODEL_CHAT_CAPABILITY, LlmGatewayProvider
from maistro.capabilities.types import Unavailable
from maistro.config.models import DEFAULT_TIERS, Tier
from maistro.config.settings import Settings
from maistro.observability.metrics import maistro_circuit_state
from maistro.providers import (
    CostAwareRouter,
    EmbeddingModelMetadata,
    InMemoryProviderRegistry,
    ModelMetadata,
    NoEligibleModelError,
    RouterBudget,
    RoutingTask,
)
from maistro.router.selector import RouterEngine
from maistro.types.config import RoutingConfig
from maistro.types.errors import NoModelsError
from maistro.types.intent import Intent
from maistro.types.model import ModelConfig, ProviderConfig

ANTHROPIC = ModelMetadata(
    name="claude-x",
    provider="anthropic",
    cost_per_1k_input=0.1,
    cost_per_1k_output=0.1,
    latency_p50_ms=100,
    fallback_to=("gpt-y",),
)
OPENAI = ModelMetadata(
    name="gpt-y",
    provider="openai",
    cost_per_1k_input=0.2,
    cost_per_1k_output=0.2,
    latency_p50_ms=500,
)
ADA = EmbeddingModelMetadata(
    name="text-embedding-ada-002",
    provider="openai",
    dimension=1536,
    cost_per_1k_tokens=0.0001,
    max_input_tokens=8192,
)
LOCAL_EMBED = EmbeddingModelMetadata(
    name="local-minilm",
    provider="local",
    dimension=384,
    cost_per_1k_tokens=0.0,
    max_input_tokens=512,
)


@pytest.fixture(autouse=True)
def _isolate_breakers() -> Iterator[None]:
    threshold = llm_circuit.failure_threshold
    recovery = llm_circuit.recovery_timeout
    try:
        yield
    finally:
        llm_circuit.failure_threshold = threshold
        llm_circuit.recovery_timeout = recovery
        llm_breakers.reset()


def _open(provider: str) -> None:
    breaker = llm_breakers.breaker(failure_domain(provider=provider))
    breaker.failure_threshold = 1
    breaker.record_failure()
    assert breaker.state == CircuitState.OPEN


def _binding(*, provider_name: str = "") -> Binding:
    return Binding(
        workspace_id="ws",
        project_id="pj",
        capability=MODEL_CHAT_CAPABILITY,
        provider_name=provider_name,
    )


def test_models_that_share_a_provider_share_one_breaker() -> None:
    gpt4 = failure_domain(model="openai/gpt-4")
    gpt4o = failure_domain(model="openai/gpt-4o")
    claude = failure_domain(model="anthropic/claude-3")
    assert gpt4 == gpt4o == "provider:openai"
    assert claude == "provider:anthropic"
    assert llm_breakers.breaker(gpt4) is llm_breakers.breaker(gpt4o)
    assert llm_breakers.breaker(gpt4) is not llm_breakers.breaker(claude)
    # A bare alias is not its own physical domain.
    assert failure_domain(model="gpt-4") == SHARED_GATEWAY_DOMAIN


def test_failure_domain_does_not_keep_credentials() -> None:
    assert failure_domain(provider="https://user:hunter2@gw.example/v1") == SHARED_GATEWAY_DOMAIN
    domain = failure_domain(model="openai/gpt-4?api_key=supersecret")
    assert domain == "provider:openai"
    assert "supersecret" not in domain
    assert "hunter2" not in domain


def test_provider_failure_does_not_open_another_provider() -> None:
    _open("openai")
    assert llm_breakers.is_open(failure_domain(provider="openai"))
    assert not llm_breakers.is_open(failure_domain(provider="anthropic"))
    assert llm_circuit.state == CircuitState.CLOSED
    anthropic = llm_breakers.breaker(failure_domain(provider="anthropic"))
    assert anthropic.allow_request() is True


def test_health_and_metrics_name_the_open_domain_without_secrets() -> None:
    domain = failure_domain(model="openai/gpt-4?api_key=supersecret")
    _open("openai")
    state, detail = llm_health_detail()
    assert state == "closed"
    assert "provider:openai=open" in detail
    assert "supersecret" not in detail
    assert "api_key" not in detail

    labels = [
        sample["labels"].get("dependency", "")
        for sample in maistro_circuit_state.collect()
        if sample["labels"].get("dependency") == domain
    ]
    assert labels == ["provider:openai"]
    rendered = repr(maistro_circuit_state.collect())
    assert "supersecret" not in rendered
    assert "hunter2" not in rendered


def test_router_engine_skips_open_provider_without_dropping_quota_errors() -> None:
    """The quota-aware engine must fall back, but not past an open breaker."""

    class _Tracker:
        pass

    engine = RouterEngine(_Tracker())  # type: ignore[arg-type]
    models = {
        "claude": ModelConfig(provider="anthropic", tier="small", quality=0.99),
        "gpt": ModelConfig(provider="openai", tier="small", quality=0.4),
    }
    providers = {
        "anthropic": ProviderConfig(status="active", free_tokens=1_000_000),
        "openai": ProviderConfig(status="active", free_tokens=1_000_000),
    }
    intent = Intent(tier="P2")
    config = RoutingConfig()
    _open("anthropic")

    selected = engine.select_with_usage(intent, models, providers, config, {})
    assert selected.model_id == "gpt"
    assert selected.provider == "openai"

    llm_circuit.failure_threshold = 1
    llm_circuit.record_failure()
    with pytest.raises(NoModelsError, match="circuit"):
        engine.select_with_usage(intent, models, providers, config, {})


async def test_router_falls_back_to_the_healthy_provider() -> None:
    registry = InMemoryProviderRegistry(models=[ANTHROPIC, OPENAI])
    router = CostAwareRouter(registry)
    _open("anthropic")

    selected = await router.select(RoutingTask())
    assert selected.name == "gpt-y"
    assert selected.provider == "openai"


async def test_router_still_honors_budget_when_the_alternative_is_too_expensive() -> None:
    registry = InMemoryProviderRegistry(models=[ANTHROPIC, OPENAI])
    router = CostAwareRouter(registry)
    _open("anthropic")

    with pytest.raises(NoEligibleModelError):
        await router.select(RoutingTask(), RouterBudget(max_cost_cents=0.15))


async def test_pinned_binding_does_not_fall_back_when_its_provider_is_open() -> None:
    registry = InMemoryProviderRegistry(models=[ANTHROPIC, OPENAI])
    resolve = resolve_model_chat_provider(registry, CostAwareRouter(registry))
    _open("anthropic")

    pinned = await resolve(_binding(provider_name="claude-x"))
    assert isinstance(pinned, Unavailable)
    assert "does not fall back" in pinned.reason

    unpinned = await resolve(_binding())
    assert isinstance(unpinned, LlmGatewayProvider)
    assert unpinned.name == "gpt-y"


async def test_embedding_selection_skips_an_open_provider() -> None:
    registry = InMemoryProviderRegistry(embedding_models=[ADA, LOCAL_EMBED])
    router = CostAwareRouter(registry)
    _open("local")

    selected = await router.select_embedding(100)
    assert selected.provider == "openai"


async def test_shared_gateway_failure_blocks_without_opening_provider_breakers() -> None:
    llm_circuit.failure_threshold = 1
    llm_circuit.record_failure()
    assert llm_circuit.state == CircuitState.OPEN
    assert not llm_breakers.is_open(failure_domain(provider="openai"))
    assert not llm_breakers.is_open(failure_domain(provider="anthropic"))

    registry = InMemoryProviderRegistry(models=[ANTHROPIC, OPENAI])
    router = CostAwareRouter(registry)
    with pytest.raises(NoEligibleModelError):
        await router.select(RoutingTask())

    state, detail = llm_health_detail()
    assert state == "open"
    assert detail.startswith("circuit=open")


def test_half_open_probe_is_per_failure_domain() -> None:
    gateway = CircuitBreaker(name="gw", failure_threshold=1, recovery_timeout=60)
    pool = LlmCircuitPool(
        gateway,
        max_domains=4,
        failure_threshold=1,
        recovery_timeout=60,
    )
    provider_a = pool.breaker("provider:a")
    provider_b = pool.breaker("provider:b")
    provider_a.record_failure()
    provider_a.recovery_timeout = 0
    assert provider_a.allow_request() is True
    assert provider_a.state == CircuitState.HALF_OPEN
    assert provider_a.allow_request() is False
    assert provider_b.allow_request() is True
    assert provider_b.state == CircuitState.CLOSED
    assert gateway.state == CircuitState.CLOSED


def test_pool_bounds_cardinality_and_retires_idle_closed_domains() -> None:
    clock = {"t": 0.0}
    gateway = CircuitBreaker(name="gw", failure_threshold=5, recovery_timeout=60)
    pool = LlmCircuitPool(
        gateway,
        max_domains=2,
        failure_threshold=5,
        recovery_timeout=60,
        idle_after_s=10,
        clock=lambda: clock["t"],
    )
    pool.breaker("provider:a")
    pool.breaker("provider:b")
    pool.breaker("provider:c")
    assert pool.domains() == ("provider:b", "provider:c")

    clock["t"] = 11
    pool.breaker("provider:d")
    assert pool.domains() == ("provider:d",)

    saturated = LlmCircuitPool(
        CircuitBreaker(name="gw2", failure_threshold=1, recovery_timeout=60),
        max_domains=1,
        failure_threshold=1,
        recovery_timeout=60,
    )
    open_domain = saturated.breaker("provider:open")
    open_domain.record_failure()
    assert open_domain.state == CircuitState.OPEN
    saturated.breaker("provider:newer")
    assert saturated.domains() == ("provider:newer",)
    assert saturated.is_open("provider:open") is False


def test_max_domains_comes_from_settings() -> None:
    assert Settings().circuit_breaker_max_domains >= 2
    pool = LlmCircuitPool.from_settings(Settings(circuit_breaker_max_domains=4))
    assert pool.max_domains == 4


def _call(model: str) -> ConductorCall:
    return ConductorCall(model=model, base_url="http://gw", api_key="key", system_prompt="sys")


def _tier() -> object:
    return DEFAULT_TIERS[Tier.STANDARD].model_copy(update={"max_llm_retries": 1, "initial_backoff": 0})


async def _no_sleep(_delay: float) -> None:
    return None


async def test_conductor_http_failure_opens_only_that_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    openai = llm_breakers.breaker(failure_domain(model="openai/gpt-4"))
    openai.failure_threshold = 1
    calls = {"n": 0}

    async def fail_openai(*_args: object, **_kwargs: object) -> str:
        calls["n"] += 1
        request = httpx.Request("POST", "http://gw/chat/completions")
        response = httpx.Response(503, request=request)
        raise httpx.HTTPStatusError("upstream", request=request, response=response)

    monkeypatch.setattr("maistro.agents.conductor._call_gateway", fail_openai)
    monkeypatch.setattr("maistro.agents.conductor.asyncio.sleep", _no_sleep)

    with pytest.raises(LLMProviderError):
        await _run_with_retry(_call("openai/gpt-4"), "prompt", _tier(), max_tokens=16)

    assert openai.state == CircuitState.OPEN
    assert llm_circuit.state == CircuitState.CLOSED
    assert not llm_breakers.is_open(failure_domain(model="anthropic/claude"))

    async def healthy(*_args: object, **_kwargs: object) -> str:
        calls["n"] += 1
        return '{"success": true}'

    monkeypatch.setattr("maistro.agents.conductor._call_gateway", healthy)
    result = await _run_with_retry(_call("anthropic/claude"), "prompt", _tier(), max_tokens=16)
    assert result.success is True

    with pytest.raises(CircuitOpenError, match="provider:openai"):
        await _run_with_retry(_call("openai/gpt-4o"), "prompt", _tier(), max_tokens=16)
    # Same provider, rejected before another gateway call.
    assert calls["n"] == 2


async def test_conductor_connect_error_opens_the_shared_gateway_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm_circuit.failure_threshold = 1
    anthropic = llm_breakers.breaker(failure_domain(model="anthropic/claude"))

    async def down(*_args: object, **_kwargs: object) -> str:
        raise httpx.ConnectError("gateway down")

    monkeypatch.setattr("maistro.agents.conductor._call_gateway", down)
    monkeypatch.setattr("maistro.agents.conductor.asyncio.sleep", _no_sleep)

    with pytest.raises(LLMProviderError):
        await _run_with_retry(_call("anthropic/claude"), "prompt", _tier(), max_tokens=16)

    assert llm_circuit.state == CircuitState.OPEN
    assert anthropic.state == CircuitState.CLOSED

    async def should_not_run(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("healthy provider must not be called while the gateway is open")

    monkeypatch.setattr("maistro.agents.conductor._call_gateway", should_not_run)
    with pytest.raises(CircuitOpenError, match="llm_provider"):
        await _run_with_retry(_call("openai/gpt-4"), "prompt", _tier(), max_tokens=16)
