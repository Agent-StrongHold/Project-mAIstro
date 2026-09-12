"""Replica conformance for the canonical effect authority (#1133)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from maistro.capabilities.binding import Binding, ResolvedCapabilityProvider
from maistro.capabilities.invocation import (
    InMemoryInvocationStore,
    Invocation,
    InvocationExecutionService,
    UnsafeEffectRetry,
)


@dataclass(frozen=True)
class _Provider:
    name: str = "replica-test"
    slot: str = "test.effect"
    trust_tier: str = "trusted"


@pytest.mark.asyncio
async def test_independent_services_cannot_dispatch_the_same_effect_twice() -> None:
    """Both replicas see an empty history before either creates its claim.

    Sharing a store, not an execution service, models independent process
    locks. The durable-backend variants additionally use separate connections.
    """
    store = InMemoryInvocationStore()
    services = [InvocationExecutionService(store=store) for _ in range(2)]
    binding = Binding(workspace_id="workspace", project_id="project", capability="test.effect")
    barrier = asyncio.Barrier(2)
    calls = 0

    async def resolve(_binding: Binding) -> ResolvedCapabilityProvider:
        await asyncio.wait_for(barrier.wait(), timeout=5)
        return _Provider()

    async def execute(_provider: ResolvedCapabilityProvider, request: Any) -> Any:
        nonlocal calls
        calls += 1
        return request

    outcomes = await asyncio.gather(
        *(
            service.invoke(
                binding=binding,
                run_id="run",
                node_run_id="node-run",
                attempt_id=f"attempt-{index}",
                effect_key="one-logical-effect",
                request={"value": 42},
                resolver=resolve,
                executor=execute,
            )
            for index, service in enumerate(services)
        ),
        return_exceptions=True,
    )
    assert calls == 1, "per-service locks must not authorize duplicate physical dispatch"
    assert all(isinstance(outcome, (Invocation, UnsafeEffectRetry)) for outcome in outcomes)
    history = await store.list_effect(
        run_id="run",
        node_run_id="node-run",
        binding_id=binding.binding_id,
        effect_key="one-logical-effect",
    )
    assert len(history) == 1
