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

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest

from maistro.capabilities.binding import Binding
from maistro.capabilities.credential_routing import CredentialBackedProvider, CredentialRouting
from maistro.capabilities.effect_context import (
    CapabilityEffectContext,
    binding_scope_policy,
    new_in_memory_effect_context,
)
from maistro.capabilities.invocation import (
    CapabilityUnavailable,
    InvocationStatus,
    UnsafeEffectRetry,
)
from maistro.capabilities.model_chat import (
    MODEL_CHAT_CAPABILITY,
    GovernedLLMClient,
    GovernedModelChatClient,
    ModelCallResult,
    ModelChatEgress,
    ModelChatRequest,
    _gateway_usage,
    _replay_result_chunks,
    build_model_chat_client,
    model_execution_context,
    resolve_model_chat_provider,
)
from maistro.capabilities.providers.llm_gateway import (
    DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
    MODEL_GATEWAY_CREDENTIAL_PROVIDER,
    GatewayEndpoint,
    LlmGatewayProvider,
)
from maistro.capabilities.types import Unavailable
from maistro.credentials.router import CredentialRouter
from maistro.credentials.types import CredentialRecord
from maistro.observability.correlation import (
    bind_execution_context,
    detached_execution_context,
)
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
from maistro.runs.store import RunIntegrityError


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
        credential_refs=(DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,),
    )


def _effects() -> CapabilityEffectContext:
    """An in-memory effect context with the gateway credential every
    ``_binding()`` authorizes already registered (#1091, Binding-scoped
    credential routing): without it every governed call in this file refuses
    with ``CredentialScopeError`` before reaching the gateway.

    It also opts into the explicit ``binding_scope_policy`` baseline: since
    #846 an omitted policy evaluator fails closed, so tests that exercise a
    governed call must name their policy instead of inheriting silence."""

    effects = new_in_memory_effect_context(policy_evaluator=binding_scope_policy)
    effects.credentials.add(
        workspace_id="ws1",
        project_id="p1",
        record=CredentialRecord(
            key_id=DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
            provider=MODEL_GATEWAY_CREDENTIAL_PROVIDER,
            api_key="test-litellm-key",
        ),
    )
    return effects


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
    effects = _effects()
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


async def test_compatibility_client_records_the_call_on_the_canonical_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM compatibility callers cannot reach a model without an Invocation."""
    effects = new_in_memory_effect_context(policy_evaluator=binding_scope_policy)
    effects.credentials.add(
        workspace_id="ws-client",
        project_id="project-client",
        record=CredentialRecord(
            key_id=DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
            provider=MODEL_GATEWAY_CREDENTIAL_PROVIDER,
            api_key="test-litellm-key",
        ),
    )
    registry = _registry()
    _patch_gateway(monkeypatch, _OK_BODY)
    client = build_model_chat_client(
        endpoint=GatewayEndpoint(base_url="http://gw"),
        workspace_id="ws-client",
        project_id="project-client",
        effects=effects,
        registry=registry,
        router=CostAwareRouter(registry),
        binding=Binding(
            workspace_id="ws-client",
            project_id="project-client",
            capability=MODEL_CHAT_CAPABILITY,
            credential_refs=(DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,),
        ),
    )

    assert isinstance(client, GovernedModelChatClient)
    body = await client.complete(
        [{"role": "user", "content": "hello"}],
        "fast-model",
        metadata={
            "run_id": "run-client",
            "node_run_id": "node-client",
            "attempt_id": "attempt-client",
            "effect_key": "client:model",
        },
    )

    assert body["choices"][0]["message"]["content"] == "hi"
    history = await effects.invocation_store.list_effect(
        run_id="run-client",
        node_run_id="node-client",
        binding_id=client._binding.binding_id,
        effect_key="client:model",
    )
    assert len(history) == 1
    assert history[0].binding.provider_name == "fast-model"


async def test_compatibility_client_inherits_canonical_execution_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Agent/Run callers retain ambient Workspace and Attempt correlation."""
    effects = new_in_memory_effect_context(policy_evaluator=binding_scope_policy)
    effects.credentials.add(
        workspace_id="ws-run",
        project_id="project-run",
        record=CredentialRecord(
            key_id=DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
            provider=MODEL_GATEWAY_CREDENTIAL_PROVIDER,
            api_key="test-litellm-key",
        ),
    )
    registry = _registry()
    _patch_gateway(monkeypatch, _OK_BODY)
    client = build_model_chat_client(
        endpoint=GatewayEndpoint(base_url="http://gw"),
        workspace_id="ws-run",
        project_id="project-run",
        effects=effects,
        registry=registry,
        router=CostAwareRouter(registry),
        binding=Binding(
            workspace_id="ws-run",
            project_id="project-run",
            capability=MODEL_CHAT_CAPABILITY,
            credential_refs=(DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,),
        ),
    )

    with bind_execution_context(
        workspace_id="ws-run",
        project_id="project-run",
        run_id="run-context",
        node_run_id="node-context",
        attempt_id="attempt-context",
    ):
        await client.complete(
            [{"role": "user", "content": "hello"}],
            "fast-model",
            metadata={"effect_key": "context:model"},
        )

    binding_id = client._binding.binding_id
    history = await effects.invocation_store.list_effect(
        run_id="run-context",
        node_run_id="node-context",
        binding_id=binding_id,
        effect_key="context:model",
    )
    assert len(history) == 1
    assert history[0].attempt_id == "attempt-context"
    assert history[0].binding.provider_name == "fast-model"


async def test_compatibility_client_forwards_the_execution_actor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Invocation carries the actor the executing caller authenticated.

    #1084: the compatibility path used to drop an actor the caller held, so
    every chat/voice Invocation recorded an empty principal while its Run
    carried the authenticated one. The actor crosses the same seam as the
    execution identity — bound by the caller that authenticated it, never
    invented here.
    """
    effects = new_in_memory_effect_context(policy_evaluator=binding_scope_policy)
    effects.credentials.add(
        workspace_id="ws-actor",
        project_id="project-actor",
        record=CredentialRecord(
            key_id=DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
            provider=MODEL_GATEWAY_CREDENTIAL_PROVIDER,
            api_key="test-litellm-key",
        ),
    )
    registry = _registry()
    _patch_gateway(monkeypatch, _OK_BODY)
    client = build_model_chat_client(
        endpoint=GatewayEndpoint(base_url="http://gw"),
        workspace_id="ws-actor",
        project_id="project-actor",
        effects=effects,
        registry=registry,
        router=CostAwareRouter(registry),
        binding=Binding(
            workspace_id="ws-actor",
            project_id="project-actor",
            capability=MODEL_CHAT_CAPABILITY,
            credential_refs=(DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,),
        ),
    )

    with model_execution_context(
        run_id="run-actor",
        node_run_id="node-actor",
        attempt_id="attempt-actor",
        actor_id="alice",
    ):
        await client.complete(
            [{"role": "user", "content": "hello"}],
            "fast-model",
            metadata={"effect_key": "actor:model"},
        )

    (recorded,) = await effects.invocation_store.list_effect(
        run_id="run-actor",
        node_run_id="node-actor",
        binding_id=client._binding.binding_id,
        effect_key="actor:model",
    )
    assert recorded.actor_id == "alice"


async def test_compatibility_client_without_an_actor_records_no_principal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller that supplies no actor still records "", never a guess.

    The ledger reads an empty ``actor_id`` as "no actor" (budget matching
    treats it as system). Fabricating a principal here would forge exactly
    the attribution the actor-required guard (#1841) exists to prevent.
    """
    effects = new_in_memory_effect_context(policy_evaluator=binding_scope_policy)
    effects.credentials.add(
        workspace_id="ws-actor",
        project_id="project-actor",
        record=CredentialRecord(
            key_id=DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
            provider=MODEL_GATEWAY_CREDENTIAL_PROVIDER,
            api_key="test-litellm-key",
        ),
    )
    registry = _registry()
    _patch_gateway(monkeypatch, _OK_BODY)
    client = build_model_chat_client(
        endpoint=GatewayEndpoint(base_url="http://gw"),
        workspace_id="ws-actor",
        project_id="project-actor",
        effects=effects,
        registry=registry,
        router=CostAwareRouter(registry),
        binding=Binding(
            workspace_id="ws-actor",
            project_id="project-actor",
            capability=MODEL_CHAT_CAPABILITY,
            credential_refs=(DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,),
        ),
    )

    await client.complete(
        [{"role": "user", "content": "hello"}],
        "fast-model",
        metadata={
            "run_id": "run-anon",
            "node_run_id": "node-anon",
            "attempt_id": "attempt-anon",
            "effect_key": "anon:model",
        },
    )

    (recorded,) = await effects.invocation_store.list_effect(
        run_id="run-anon",
        node_run_id="node-anon",
        binding_id=client._binding.binding_id,
        effect_key="anon:model",
    )
    assert recorded.actor_id == ""


async def test_unpinned_unaliased_request_uses_router_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No pin and no alias: the cost-aware router picks, with fallback parity."""

    registry = _registry()
    registry.mark_unavailable("fast-model")
    router = CostAwareRouter(registry)
    _patch_gateway(monkeypatch, _OK_BODY)
    effects = _effects()
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
    effects = _effects()
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


@pytest.mark.parametrize("alias", ["", "slow-model", "gateway-only-alias"])
@pytest.mark.parametrize("pin", ["unregistered-pin", "fast-model"])
async def test_binding_pin_refuses_before_setup_and_gateway(
    monkeypatch: pytest.MonkeyPatch, alias: str, pin: str
) -> None:
    """A pin is registry authority, never an unregistered request alias (#56)."""
    from unittest.mock import AsyncMock

    effects = _effects()
    registry = _registry()
    registry.mark_unavailable("fast-model")
    router = CostAwareRouter(registry)
    select = AsyncMock(side_effect=AssertionError("a pin must not use the router"))
    monkeypatch.setattr(router, "select", select)
    # A successful fake terminal makes the pre-fix failure safe and meaningful:
    # before the repair this actually dispatches instead of refusing.
    dispatch = AsyncMock(return_value=_OK_BODY)
    monkeypatch.setattr("maistro.capabilities.model_chat.execute_model_chat", dispatch)
    setup = AsyncMock()
    binding = _binding(provider_name=pin)
    egress = ModelChatEgress(
        effects,
        registry=registry,
        router=router,
        endpoint=GatewayEndpoint(base_url="https://gateway.invalid"),
    )

    reason = r"register.*ProviderRegistry" if pin == "unregistered-pin" else "does not fall back"
    with pytest.raises(CapabilityUnavailable, match=reason):
        await egress.complete(
            binding=binding,
            run_id="pin-run",
            node_run_id="pin-node",
            attempt_id="pin-attempt",
            effect_key="unknown-pin",
            request=ModelChatRequest(model=alias, messages=[]),
            setup=setup,
        )

    select.assert_not_called()
    setup.assert_not_called()
    dispatch.assert_not_called()
    assert (
        await effects.invocation_store.list_effect(
            run_id="pin-run",
            node_run_id="pin-node",
            binding_id=binding.binding_id,
            effect_key="unknown-pin",
        )
        == []
    )


async def test_unavailable_request_alias_is_not_described_as_a_binding_pin() -> None:
    registry = _registry()
    registry.mark_unavailable("fast-model")
    resolve = resolve_model_chat_provider(registry, CostAwareRouter(registry), alias="fast-model")

    result = await resolve(_binding())

    assert isinstance(result, Unavailable)
    assert "request alias" in result.reason
    assert "pinned" not in result.reason
    assert "does not fall back" in result.reason


async def test_unregistered_alias_still_reaches_gateway_with_absent_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gateway aliases absent from the registry keep today's passthrough."""

    effects = _effects()
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
    effects = _effects()
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
    effects = _effects()
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
    effects = new_in_memory_effect_context(
        usage_log=InMemoryUsageLog(),
        quota_tracker=tracker,
        policy_evaluator=binding_scope_policy,
    )
    # Binding-scoped credential routing (#1091): every governed call in this
    # file crosses the credential seam, so the gateway credential the binding
    # authorizes must exist in its Workspace/Project scope.
    effects.credentials.add(
        workspace_id="ws1",
        project_id="p1",
        record=CredentialRecord(
            key_id=DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
            provider=MODEL_GATEWAY_CREDENTIAL_PROVIDER,
            api_key="test-litellm-key",
        ),
    )
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
    effects = new_in_memory_effect_context(
        usage_log=InMemoryUsageLog(),
        quota_tracker=tracker,
        policy_evaluator=binding_scope_policy,
    )
    effects.credentials.add(
        workspace_id="ws1",
        project_id="p1",
        record=CredentialRecord(
            key_id=DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
            provider=MODEL_GATEWAY_CREDENTIAL_PROVIDER,
            api_key="test-litellm-key",
        ),
    )
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

    effects = _effects()
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

    effects = _effects()
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

    router = CredentialRouter()
    router.add(
        workspace_id="ws1",
        project_id="p1",
        record=CredentialRecord(
            key_id=DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
            provider=MODEL_GATEWAY_CREDENTIAL_PROVIDER,
            api_key="test-litellm-key",
        ),
    )

    class _StubEffects:
        invocations = _StubInvocations()

        def credential_routing(self) -> CredentialRouting:
            # `_StubInvocations.invoke()` never calls the routed
            # resolver/executor it's handed (it returns a canned result
            # directly), but the test below calls the captured resolver
            # itself, which does route through this credential (#1091).
            return CredentialRouting(router)

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
    # The captured resolver is the credential-routed wrapper (#1091), so the
    # resolved value is the CredentialBackedProvider around the gateway
    # provider `tracked_resolve` itself recorded into `selected`.
    provider = await captured["resolver"](_binding())
    assert isinstance(provider, CredentialBackedProvider)
    assert isinstance(provider.base, LlmGatewayProvider)
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
    effects = _effects()
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


# --- physical executor's own fail-closed checks (#1091) ---------------------
#
# On the real governed path the resolver is always credential-routed before
# the executor ever runs (every test above goes through it), so these two
# checks inside `execute()` are defense in depth against a resolver seam that
# skipped credential routing -- never reachable by construction through
# `ModelChatEgress.complete()` alone. They are exercised the same way
# `test_usage_from_without_tracked_provider_returns_none` reaches the raw
# resolver/executor: stub `effects.invocations.invoke` to capture the routed
# executor `complete()` builds, then call it directly with a provider shape
# each check exists to refuse.


async def _capture_routed_executor(egress_kwargs: dict[str, Any]) -> Any:
    """Run one `complete()` call through a stub `invocations.invoke` that
    hands back the routed executor instead of actually invoking it."""

    from types import SimpleNamespace

    captured: dict[str, Any] = {}

    class _StubInvocations:
        async def invoke(self, *, executor: Any, **kwargs: Any) -> Any:
            captured["executor"] = executor
            return SimpleNamespace(
                invocation_id="inv-stub",
                binding=SimpleNamespace(provider_name="fast-model"),
                result={},
                usage=None,
            )

    router = CredentialRouter()

    class _StubEffects:
        invocations = _StubInvocations()

        def credential_routing(self) -> CredentialRouting:
            return CredentialRouting(router)

    registry = _registry()
    egress = ModelChatEgress(
        _StubEffects(),  # type: ignore[arg-type]
        registry=registry,
        router=CostAwareRouter(registry),
        endpoint=GatewayEndpoint(base_url="http://gw"),
    )
    await egress.complete(**egress_kwargs)
    return captured["executor"]


async def test_execute_refuses_a_provider_without_a_routed_credential() -> None:
    """Line 178-179: a provider that never crossed credential routing (not a
    `CredentialBackedProvider`) must not reach the gateway HTTP call at all --
    `CredentialRouting.executor`'s own wrapper passes such a provider straight
    to `execute` unchanged (it only wraps `CredentialBackedProvider`
    instances), so `execute` itself is the last fail-closed check."""

    executor = await _capture_routed_executor(
        {
            "binding": _binding(),
            "run_id": "r1",
            "node_run_id": "nr1",
            "attempt_id": "a1",
            "effect_key": "test:no-credential",
            "request": ModelChatRequest(messages=[{"role": "user", "content": "hi"}]),
        }
    )

    class _BareProvider:
        name = "fast-model"
        slot = MODEL_CHAT_CAPABILITY
        trust_tier = "t1"

    with pytest.raises(TypeError, match="Binding-scoped credential"):
        await executor(_BareProvider(), {})


async def test_execute_refuses_a_credential_backed_non_gateway_provider() -> None:
    """Line 183-184: even once credential-routed, the wrapped base provider
    must still be the one approved gateway Provider -- a `CredentialBackedProvider`
    around anything else (a slot-specific resolver bug, or a future second
    Provider that forgets this boundary) is refused rather than handed an
    HTTP client it was never built for."""

    from maistro.credentials.types import CredentialRecord

    executor = await _capture_routed_executor(
        {
            "binding": _binding(),
            "run_id": "r1",
            "node_run_id": "nr1",
            "attempt_id": "a1",
            "effect_key": "test:non-gateway",
            "request": ModelChatRequest(messages=[{"role": "user", "content": "hi"}]),
        }
    )

    class _NonGatewayProvider:
        name = "not-a-gateway"
        slot = MODEL_CHAT_CAPABILITY
        trust_tier = "t1"
        credential_provider = MODEL_GATEWAY_CREDENTIAL_PROVIDER

    wrapped = CredentialBackedProvider(
        base=_NonGatewayProvider(),  # type: ignore[arg-type]
        credential=CredentialRecord(
            key_id=DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
            provider=MODEL_GATEWAY_CREDENTIAL_PROVIDER,
            api_key="test-litellm-key",
        ),
        workspace_id="ws1",
        project_id="p1",
    )

    with pytest.raises(TypeError, match="non-gateway provider"):
        await executor(wrapped, {})


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
    effects = _effects()
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


async def test_client_complete_adopts_bound_context_or_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller that never set a turn uses canonical identity — only a real one.

    `Agent.handle` always calls `set_turn` first, but the client is also the
    factory's LLMClient for strategies driven outside that seam. `complete`
    adopts the Run/NodeRun/Attempt triple canonical execution bound on the
    correlation context when there is one (#1827). When canonical execution
    bound nothing, the client refuses with RunIntegrityError and makes zero
    egress calls instead of minting a fabricated identity that would make an
    unadmitted call look governed (#718's no-ungoverned-side-door rule now
    means refuse, not invent).
    """
    tracker = InMemoryQuotaTracker()
    effects = new_in_memory_effect_context(
        usage_log=InMemoryUsageLog(),
        quota_tracker=tracker,
        policy_evaluator=binding_scope_policy,
    )
    effects.credentials.add(
        workspace_id="ws1",
        project_id="p1",
        record=CredentialRecord(
            key_id=DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
            provider=MODEL_GATEWAY_CREDENTIAL_PROVIDER,
            api_key="test-litellm-key",
        ),
    )
    registry = _registry()
    _patch_gateway(monkeypatch, _OK_BODY)
    client = GovernedLLMClient(
        effects,
        registry=registry,
        router=CostAwareRouter(registry),
        endpoint=GatewayEndpoint(base_url="http://gw:4000"),
        workspace_id="ws1",
        project_id="p1",
    )

    # No canonical context in scope: refuse with zero egress.
    with detached_execution_context(), pytest.raises(RunIntegrityError):
        await client.complete([{"role": "user", "content": "hello"}], "fast-model")
    assert await tracker.get_all_usage() == []

    # A complete bound context is adopted wholesale, without an explicit
    # set_turn: the usage the fake gateway reported still reaches the quota
    # ledger, under the canonical identity the execution bound.
    with bind_execution_context(
        run_id="run-adopt",
        node_run_id="node-adopt",
        attempt_id="attempt-adopt",
    ):
        body = await client.complete([{"role": "user", "content": "hello"}], "fast-model")

    assert body["choices"][0]["message"]["content"] == "hi"
    (entry,) = await tracker.get_all_usage()
    assert entry["request_count"] == 1


# --- Incremental streaming through the governed lifecycle (SPEC-285) --------


class _LiveStreamResponse:
    """A real SSE wire the test paces: yields lines, waits when told to."""

    def __init__(
        self,
        lines: list[str],
        *,
        after_line: Callable[[], Awaitable[None]] | None = None,
        fail_at_line: int | None = None,
        status: int = 200,
    ) -> None:
        self._lines = lines
        self._after_line = after_line
        self._fail_at_line = fail_at_line
        self._served = 0
        self.status_code = status
        self.headers: dict[str, str] = {}

    @property
    def is_success(self) -> bool:
        return self.status_code < 400

    async def __aenter__(self) -> _LiveStreamResponse:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def aread(self) -> bytes:
        return b""

    async def aiter_lines(self) -> Any:
        for line in self._lines:
            if self._fail_at_line is not None and self._served >= self._fail_at_line:
                raise RuntimeError("wire cut mid-stream")
            self._served += 1
            yield line
            if self._after_line is not None:
                await self._after_line()


class _LiveStreamClient:
    """httpx.AsyncClient stand-in: the socket is fake, the pacing is real."""

    def __init__(
        self,
        lines: list[str],
        *,
        after_line: Callable[[], Awaitable[None]] | None = None,
        fail_at_line: int | None = None,
        status: int = 200,
    ) -> None:
        self._args: tuple[Any, ...] = ()
        self._kwargs: dict[str, Any] = {}
        self._lines = lines
        self._after_line = after_line
        self._fail_at_line = fail_at_line
        self._status = status
        self.dispatches = 0

    async def __aenter__(self) -> _LiveStreamClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    def stream(self, *args: Any, **kwargs: Any) -> _LiveStreamResponse:
        self.dispatches += 1
        self._args, self._kwargs = args, kwargs
        return _LiveStreamResponse(
            self._lines,
            after_line=self._after_line,
            fail_at_line=self._fail_at_line,
            status=self._status,
        )


def _stream_client(
    monkeypatch: pytest.MonkeyPatch,
    lines: list[str],
    *,
    after_line: Callable[[], Awaitable[None]] | None = None,
    fail_at_line: int | None = None,
    status: int = 200,
) -> _LiveStreamClient:
    client = _LiveStreamClient(
        lines, after_line=after_line, fail_at_line=fail_at_line, status=status
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: client)
    return client


def _stream_effects() -> CapabilityEffectContext:
    return _effects()


def _sse_lines(*payloads: str) -> list[str]:
    lines: list[str] = []
    for payload in payloads:
        lines.append(f"data: {payload}")
        lines.append("")
    lines.append("data: [DONE]")
    return lines


_IDENTITY = {
    "run_id": "run-stream",
    "node_run_id": "node-stream",
    "attempt_id": "attempt-stream",
    "effect_key": "stream:model",
}


def _streaming_client(
    effects: CapabilityEffectContext,
    registry: Any,
    timeout_s: float,
    protocol: str = "chat_completions",
) -> GovernedModelChatClient:
    """The compatibility client over real in-memory canonical authorities.

    Each test names its own endpoint timeout: the shared-client pool keys on
    it, so no test ever consumes another test's socket substitute.
    """

    return build_model_chat_client(
        endpoint=GatewayEndpoint(base_url="http://gw", timeout_s=timeout_s),
        workspace_id="ws1",
        project_id="p1",
        effects=effects,
        registry=registry,
        router=CostAwareRouter(registry),
        protocol=protocol,
        binding=Binding(
            workspace_id="ws1",
            project_id="p1",
            capability=MODEL_CHAT_CAPABILITY,
            credential_refs=(DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,),
        ),
    )


@pytest.mark.contract("behavioral")
@pytest.mark.ac("SPEC-285/AC-1")
async def test_stream_reaches_the_consumer_while_the_invocation_is_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chunks cross to the caller live, before the Invocation terminalizes.

    The wire refuses to emit its second line until the consumer has actually
    received the first one through the governed bridge. A buffering regression
    never satisfies that handshake, the wire aborts loudly, and the chunk
    assertions fail — the proof is structural (the consumer observed a chunk
    the provider had not finished producing), not wall-clock.
    """

    first_chunk_received = asyncio.Event()

    async def pace() -> None:
        # After the first line: hold the wire until the consumer has the chunk.
        try:
            await asyncio.wait_for(first_chunk_received.wait(), timeout=5)
        except TimeoutError:
            raise RuntimeError(
                "bridge buffered the stream: the consumer never received the "
                "first chunk while the provider was still producing"
            ) from None

    lines = _sse_lines(
        '{"choices":[{"delta":{"content":"Hel"}}]}',
        '{"choices":[{"delta":{"content":"lo"},"finish_reason":"stop"}]}',
        '{"usage":{"prompt_tokens":10,"completion_tokens":3},"choices":[]}',
    )
    effects = _stream_effects()
    registry = _registry()
    _stream_client(monkeypatch, lines, after_line=pace)
    client = _streaming_client(effects, registry, timeout_s=101.0)

    chunks: list[dict[str, Any]] = []
    async for chunk in client.stream_chunks(
        [{"role": "user", "content": "hello"}],
        "fast-model",
        metadata=dict(_IDENTITY),
    ):
        chunks.append(chunk)
        if len(chunks) == 1:
            first_chunk_received.set()

    def _contents(received: list[dict[str, Any]]) -> list[str]:
        return [
            c["choices"][0]["delta"]["content"]
            for c in received
            if c.get("choices") and c["choices"][0].get("delta", {}).get("content")
        ]

    assert _contents(chunks) == ["Hel", "lo"]
    # The terminal usage chunk crosses too — it is part of the stream.
    assert any(c.get("usage") for c in chunks)
    (recorded,) = await effects.invocation_store.list_effect(
        run_id="run-stream",
        node_run_id="node-stream",
        binding_id=client._binding.binding_id,
        effect_key="stream:model",
    )
    # Terminalized, and only after full consumption — with the usage the
    # terminal usage chunk reported, which a streamed call used to lose.
    assert recorded.status is InvocationStatus.COMPLETED
    assert recorded.usage is not None
    assert recorded.usage.input_units == 10
    assert recorded.usage.output_units == 3
    assert isinstance(recorded.result, dict)
    assert recorded.result["choices"][0]["message"]["content"] == "Hello"
    assert recorded.result["choices"][0]["finish_reason"] == "stop"


@pytest.mark.ac("SPEC-285/AC-2")
async def test_stream_failure_midstream_terminalizes_and_reaches_the_consumer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wire that dies mid-stream fails the Invocation and raises upstream."""

    lines = _sse_lines(
        '{"choices":[{"delta":{"content":"partial"}}]}',
        '{"choices":[{"delta":{"content":" never"}}]}',
    )
    effects = _stream_effects()
    registry = _registry()
    _stream_client(monkeypatch, lines, fail_at_line=2)
    client = _streaming_client(effects, registry, timeout_s=102.0)

    received: list[dict[str, Any]] = []
    with pytest.raises(RuntimeError, match="wire cut mid-stream"):
        async for chunk in client.stream_chunks(
            [{"role": "user", "content": "hello"}],
            "fast-model",
            metadata=dict(_IDENTITY),
        ):
            received.append(chunk)

    assert [c["choices"][0]["delta"]["content"] for c in received] == ["partial"]
    (recorded,) = await effects.invocation_store.list_effect(
        run_id="run-stream",
        node_run_id="node-stream",
        binding_id=client._binding.binding_id,
        effect_key="stream:model",
    )
    # A half-delivered stream is not a success: the record must say so.
    assert recorded.status is InvocationStatus.UNKNOWN
    assert "wire cut mid-stream" in str(recorded.error)


@pytest.mark.contract("boundary")
@pytest.mark.ac("SPEC-285/AC-3")
async def test_stream_abandonment_never_leaves_a_completed_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A consumer that walks away cancels the dispatch, truthfully recorded."""

    first_chunk_received = asyncio.Event()

    async def pace() -> None:
        await first_chunk_received.wait()

    lines = _sse_lines(
        '{"choices":[{"delta":{"content":"only"}}]}',
        '{"choices":[{"delta":{"content":"lost"}}]}',
    )
    effects = _stream_effects()
    registry = _registry()
    _stream_client(monkeypatch, lines, after_line=pace)
    client = _streaming_client(effects, registry, timeout_s=103.0)

    stream = client.stream_chunks(
        [{"role": "user", "content": "hello"}],
        "fast-model",
        metadata=dict(_IDENTITY),
    )
    first = await anext(stream)
    assert first["choices"][0]["delta"]["content"] == "only"
    first_chunk_received.set()
    await stream.aclose()

    (recorded,) = await effects.invocation_store.list_effect(
        run_id="run-stream",
        node_run_id="node-stream",
        binding_id=client._binding.binding_id,
        effect_key="stream:model",
    )
    # The provider outcome is unknown — the Invocation must not claim success.
    assert recorded.status is InvocationStatus.UNKNOWN
    assert "cancelled" in str(recorded.error)


@pytest.mark.ac("SPEC-285/AC-4")
async def test_deduplicated_stream_replays_the_record_without_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A replayed effect streams its recorded chunks and never re-dispatches."""

    lines = _sse_lines(
        '{"choices":[{"delta":{"content":"once"}}]}',
        '{"choices":[{"delta":{},"finish_reason":"stop"}]}',
    )
    effects = _stream_effects()
    registry = _registry()
    live = _stream_client(monkeypatch, lines)
    client = _streaming_client(effects, registry, timeout_s=104.0)

    def consume() -> Any:
        return client.stream_chunks(
            [{"role": "user", "content": "hello"}],
            "fast-model",
            metadata=dict(_IDENTITY),
        )

    first = [chunk async for chunk in consume()]
    second = [chunk async for chunk in consume()]

    assert live.dispatches == 1, "a deduplicated stream must not re-dispatch"
    assert [c["choices"][0]["delta"] for c in second] == [c["choices"][0]["delta"] for c in first]


@pytest.mark.ac("SPEC-285/AC-2")
async def test_stream_http_refusal_records_failed_not_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A not-applied HTTP refusal on the stream records FAILED, not UNKNOWN.

    SPEC-285's failure table: the wire refusing before any chunk is an
    `EffectNotApplied` (nothing was delivered, safe to reconcile), not an
    unknown-outcome abort — the Invocation must say FAILED for the same
    request a non-streaming call would fail with.
    """

    effects = _stream_effects()
    registry = _registry()
    _stream_client(monkeypatch, [], status=503)
    client = _streaming_client(effects, registry, timeout_s=105.0)

    with pytest.raises(RuntimeError, match="status=503"):
        async for _ in client.stream_chunks(
            [{"role": "user", "content": "hello"}],
            "fast-model",
            metadata=dict(_IDENTITY),
        ):
            pass

    (recorded,) = await effects.invocation_store.list_effect(
        run_id="run-stream",
        node_run_id="node-stream",
        binding_id=client._binding.binding_id,
        effect_key="stream:model",
    )
    assert recorded.status is InvocationStatus.FAILED
    assert "status=503" in str(recorded.error)


async def test_stream_text_helper_yields_only_content_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`stream()` is the text-only view: content deltas only, in order.

    Reasoning deltas and empty terminal chunks are chunks on the wire but are
    not assistant text — the compatibility helper must not leak them as text.
    """

    lines = _sse_lines(
        '{"choices":[{"delta":{"content":"Hel"}}]}',
        '{"choices":[{"delta":{"reasoning_content":"thinking"}}]}',
        '{"choices":[{"delta":{},"finish_reason":"stop"}]}',
        '{"usage":{"prompt_tokens":1,"completion_tokens":1},"choices":[]}',
    )
    effects = _stream_effects()
    registry = _registry()
    _stream_client(monkeypatch, lines)
    client = _streaming_client(effects, registry, timeout_s=106.0)

    text = [
        part
        async for part in client.stream(
            [{"role": "user", "content": "hello"}], "fast-model", metadata=dict(_IDENTITY)
        )
    ]

    assert text == ["Hel"]


async def test_stream_with_caller_scope_dispatches_under_the_scoped_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller-named scope derives the scoped Binding and records under it.

    The stream path scopes exactly like `complete`: the turn's metadata names
    a foreign Workspace, so the client derives (never reaches past its
    authority for) the scoped copy and the Invocation lands under it.
    """

    lines = _sse_lines(
        '{"choices":[{"delta":{"content":"scoped"}}]}',
        '{"choices":[{"delta":{},"finish_reason":"stop"}]}',
    )
    effects = _stream_effects()
    effects.credentials.add(
        workspace_id="ws2",
        project_id="p2",
        record=CredentialRecord(
            key_id=DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
            provider=MODEL_GATEWAY_CREDENTIAL_PROVIDER,
            api_key="scoped-key",
        ),
    )
    registry = _registry()
    _stream_client(monkeypatch, lines)
    client = _streaming_client(effects, registry, timeout_s=107.0)

    chunks = [
        chunk
        async for chunk in client.stream_chunks(
            [{"role": "user", "content": "hello"}],
            "fast-model",
            metadata={**_IDENTITY, "workspace_id": "ws2", "project_id": "p2"},
        )
    ]
    assert [c["choices"][0]["delta"].get("content") for c in chunks if c.get("choices")] == [
        "scoped",
        None,
    ]

    (recorded,) = await effects.invocation_store.list_effect(
        run_id="run-stream",
        node_run_id="node-stream",
        binding_id="model-chat:ws2:p2",
        effect_key="stream:model",
    )
    assert recorded.binding.workspace_id == "ws2"
    assert recorded.binding.project_id == "p2"
    assert recorded.status is InvocationStatus.COMPLETED


@pytest.mark.ac("SPEC-285/AC-5")
async def test_stream_without_terminal_usage_records_none_not_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wire that never reports usage leaves the Invocation unmeasured.

    `usage=None` is the truthful record; zero would fabricate a measurement
    the provider never made.
    """

    lines = _sse_lines(
        '{"choices":[{"delta":{"content":"bare"}}]}',
        '{"choices":[{"delta":{},"finish_reason":"stop"}]}',
    )
    effects = _stream_effects()
    registry = _registry()
    _stream_client(monkeypatch, lines)
    client = _streaming_client(effects, registry, timeout_s=108.0)

    _ = [
        chunk
        async for chunk in client.stream_chunks(
            [{"role": "user", "content": "hello"}],
            "fast-model",
            metadata=dict(_IDENTITY),
        )
    ]

    (recorded,) = await effects.invocation_store.list_effect(
        run_id="run-stream",
        node_run_id="node-stream",
        binding_id=client._binding.binding_id,
        effect_key="stream:model",
    )
    assert recorded.status is InvocationStatus.COMPLETED
    assert recorded.usage is None


def test_replay_falls_back_to_the_recorded_completion_body() -> None:
    """A record without stored chunks replays its completion body once."""

    result = ModelCallResult(
        invocation_id="inv-1",
        model="fast-model",
        body={"choices": [{"message": {"role": "assistant", "content": "recorded"}}]},
    )
    chunks = list(_replay_result_chunks(result))
    assert chunks == [{"choices": [{"delta": {"content": "recorded"}, "finish_reason": "stop"}]}]


def test_replay_without_a_record_yields_nothing() -> None:
    """No terminal record, no replayed chunks — silence, not fabrication."""

    assert list(_replay_result_chunks(None)) == []


@pytest.mark.ac("SPEC-285/AC-6")
async def test_responses_protocol_streams_normalized_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`auto` streams the Responses endpoint through the same one Invocation.

    The shipped default variant tries /responses first: its events cross the
    observer normalized to chat.completions chunks, unusable wire noise is
    skipped rather than fatal, and the same admitted, deduplicated Invocation
    terminalizes with the usage the terminal event reported. A malformed
    usage measurement stays unmeasured (`usage=None`), never zero.
    """

    lines = [
        "data: not-json",  # unparseable: skipped, not fatal
        "data: 123",  # JSON but not an object: skipped
        'data: {"type":"response.output_text.delta","delta":"Hel"}',
        'data: {"type":"response.reasoning_summary_text.delta","delta":"hm"}',
        'data: {"type":"response.output_text.delta","delta":"lo"}',
        'data: {"type":"response.some_future_event","x":1}',  # unrecognized: skipped
        "data: {broken json",  # unparseable: skipped, not fatal
        'data: {"type":"response.completed",'
        '"response":{"usage":{"input_tokens":"many","output_tokens":3}}}',  # malformed usage
    ]
    effects = _stream_effects()
    registry = _registry()
    live = _stream_client(monkeypatch, lines)
    client = _streaming_client(effects, registry, timeout_s=109.0, protocol="auto")

    chunks = [
        chunk
        async for chunk in client.stream_chunks(
            [{"role": "user", "content": "hello"}],
            "fast-model",
            metadata=dict(_IDENTITY),
        )
    ]

    # The request went to the Responses endpoint with the Responses payload…
    assert "/responses" in str(live._args[1])
    payload = live._kwargs["json"]
    assert payload["stream"] is True
    assert payload["input"] == [{"role": "user", "content": "hello"}]
    # …normalized: text deltas crossed as content chunks, reasoning as
    # reasoning_content, the terminal event as a stop chunk.
    contents = [
        c["choices"][0]["delta"]["content"]
        for c in chunks
        if c.get("choices") and c["choices"][0].get("delta", {}).get("content") is not None
    ]
    assert contents == ["Hel", "lo"]
    assert any(c["choices"][0]["delta"].get("reasoning_content") == "hm" for c in chunks)
    assert any(c.get("choices") and c["choices"][0].get("finish_reason") == "stop" for c in chunks)

    (recorded,) = await effects.invocation_store.list_effect(
        run_id="run-stream",
        node_run_id="node-stream",
        binding_id=client._binding.binding_id,
        effect_key="stream:model",
    )
    # One governed Invocation for the streamed call; the malformed usage
    # measurement is absent, not zeroed.
    assert live.dispatches == 1
    assert recorded.status is InvocationStatus.COMPLETED
    assert recorded.usage is None


async def test_auto_protocol_reraises_a_response_auth_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 401 from /responses must surface, not silently retry as chat."""

    class _Resp:
        status_code = 401

        def json(self) -> dict[str, Any]:
            return {"error": "bad key"}

    posts: list[str] = []

    class _Client:
        def __init__(self, *a: Any, **kw: Any) -> None: ...

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *a: Any) -> None: ...

        async def post(self, url: str, **kw: Any) -> _Resp:
            posts.append(url)
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    effects = _effects()
    registry = _registry()
    egress = ModelChatEgress(
        effects,
        registry=registry,
        router=CostAwareRouter(registry),
        endpoint=GatewayEndpoint(base_url="http://gw:4000"),
    )
    request = ModelChatRequest(
        model="fast-model", messages=[{"role": "user", "content": "hi"}], protocol="auto"
    )
    with pytest.raises(RuntimeError, match="status=401"):
        await egress.complete(
            binding=_binding(),
            run_id="r-auto",
            node_run_id="nr-auto",
            attempt_id="a-auto",
            effect_key="auto:model",
            request=request,
        )
    assert len(posts) == 1, "an auth refusal must not be retried on the other protocol"


async def test_auto_protocol_falls_back_when_responses_refuses_the_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`auto` retries the chat endpoint when /responses refuses the request.

    A not-applied refusal that is not an auth failure (here: the endpoint
    rejecting the Responses payload with 404) falls back to
    chat.completions; an auth refusal does not (the previous test).
    """

    posts: list[str] = []

    class _Resp:
        def __init__(self, status_code: int, body: dict[str, Any]) -> None:
            self.status_code = status_code
            self._body = body

        def json(self) -> dict[str, Any]:
            return self._body

    class _Client:
        def __init__(self, *a: Any, **kw: Any) -> None: ...

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *a: Any) -> None: ...

        async def post(self, url: str, **kw: Any) -> _Resp:
            posts.append(url)
            if url.endswith("/responses"):
                return _Resp(404, {"error": "no responses route"})
            return _Resp(200, _OK_BODY)

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    effects = _effects()
    registry = _registry()
    egress = ModelChatEgress(
        effects,
        registry=registry,
        router=CostAwareRouter(registry),
        endpoint=GatewayEndpoint(base_url="http://gw:4000"),
    )
    request = ModelChatRequest(
        model="fast-model", messages=[{"role": "user", "content": "hi"}], protocol="auto"
    )
    result = await egress.complete(
        binding=_binding(),
        run_id="r-auto2",
        node_run_id="nr-auto2",
        attempt_id="a-auto2",
        effect_key="auto2:model",
        request=request,
    )
    assert [u.endswith("/responses") or u.endswith("/chat/completions") for u in posts] == [
        True,
        True,
    ]
    assert result.body["choices"][0]["message"]["content"] == "hi"


def test_build_model_chat_client_supplies_default_authorities_when_omitted() -> None:
    """Omitting the effect context composes the process-default one.

    The compatibility constructor must not silently return an ungoverned
    client: with no effects supplied it binds the process default context,
    so a caller that forgets the authority still lands on the ledger.
    """

    client = build_model_chat_client(endpoint=GatewayEndpoint(base_url="http://gw", timeout_s=1.0))
    assert isinstance(client, GovernedModelChatClient)
