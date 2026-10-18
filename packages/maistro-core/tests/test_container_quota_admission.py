"""Quota admission must refuse unknown model bounds before physical dispatch."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import aiosqlite
import pytest
import pytest_asyncio

from maistro.capabilities.binding import Binding
from maistro.capabilities.effect_context import CapabilityEffectContext
from maistro.capabilities.invocation import Invocation, InvocationStatus
from maistro.capabilities.providers.llm_gateway import (
    LlmGatewayProvider,
    ModelChatRequest,
    _chat_payload,
)
from maistro.container import _wire_capability_effects
from maistro.providers.registry import InMemoryProviderRegistry
from maistro.providers.types import ModelMetadata
from maistro.quota.invocation_quota import InvocationQuotaDenied, QuotaBudget, QuotaUnit
from maistro.quota.sqlite_invocation_quota import SqliteInvocationQuota

_MODEL = ModelMetadata(
    name="priced-model",
    provider="gateway-alias",
    cost_per_1k_input=1.0,
    cost_per_1k_output=1.0,
    latency_p50_ms=1,
)
_BINDING = Binding(
    binding_id="model-binding",
    workspace_id="workspace",
    project_id="project",
    capability="model.chat",
    provider_name=_MODEL.name,
)
_REQUESTS = [
    pytest.param({}, id="empty-default"),
    pytest.param({"messages": [{"role": "user", "content": "hello"}]}, id="plain-text"),
    pytest.param({"messages": [{"role": "user", "content": "🧑🏽‍🚀" * 100}]}, id="unicode"),
    pytest.param(
        {"messages": [{"role": "user", "content": "hi", "name": "n" * 10_000}]},
        id="full-message-fields",
    ),
    pytest.param(
        {
            "messages": [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {"name": "lookup", "arguments": "x" * 10_000},
                        }
                    ],
                }
            ]
        },
        id="tool-call-history",
    ),
    pytest.param(
        {
            "tools": [
                {"type": "function", "function": {"name": "lookup", "description": "x" * 10_000}}
            ]
        },
        id="tool-schema",
    ),
    pytest.param(
        {
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "answer", "schema": {"description": "x" * 10_000}},
            }
        },
        id="response-schema",
    ),
    pytest.param(
        {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": "https://example.invalid/image.png"},
                        }
                    ],
                }
            ]
        },
        id="multimodal",
    ),
]


@pytest_asyncio.fixture
async def effects(tmp_path: Path) -> AsyncIterator[CapabilityEffectContext]:
    database = tmp_path / "effects.sqlite3"
    async with aiosqlite.connect(database) as connection:
        yield await _wire_capability_effects(
            pg_pool=None,
            db_pool=connection,
            database_url=f"sqlite:///{database}",
            provider_registry=InMemoryProviderRegistry(models=[_MODEL]),
            capability_bindings=[_BINDING],
        )


def _quota(effects: CapabilityEffectContext) -> SqliteInvocationQuota:
    assert isinstance(effects.quota, SqliteInvocationQuota)
    return effects.quota


async def _budget(effects: CapabilityEffectContext, unit: QuotaUnit, limit: int) -> None:
    await _quota(effects).register_budget(
        QuotaBudget(
            budget_id=unit,
            unit=unit,
            limit=limit,
            period_start=0,
            period_end=2**62,
            coverage_ref="test-fresh-period",
            opening_spend=0,
            provider_name=_MODEL.name,
        )
    )


async def _invoke(
    effects: CapabilityEffectContext, request: ModelChatRequest, payloads: list[dict[str, object]]
) -> Invocation:
    async def resolve(_binding: Binding) -> LlmGatewayProvider:
        return LlmGatewayProvider(_MODEL, model=_MODEL.name)

    async def execute(provider: Any, value: Any) -> dict[str, object]:
        # Use the real provider serialization at the physical execution seam.
        # No network call is made by this fake provider transport.
        payloads.append(_chat_payload(provider, value))
        return {"choices": []}

    return await effects.invocations.invoke(
        binding=_BINDING,
        run_id="run",
        node_run_id="node",
        attempt_id="attempt",
        effect_key="chat",
        actor_id="principal",
        request=request,
        resolver=resolve,
        executor=execute,
    )


@pytest.mark.parametrize("unit", ["tokens", "micro_usd"])
@pytest.mark.parametrize("fields", _REQUESTS)
@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
async def test_unknown_full_input_bound_refuses_before_dispatch(
    effects: CapabilityEffectContext, unit: QuotaUnit, fields: dict[str, Any]
) -> None:
    await _budget(effects, unit, 1_000_000)
    request = ModelChatRequest(model=_MODEL.name, max_tokens=100, **fields)
    payloads: list[dict[str, object]] = []

    with pytest.raises(InvocationQuotaDenied, match="missing upper bound"):
        await _invoke(effects, request, payloads)

    assert payloads == []
    balance = await _quota(effects).balance(unit)
    assert balance.spent == balance.held == 0
    history = await effects.invocation_store.list_effect(
        run_id="run", node_run_id="node", binding_id=_BINDING.binding_id, effect_key="chat"
    )
    assert len(history) == 1
    assert history[0].status is InvocationStatus.FAILED
    assert not history[0].dispatch_active


@pytest.mark.parametrize("max_tokens", [None, 0, -1])
async def test_unbounded_output_never_becomes_zero_money_reservation(
    effects: CapabilityEffectContext, max_tokens: int | None
) -> None:
    # The former production estimator admitted and held 100 micro-USD for
    # "hi" with no max_tokens, despite allowing an unbounded output charge.
    await _budget(effects, "micro_usd", 100)
    request = ModelChatRequest(
        model=_MODEL.name, messages=[{"role": "user", "content": "hi"}], max_tokens=max_tokens
    )
    payloads: list[dict[str, object]] = []
    with pytest.raises(InvocationQuotaDenied, match="missing upper bound"):
        await _invoke(effects, request, payloads)
    assert payloads == []
    assert (await _quota(effects).balance("micro_usd")).held == 0


@pytest.mark.parametrize("unit", [None, "requests"])
@pytest.mark.parametrize("fields", _REQUESTS)
async def test_unconfigured_and_request_only_quotas_preserve_payload_and_replay(
    effects: CapabilityEffectContext, unit: QuotaUnit | None, fields: dict[str, Any]
) -> None:
    if unit is not None:
        await _budget(effects, unit, 1)
    request = ModelChatRequest(model=_MODEL.name, **fields)
    payloads: list[dict[str, object]] = []
    first = await _invoke(effects, request, payloads)
    replay = await _invoke(effects, request, payloads)
    assert first.status is InvocationStatus.COMPLETED
    assert replay.invocation_id == first.invocation_id
    assert payloads == [_chat_payload(LlmGatewayProvider(_MODEL, model=_MODEL.name), request)]
    assert "max_tokens" not in payloads[0]
    if unit is not None:
        balance = await _quota(effects).balance(unit)
        assert balance.spent == 1
        assert balance.held == 0


async def test_injected_adapter_backed_quota_retains_numeric_admission(
    effects: CapabilityEffectContext, tmp_path: Path
) -> None:
    """The safety fallback does not replace a host's existing trusted estimator."""
    from maistro.capabilities.effect_context import binding_scope_policy, new_effect_context
    from maistro.quota.invocation_quota import QuotaEstimate

    async def enforced_bound(_invocation: Invocation, _binding: Binding) -> QuotaEstimate:
        # This fake adapter reserves its declared physical maximum. A production
        # adapter must enforce/prove its bound; registry price alone cannot.
        return QuotaEstimate(principal_id="principal", tokens=60, micro_usd=600)

    quota = SqliteInvocationQuota(tmp_path / "bounded.sqlite3", estimate=enforced_bound)
    await quota.ensure_schema()
    injected = new_effect_context(
        invocation_store=effects.invocation_store,
        binding_store=effects.bindings,
        event_store=effects.event_store,
        approval_store=effects.approval_store,
        policy_evaluator=binding_scope_policy,
        quota=quota,
    )
    selected = await _wire_capability_effects(
        pg_pool=None,
        db_pool=None,
        effect_context=injected,
        capability_bindings=[_BINDING],
        provider_registry=InMemoryProviderRegistry(models=[_MODEL]),
    )
    assert selected is injected
    await _budget(selected, "tokens", 60)
    await _budget(selected, "micro_usd", 600)
    await _budget(selected, "requests", 1)
    payloads: list[dict[str, object]] = []
    request = ModelChatRequest(model=_MODEL.name, messages=[], max_tokens=10)
    first = await _invoke(selected, request, payloads)
    replay = await _invoke(selected, request, payloads)
    assert first.status is InvocationStatus.COMPLETED
    assert replay.invocation_id == first.invocation_id
    assert len(payloads) == 1
    # Unreported usage conservatively keeps numeric holds through the replay.
    assert (await quota.balance("tokens")).held == 60
    assert (await quota.balance("micro_usd")).held == 600
    assert (await quota.balance("requests")).spent == 1
