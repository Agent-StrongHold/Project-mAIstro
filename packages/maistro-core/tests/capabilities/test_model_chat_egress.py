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
    CapabilityUnavailable,
    InvocationStatus,
    UnsafeEffectRetry,
)
from maistro.capabilities.model_chat import (
    MODEL_CHAT_CAPABILITY,
    ModelChatEgress,
    ModelChatRequest,
    _gateway_usage,
    resolve_model_chat_provider,
)
from maistro.capabilities.providers.llm_gateway import GatewayEndpoint, LlmGatewayProvider
from maistro.capabilities.types import Unavailable
from maistro.providers.errors import NoEligibleModelError
from maistro.providers.registry import InMemoryProviderRegistry
from maistro.providers.router import CostAwareRouter
from maistro.providers.types import (
    ModelMetadata,
    RouterBudget,
    RoutingTask,
)
from maistro.quota.tracker import InMemoryQuotaTracker
from maistro.quota.usage_log import InMemoryUsageLog


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


async def test_canonical_invocation_completion_records_quota_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live Invocation hook records provider usage and deduplicates effects."""
    tracker = InMemoryQuotaTracker()
    effects = new_in_memory_effect_context(usage_log=InMemoryUsageLog(), quota_tracker=tracker)
    registry = _registry()
    _patch_gateway(monkeypatch, _OK_BODY)
    egress = ModelChatEgress(
        effects,
        registry=registry,
        router=CostAwareRouter(registry),
        endpoint=GatewayEndpoint(base_url="http://gw"),
    )
    kwargs: dict[str, Any] = {
        "binding": _binding(),
        "run_id": "r-quota",
        "node_run_id": "nr-quota",
        "attempt_id": "a-quota",
        "effect_key": "quota:dedupe",
        "request": ModelChatRequest(model="fast-model", messages=[]),
    }

    first = await egress.complete(**kwargs)
    second = await egress.complete(**kwargs)

    events = effects.usage_log.events_for("fast-model")
    assert len(events) == 1
    assert events[0].invocation_id == first.invocation_id
    assert events[0].usage_reported is True
    assert second.invocation_id == first.invocation_id
    quota_rows = await tracker.get_all_usage()
    assert quota_rows[0]["provider"] == "fast-model"
    assert quota_rows[0]["total_tokens"] == 120
    rows = await effects.invocation_store.list_effect(
        run_id="r-quota",
        node_run_id="nr-quota",
        binding_id=kwargs["binding"].binding_id,
        effect_key="quota:dedupe",
    )
    assert len(rows) == 1
    assert rows[0].usage is not None


async def test_canonical_invocation_missing_usage_is_explicitly_unreported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = InMemoryQuotaTracker()
    effects = new_in_memory_effect_context(usage_log=InMemoryUsageLog(), quota_tracker=tracker)
    _patch_gateway(monkeypatch, {"choices": [{"message": {"content": "ok"}}]})
    egress = ModelChatEgress(
        effects,
        registry=_registry(),
        router=CostAwareRouter(_registry()),
        endpoint=GatewayEndpoint(base_url="http://gw"),
    )

    result = await egress.complete(
        binding=_binding(),
        run_id="r-missing",
        node_run_id="nr-missing",
        attempt_id="a-missing",
        effect_key="quota:missing",
        request=ModelChatRequest(model="fast-model", messages=[]),
    )

    event = effects.usage_log.events_for("fast-model")[0]
    assert result.usage is None
    assert event.usage_reported is False
    assert event.input_tokens == event.output_tokens == 0
    row = (await tracker.get_all_usage())[0]
    assert row["unreported_count"] == 1
    assert row["total_tokens"] == 0


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


# --- diff-coverage branch closers (model_chat.py arcs 56, 161, 169) --------


def test_gateway_usage_requires_dict_body() -> None:
    """Arc 56 both ways: non-dict bodies carry no usage; dict bodies do."""

    provider = LlmGatewayProvider(_meta("fast-model"), model="fast-model")

    # Arc 56 True: a non-object gateway body has no usage to extract.
    assert _gateway_usage(provider, ["not", "a", "dict"]) is None
    assert _gateway_usage(provider, None) is None

    # Arc 56 False: the dict body keeps mapping usage/cost metadata.
    usage = _gateway_usage(provider, _OK_BODY)
    assert usage is not None
    assert usage.input_units == 100
    assert usage.output_units == 20


async def test_unavailable_selection_refuses_before_any_gateway_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Arc 161 False: an Unavailable resolver result is returned untracked.

    ``tracked_resolve`` only records ``LlmGatewayProvider`` handles (arc 161
    True, covered by every successful egress call above). An unavailable pin
    crosses the seam as ``Unavailable`` and ``invoke`` refuses it with
    ``CapabilityUnavailable`` before any HTTP is attempted.
    """

    effects = new_in_memory_effect_context()
    registry = _registry()
    registry.mark_unavailable("fast-model")
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

    with pytest.raises(CapabilityUnavailable):
        await egress.complete(
            binding=_binding(provider_name="fast-model"),
            run_id="r1",
            node_run_id="nr1",
            attempt_id="a1",
            effect_key="test:unavailable",
            request=ModelChatRequest(messages=[{"role": "user", "content": "hi"}]),
        )

    assert calls == []  # refusal happened at resolution, not over HTTP


async def test_usage_from_without_tracked_provider_returns_none() -> None:
    """Arc 169 both ways: unselected usage is absent, selected usage maps."""

    from types import SimpleNamespace

    captured: dict[str, Any] = {}

    class _StubInvocations:
        async def invoke(
            self,
            *,
            resolver: Any,
            executor: Any,
            usage_from: Any,
            **kwargs: Any,
        ) -> Any:
            captured["resolver"] = resolver
            captured["usage_from"] = usage_from
            # Arc 169 True: nothing was resolved/tracked yet (a dedupe-shaped
            # consumer), so usage extraction yields None instead of crashing.
            assert usage_from(_OK_BODY) is None
            return SimpleNamespace(
                invocation_id="inv-stub",
                binding=SimpleNamespace(provider_name="fast-model"),
                result={"model": "fast-model"},
                usage=None,
            )

    class _StubEffects:
        invocations = _StubInvocations()

    registry = _registry()
    egress = ModelChatEgress(
        _StubEffects(),  # type: ignore[arg-type]
        registry=registry,
        router=CostAwareRouter(registry),
        endpoint=GatewayEndpoint(base_url="http://gw"),
    )

    result = await egress.complete(
        binding=_binding(),
        run_id="r1",
        node_run_id="nr1",
        attempt_id="a1",
        effect_key="test:stub-seam",
        request=ModelChatRequest(messages=[{"role": "user", "content": "hi"}]),
    )
    assert result.usage is None
    assert result.body == {"model": "fast-model"}

    # Arc 161 True + arc 169 False: once the tracked resolver records a
    # gateway provider, the same usage_from maps the body via _gateway_usage.
    provider = await captured["resolver"](_binding())
    assert isinstance(provider, LlmGatewayProvider)
    usage = captured["usage_from"](_OK_BODY)
    assert usage is not None
    assert usage.input_units == 100
    assert usage.provider == "test-gw"


async def test_setup_hook_runs_after_authorization_before_model_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider-internal setup executes inside the Invocation (#1088).

    Ordering proof: policy authorization -> setup -> gateway HTTP. The setup
    hook lets a Provider perform its own credential-bearing preparation
    without turning that preparation into pre-authorization HTTP.
    """

    order: list[str] = []
    effects = new_in_memory_effect_context()
    registry = _registry()

    async def _setup() -> None:
        order.append("setup")

    class _Resp:
        status_code = 200

        def json(self) -> Any:
            return _OK_BODY

    class _Client:
        def __init__(self, *a: Any, **kw: Any) -> None: ...

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *a: Any) -> None: ...

        async def post(self, *a: Any, **kw: Any) -> _Resp:
            order.append("http")
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

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
        effect_key="test:setup",
        request=ModelChatRequest(messages=[{"role": "user", "content": "hi"}]),
        setup=_setup,
    )

    assert result.model == "fast-model"
    assert order == ["setup", "http"]
    stored = await effects.invocation_store.get(result.invocation_id)
    assert stored is not None
    assert stored.status is InvocationStatus.COMPLETED


async def test_denied_policy_refuses_before_setup_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Authorization refusal means zero setup and zero HTTP (#1088)."""

    from maistro.capabilities.governed_invocation import InvocationDenied
    from maistro.policy.types import Decision, PolicyVerdict

    async def _deny(*args: Any, **kwargs: Any) -> PolicyVerdict:
        del args, kwargs
        return PolicyVerdict(Decision.DENY, reason="denied", rule="test")

    setup_ran = False
    effects = new_in_memory_effect_context(policy_evaluator=_deny)
    registry = _registry()
    _patch_gateway(monkeypatch, _OK_BODY)
    egress = ModelChatEgress(
        effects,
        registry=registry,
        router=CostAwareRouter(registry),
        endpoint=GatewayEndpoint(base_url="http://gw:4000"),
    )

    async def _setup() -> None:
        nonlocal setup_ran
        setup_ran = True

    with pytest.raises(InvocationDenied):
        await egress.complete(
            binding=_binding(),
            run_id="r1",
            node_run_id="nr1",
            attempt_id="a1",
            effect_key="test:setup-denied",
            request=ModelChatRequest(messages=[{"role": "user", "content": "hi"}]),
            setup=_setup,
        )

    assert setup_ran is False


# --- provider registration seam + structured-output payload (#1088) ---------


async def test_register_provider_models_posts_each_model_and_strips_v1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Registration goes through the gateway admin seam per model, stripping a
    trailing ``/v1`` from the endpoint and carrying the transient key only in
    the litellm_params body plus the endpoint's authorization header."""
    from maistro.capabilities.providers.llm_gateway import register_provider_models

    calls: list[tuple[str, dict[str, str], dict[str, Any]]] = []

    class _Resp:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {"status": "ok"}

    class _Client:
        def __init__(self, *a: Any, **kw: Any) -> None: ...

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *a: Any) -> None: ...

        async def post(self, url: str, *, headers: Any = None, json: Any = None) -> _Resp:
            calls.append((url, dict(headers or {}), dict(json or {})))
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    await register_provider_models(
        GatewayEndpoint(base_url="http://gw:4000/v1/", api_key="master"),
        models=("model-a", "model-b"),
        api_key="transient-key",
    )

    assert [url for url, _h, _b in calls] == [
        "http://gw:4000/model/new",
        "http://gw:4000/model/new",
    ]
    assert calls[0][2] == {
        "model_name": "model-a",
        "litellm_params": {"model": "model-a", "api_key": "transient-key"},
    }
    assert calls[0][1]["Authorization"] == "Bearer master"


async def test_register_provider_models_maps_http_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A gateway rejection (>=400) becomes a ProviderRegistrationError naming
    the model and status."""
    from maistro.capabilities.providers.llm_gateway import (
        ProviderRegistrationError,
        register_provider_models,
    )

    class _Resp:
        status_code = 403

        def json(self) -> dict[str, Any]:
            return {"error": "invalid admin key"}

    class _Client:
        def __init__(self, *a: Any, **kw: Any) -> None: ...

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *a: Any) -> None: ...

        async def post(self, *a: Any, **kw: Any) -> _Resp:
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    with pytest.raises(ProviderRegistrationError, match=r"model-a.*HTTP 403"):
        await register_provider_models(
            GatewayEndpoint(base_url="http://gw:4000", api_key="master"),
            models=("model-a",),
            api_key="k",
        )


async def test_register_provider_models_wraps_transport_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreachable gateway (transport error) is a registration failure, not
    a crash or an authorization verdict."""
    from maistro.capabilities.providers.llm_gateway import (
        ProviderRegistrationError,
        register_provider_models,
    )

    class _Client:
        def __init__(self, *a: Any, **kw: Any) -> None: ...

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *a: Any) -> None: ...

        async def post(self, *a: Any, **kw: Any) -> Any:
            raise httpx.ConnectError("no route to gateway")

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    with pytest.raises(ProviderRegistrationError, match="gateway unreachable"):
        await register_provider_models(
            GatewayEndpoint(base_url="http://gw:4000", api_key="master"),
            models=("model-a",),
            api_key="k",
        )


async def test_chat_payload_carries_structured_output_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A governed request's ``response_format`` passes through to the gateway
    body; when absent, the key is absent (no implicit schema)."""

    captured: dict[str, Any] = {}

    class _Resp:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return _OK_BODY

    class _Client:
        is_closed = False

        def __init__(self, *a: Any, **kw: Any) -> None: ...

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *a: Any) -> None: ...

        async def post(self, *a: Any, **kw: Any) -> _Resp:
            captured["json"] = kw.get("json")
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    effects = new_in_memory_effect_context()
    registry = _registry()
    egress = ModelChatEgress(
        effects,
        registry=registry,
        router=CostAwareRouter(registry),
        endpoint=GatewayEndpoint(base_url="http://gw"),
    )
    response_format = {
        "type": "json_schema",
        "json_schema": {"name": "score", "schema": {"type": "object"}},
    }

    structured = await egress.complete(
        binding=_binding(),
        run_id="r1",
        node_run_id="nr1",
        attempt_id="a1",
        effect_key="test:structured",
        request=ModelChatRequest(
            messages=[{"role": "user", "content": "hi"}],
            response_format=response_format,
        ),
    )
    assert structured.model == "fast-model"
    assert captured["json"]["response_format"] == response_format

    captured.clear()
    await egress.complete(
        binding=_binding(),
        run_id="r1",
        node_run_id="nr1",
        attempt_id="a2",
        effect_key="test:unstructured",
        request=ModelChatRequest(messages=[{"role": "user", "content": "hi"}]),
    )
    assert "response_format" not in captured["json"]
