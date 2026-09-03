"""Focused tests for the one governed model egress (#56).

Covers the acceptance shape of the M1-D2 boundary:
- governed model calls create canonical Invocation records;
- model/version/token/cost/provider metadata is attached to the Invocation;
- Binding pins and cost-aware router/fallback selection keep parity inside
  the boundary (ADR-079 policy is preserved, not replaced);
- a pinned-but-unavailable selection refuses instead of falling back
  (fallback cannot widen authorization);
- completed effects deduplicate, and unreachable gateways fail retryably.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from maistro.capabilities.binding import Binding
from maistro.capabilities.effect_context import new_in_memory_effect_context
from maistro.capabilities.invocation import (
    InvocationStatus,
    UnsafeEffectRetry,
)
from maistro.capabilities.model_chat import (
    MODEL_CHAT_CAPABILITY,
    ModelChatEgress,
    ModelChatRequest,
    resolve_model_chat_provider,
)
from maistro.capabilities.providers.llm_gateway import GatewayEndpoint
from maistro.capabilities.types import Unavailable
from maistro.providers.errors import NoEligibleModelError
from maistro.providers.registry import InMemoryProviderRegistry
from maistro.providers.router import CostAwareRouter
from maistro.providers.types import (
    ModelMetadata,
    RouterBudget,
    RoutingTask,
)


def _meta(
    name: str, *, latency: int = 100, cost_in: float = 0.5, provider: str = "test-gw"
) -> ModelMetadata:
    return ModelMetadata(
        name=name,
        provider=provider,
        cost_per_1k_input=cost_in,
        cost_per_1k_output=1.0,
        latency_p50_ms=latency,
    )


def _registry() -> InMemoryProviderRegistry:
    return InMemoryProviderRegistry(
        models=[
            _meta("fast-model", latency=50),
            _meta("slow-model", latency=500, cost_in=0.1),
            _meta("fallback-model", latency=400),
        ]
    )


def _binding(provider_name: str = "") -> Binding:
    return Binding(
        workspace_id="ws1",
        project_id="p1",
        capability=MODEL_CHAT_CAPABILITY,
        provider_name=provider_name,
    )


_OK_BODY: dict[str, Any] = {
    "model": "fast-model-v3",
    "choices": [{"message": {"role": "assistant", "content": "hi"}}],
    "usage": {"prompt_tokens": 100, "completion_tokens": 20},
}


def _patch_gateway(monkeypatch: pytest.MonkeyPatch, body: Any = None, status: int = 200) -> None:
    class _Resp:
        status_code = status

        def json(self) -> Any:
            return body

    class _Client:
        def __init__(self, *a: Any, **kw: Any) -> None: ...

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *a: Any) -> None: ...

        async def post(self, *a: Any, **kw: Any) -> _Resp:
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)


async def test_governed_call_creates_invocation_with_usage_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    effects = new_in_memory_effect_context()
    registry = _registry()
    _patch_gateway(monkeypatch, _OK_BODY)
    egress = ModelChatEgress(
        effects,
        registry=registry,
        router=CostAwareRouter(registry),
        endpoint=GatewayEndpoint(base_url="http://gw:4000"),
    )

    result = await egress.complete(
        binding=_binding(),
        run_id="r1",
        node_run_id="nr1",
        attempt_id="a1",
        effect_key="test:model",
        request=ModelChatRequest(
            model="fast-model", messages=[{"role": "user", "content": "hello"}]
        ),
    )

    assert result.model == "fast-model"
    # 100 in @ 0.5c/1k + 20 out @ 1.0c/1k
    assert result.usage is not None
    assert result.usage.input_units == 100
    assert result.usage.output_units == 20
    assert result.usage.cost_cents == pytest.approx(0.05 + 0.02)
    assert result.usage.model == "fast-model"
    assert result.usage.model_version == "fast-model-v3"
    assert result.usage.provider == "test-gw"

    stored = await effects.invocation_store.get(result.invocation_id)
    assert stored is not None
    assert stored.status is InvocationStatus.COMPLETED
    assert stored.binding.capability == MODEL_CHAT_CAPABILITY
    assert stored.binding.provider_name == "fast-model"
    assert stored.usage == result.usage


async def test_unpinned_unaliased_request_uses_router_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No pin and no alias: the cost-aware router picks, with fallback parity."""

    registry = _registry()
    registry.mark_unavailable("fast-model")
    router = CostAwareRouter(registry)
    _patch_gateway(monkeypatch, _OK_BODY)
    effects = new_in_memory_effect_context()
    egress = ModelChatEgress(
        effects, registry=registry, router=router, endpoint=GatewayEndpoint(base_url="http://gw")
    )

    result = await egress.complete(
        binding=_binding(),
        run_id="r1",
        node_run_id="nr1",
        attempt_id="a1",
        effect_key="test:router",
        request=ModelChatRequest(messages=[{"role": "user", "content": "hi"}]),
    )

    # The router alone would skip the unavailable fast-model; the governed
    # resolver must select the same model (parity, not replacement).
    expected = await router.select(RoutingTask())
    assert result.model == expected.name
    assert result.model != "fast-model"


async def test_router_selection_matches_resolver_selection_exactly() -> None:
    """Direct router.select and the governed resolver agree, budget included."""

    registry = _registry()
    registry.mark_unavailable("slow-model")
    router = CostAwareRouter(registry)
    task = RoutingTask(task_type="model.chat")

    default_resolve = resolve_model_chat_provider(registry, router)
    provider = await default_resolve(_binding())
    expected = await router.select(task)
    assert not isinstance(provider, Unavailable)
    assert provider.name == expected.name

    # A budget the resolver is composed with constrains it identically.
    budget = RouterBudget(max_latency_ms=450)
    budgeted = resolve_model_chat_provider(registry, router, task=task, budget=budget)
    budgeted_provider = await budgeted(_binding())
    budgeted_expected = await router.select(task, budget)
    assert not isinstance(budgeted_provider, Unavailable)
    assert budgeted_provider.name == budgeted_expected.name


async def test_binding_pin_outranks_router_preference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    effects = new_in_memory_effect_context()
    registry = _registry()
    _patch_gateway(monkeypatch, _OK_BODY)
    egress = ModelChatEgress(
        effects,
        registry=registry,
        router=CostAwareRouter(registry),
        endpoint=GatewayEndpoint(base_url="http://gw"),
    )

    result = await egress.complete(
        binding=_binding(provider_name="slow-model"),
        run_id="r1",
        node_run_id="nr1",
        attempt_id="a1",
        effect_key="test:pin",
        request=ModelChatRequest(model="fast-model", messages=[{"role": "user", "content": "hi"}]),
    )

    assert result.model == "slow-model"


async def test_pinned_unavailable_model_refuses_without_fallback() -> None:
    registry = _registry()
    registry.mark_unavailable("fast-model")
    resolve = resolve_model_chat_provider(registry, CostAwareRouter(registry))

    provider = await resolve(_binding(provider_name="fast-model"))

    assert isinstance(provider, Unavailable)
    assert "does not fall back" in provider.reason


async def test_unregistered_alias_still_reaches_gateway_with_absent_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gateway aliases absent from the registry keep today's passthrough."""

    effects = new_in_memory_effect_context()
    registry = _registry()
    _patch_gateway(monkeypatch, _OK_BODY)
    egress = ModelChatEgress(
        effects,
        registry=registry,
        router=CostAwareRouter(registry),
        endpoint=GatewayEndpoint(base_url="http://gw"),
    )

    result = await egress.complete(
        binding=_binding(),
        run_id="r1",
        node_run_id="nr1",
        attempt_id="a1",
        effect_key="test:alias",
        request=ModelChatRequest(
            model="gemini-3.1-flash-lite", messages=[{"role": "user", "content": "hi"}]
        ),
    )

    assert result.model == "gemini-3.1-flash-lite"
    assert result.usage is not None
    assert result.usage.cost_cents is None  # unmeasured is absent, not zero
    assert result.usage.provider == "llm-gateway"


async def test_completed_effect_deduplicates_repeat_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    effects = new_in_memory_effect_context()
    registry = _registry()
    calls: list[str] = []

    class _Resp:
        status_code = 200

        def json(self) -> Any:
            return _OK_BODY

    class _Client:
        def __init__(self, *a: Any, **kw: Any) -> None: ...

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *a: Any) -> None: ...

        async def post(self, url: str, **kw: Any) -> _Resp:
            calls.append(url)
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    egress = ModelChatEgress(
        effects,
        registry=registry,
        router=CostAwareRouter(registry),
        endpoint=GatewayEndpoint(base_url="http://gw"),
    )
    kwargs: dict[str, Any] = dict(
        binding=_binding(),
        run_id="r1",
        node_run_id="nr1",
        attempt_id="a1",
        effect_key="test:dedupe",
        request=ModelChatRequest(messages=[{"role": "user", "content": "hi"}]),
    )
    kwargs: dict[str, Any] = {
        "binding": _binding(),
        "run_id": "r1",
        "node_run_id": "nr1",
        "attempt_id": "a1",
        "effect_key": "test:dedupe",
        "request": ModelChatRequest(messages=[{"role": "user", "content": "hi"}]),
    }

    first = await egress.complete(**kwargs)
    second = await egress.complete(**kwargs)

    assert len(calls) == 1
    assert second.invocation_id == first.invocation_id


async def test_unreachable_gateway_records_failed_retryable_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    effects = new_in_memory_effect_context()
    registry = _registry()

    class _Client:
        is_closed = False

        def __init__(self, *a: Any, **kw: Any) -> None: ...

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *a: Any) -> None: ...

        async def post(self, url: str, **kw: Any) -> Any:
            raise httpx.ConnectError("no route to gateway")

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    egress = ModelChatEgress(
        effects,
        registry=registry,
        router=CostAwareRouter(registry),
        endpoint=GatewayEndpoint(base_url="http://gw"),
    )
    kwargs: dict[str, Any] = dict(
        binding=_binding(),
        run_id="r1",
        node_run_id="nr1",
        attempt_id="a1",
        effect_key="test:unreachable",
        request=ModelChatRequest(messages=[{"role": "user", "content": "hi"}]),
    )
    kwargs: dict[str, Any] = {
        "binding": _binding(),
        "run_id": "r1",
        "node_run_id": "nr1",
        "attempt_id": "a1",
        "effect_key": "test:unreachable",
        "request": ModelChatRequest(messages=[{"role": "user", "content": "hi"}]),
    }

    from maistro.capabilities.invocation import EffectNotApplied

    with pytest.raises(EffectNotApplied):
        await egress.complete(**kwargs)

    history = await effects.invocation_store.list_effect(
        run_id="r1",
        node_run_id="nr1",
        binding_id=kwargs["binding"].binding_id,
        effect_key="test:unreachable",
    )
    assert len(history) == 1
    assert history[0].status is InvocationStatus.FAILED

    # A FAILED EffectNotApplied record is eligible for one retry, which then
    # succeeds -- recovery parity for the governed path. The pooled client
    # still holds the ConnectError fake, so drop the pool before re-patching.
    from maistro.http import set_test_transport

    set_test_transport(None)
    _patch_gateway(monkeypatch, _OK_BODY)
    retried = await ModelChatEgress(
        effects,
        registry=registry,
        router=CostAwareRouter(registry),
        endpoint=GatewayEndpoint(base_url="http://gw"),
    ).complete(**kwargs)
    assert retried.model == "fast-model"


async def test_unknown_outcome_blocks_repeat() -> None:
    """A 500 leaves the Invocation UNKNOWN; recovery must not repeat it."""

    effects = new_in_memory_effect_context()
    registry = _registry()
    resolve = resolve_model_chat_provider(registry, CostAwareRouter(registry))

    async def _execute(provider: Any, request: Any) -> Any:
        raise RuntimeError("llm_http_error status=500")

    binding = _binding()
    with pytest.raises(RuntimeError):
        await effects.invocations.invoke(
            binding=binding,
            run_id="r1",
            node_run_id="nr1",
            attempt_id="a2",
            effect_key="test:unknown",
            request=ModelChatRequest(messages=[]),
            resolver=resolve,
            executor=_execute,
        )

    with pytest.raises(UnsafeEffectRetry):
        await effects.invocations.invoke(
            binding=binding,
            run_id="r1",
            node_run_id="nr1",
            attempt_id="a3",
            effect_key="test:unknown",
            request=ModelChatRequest(messages=[]),
            resolver=resolve,
            executor=_execute,
        )


async def test_no_eligible_model_is_capability_unavailable() -> None:
    empty = InMemoryProviderRegistry()
    resolve = resolve_model_chat_provider(empty, CostAwareRouter(empty))

    provider = await resolve(_binding())

    assert isinstance(provider, Unavailable)
    with pytest.raises(NoEligibleModelError):
        await CostAwareRouter(empty).select(RoutingTask())
