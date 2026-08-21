from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from maistro.capabilities.binding import Binding
from maistro.capabilities.governed_invocation import (
    GovernedInvocationExecutionService,
    InvocationApprovalRequired,
    InvocationDenied,
    InvocationPolicyContext,
)
from maistro.capabilities.invocation import InMemoryInvocationStore, InvocationExecutionService
from maistro.events.envelope import InMemoryEventStore
from maistro.policy.types import Decision, PolicyVerdict


@dataclass(frozen=True)
class _Provider:
    name: str = "provider-a"
    slot: str = "external_write"
    trust_tier: str = "trusted"


def _binding() -> Binding:
    return Binding(
        binding_id="binding-1",
        workspace_id="ws-1",
        project_id="project-1",
        node_id="node-1",
        capability="external_write",
        policy_refs=("policy-1",),
    )


async def _resolver(_binding: Binding) -> _Provider:
    return _Provider()


async def _executor(_provider: _Provider, request: Any) -> dict[str, Any]:
    return {"committed": request}


@pytest.mark.asyncio
async def test_denied_policy_records_event_and_never_calls_provider() -> None:
    invocation_store = InMemoryInvocationStore()
    event_store = InMemoryEventStore()
    called = False

    async def policy(
        _binding: Binding,
        _request: Any,
        _context: InvocationPolicyContext,
    ) -> PolicyVerdict:
        return PolicyVerdict(Decision.DENY, reason="scope denied", rule="workspace-write")

    async def executor(_provider: _Provider, _request: Any) -> None:
        nonlocal called
        called = True

    service = GovernedInvocationExecutionService(
        invocation_service=InvocationExecutionService(store=invocation_store),
        event_store=event_store,
        policy_evaluator=policy,
    )

    with pytest.raises(InvocationDenied, match="scope denied"):
        await service.invoke(
            binding=_binding(),
            run_id="run-1",
            node_run_id="node-run-1",
            attempt_id="attempt-1",
            effect_key="write:1",
            request={"value": 1},
            resolver=_resolver,
            executor=executor,
        )

    assert called is False
    events = await event_store.list_stream("workspace:ws-1")
    assert len(events) == 1
    assert events[0].type == "capability.invocation.policy_decision"
    assert events[0].payload["decision"] == "deny"
    assert events[0].attempt_id == "attempt-1"


@pytest.mark.asyncio
async def test_approval_policy_blocks_before_provider_execution() -> None:
    event_store = InMemoryEventStore()

    async def policy(
        _binding: Binding,
        _request: Any,
        _context: InvocationPolicyContext,
    ) -> PolicyVerdict:
        return PolicyVerdict(
            Decision.REQUIRE_APPROVAL,
            reason="human approval required",
            rule="irreversible-write",
        )

    service = GovernedInvocationExecutionService(
        invocation_service=InvocationExecutionService(store=InMemoryInvocationStore()),
        event_store=event_store,
        policy_evaluator=policy,
    )

    with pytest.raises(InvocationApprovalRequired, match="human approval required"):
        await service.invoke(
            binding=_binding(),
            run_id="run-1",
            node_run_id="node-run-1",
            attempt_id="attempt-1",
            effect_key="write:2",
            request={"value": 2},
            resolver=_resolver,
            executor=_executor,
        )

    events = await event_store.list_stream("workspace:ws-1")
    assert events[0].payload["decision"] == "require_approval"


@pytest.mark.asyncio
async def test_allowed_invocation_emits_causal_completion_event_and_policy_context() -> None:
    event_store = InMemoryEventStore()
    seen_context: InvocationPolicyContext | None = None

    async def policy(
        _binding: Binding,
        _request: Any,
        context: InvocationPolicyContext,
    ) -> PolicyVerdict:
        nonlocal seen_context
        seen_context = context
        return PolicyVerdict(Decision.ALLOW, reason="within scope", rule="workspace-write")

    service = GovernedInvocationExecutionService(
        invocation_service=InvocationExecutionService(store=InMemoryInvocationStore()),
        event_store=event_store,
        policy_evaluator=policy,
    )

    invocation = await service.invoke(
        binding=_binding(),
        run_id="run-1",
        node_run_id="node-run-1",
        attempt_id="attempt-1",
        effect_key="write:3",
        request={"value": 3},
        resolver=_resolver,
        executor=_executor,
    )

    assert seen_context == InvocationPolicyContext(
        run_id="run-1",
        node_run_id="node-run-1",
        attempt_id="attempt-1",
        effect_key="write:3",
    )
    events = await event_store.list_stream("workspace:ws-1")
    assert [event.type for event in events] == [
        "capability.invocation.policy_decision",
        "capability.invocation.completed",
    ]
    assert events[1].causation_id == events[0].event_id
    assert events[1].invocation_id == invocation.invocation_id
    assert events[1].payload["provider_name"] == "provider-a"


@pytest.mark.asyncio
async def test_provider_exception_emits_causal_unknown_outcome_event() -> None:
    event_store = InMemoryEventStore()

    async def policy(
        _binding: Binding,
        _request: Any,
        _context: InvocationPolicyContext,
    ) -> PolicyVerdict:
        return PolicyVerdict(Decision.ALLOW, reason="within scope", rule="workspace-write")

    async def failing_executor(_provider: _Provider, _request: Any) -> None:
        raise RuntimeError("provider response lost")

    service = GovernedInvocationExecutionService(
        invocation_service=InvocationExecutionService(store=InMemoryInvocationStore()),
        event_store=event_store,
        policy_evaluator=policy,
    )

    with pytest.raises(RuntimeError, match="provider response lost"):
        await service.invoke(
            binding=_binding(),
            run_id="run-1",
            node_run_id="node-run-1",
            attempt_id="attempt-1",
            effect_key="write:unknown",
            request={"value": 4},
            resolver=_resolver,
            executor=failing_executor,
        )

    events = await event_store.list_stream("workspace:ws-1")
    assert [event.type for event in events] == [
        "capability.invocation.policy_decision",
        "capability.invocation.unknown",
    ]
    assert events[1].causation_id == events[0].event_id
    assert events[1].invocation_id
    assert events[1].payload["provider_name"] == "provider-a"
    assert events[1].payload["status"] == "unknown"
    assert events[1].payload["error"] == "provider response lost"


@pytest.mark.asyncio
async def test_provider_cancellation_emits_causal_unknown_outcome_event() -> None:
    event_store = InMemoryEventStore()

    async def policy(
        _binding: Binding,
        _request: Any,
        _context: InvocationPolicyContext,
    ) -> PolicyVerdict:
        return PolicyVerdict(Decision.ALLOW, reason="within scope", rule="workspace-write")

    async def cancelled_executor(_provider: _Provider, _request: Any) -> None:
        raise asyncio.CancelledError

    service = GovernedInvocationExecutionService(
        invocation_service=InvocationExecutionService(store=InMemoryInvocationStore()),
        event_store=event_store,
        policy_evaluator=policy,
    )

    with pytest.raises(asyncio.CancelledError):
        await service.invoke(
            binding=_binding(),
            run_id="run-1",
            node_run_id="node-run-1",
            attempt_id="attempt-1",
            effect_key="write:cancelled",
            request={"value": 4},
            resolver=_resolver,
            executor=cancelled_executor,
        )

    events = await event_store.list_stream("workspace:ws-1")
    assert [event.type for event in events] == [
        "capability.invocation.policy_decision",
        "capability.invocation.unknown",
    ]
    assert events[1].causation_id == events[0].event_id
    assert events[1].invocation_id
    assert events[1].payload["provider_name"] == "provider-a"
    assert events[1].payload["status"] == "unknown"
    assert (
        events[1].payload["error"] == "provider invocation cancelled with unknown external outcome"
    )


@pytest.mark.asyncio
async def test_deduplicated_completed_effect_emits_one_completion_event() -> None:
    event_store = InMemoryEventStore()
    provider_calls = 0

    async def policy(
        _binding: Binding,
        _request: Any,
        _context: InvocationPolicyContext,
    ) -> PolicyVerdict:
        return PolicyVerdict(Decision.ALLOW, reason="within scope", rule="workspace-write")

    async def executor(_provider: _Provider, request: Any) -> dict[str, Any]:
        nonlocal provider_calls
        provider_calls += 1
        return {"committed": request}

    service = GovernedInvocationExecutionService(
        invocation_service=InvocationExecutionService(store=InMemoryInvocationStore()),
        event_store=event_store,
        policy_evaluator=policy,
    )

    first = await service.invoke(
        binding=_binding(),
        run_id="run-1",
        node_run_id="node-run-1",
        attempt_id="attempt-1",
        effect_key="write:dedupe",
        request={"value": 5},
        resolver=_resolver,
        executor=executor,
    )
    second = await service.invoke(
        binding=_binding(),
        run_id="run-1",
        node_run_id="node-run-1",
        attempt_id="attempt-2",
        effect_key="write:dedupe",
        request={"value": 5},
        resolver=_resolver,
        executor=executor,
    )

    assert second.invocation_id == first.invocation_id
    assert provider_calls == 1
    events = await event_store.list_stream("workspace:ws-1")
    completion_events = [
        event for event in events if event.type == "capability.invocation.completed"
    ]
    assert len(completion_events) == 1
    assert completion_events[0].invocation_id == first.invocation_id
