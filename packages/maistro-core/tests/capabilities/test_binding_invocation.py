from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from maistro.capabilities.binding import Binding, ResolvedBinding
from maistro.capabilities.binding_store import (
    BindingNotFound,
    BindingScopeDenied,
    InMemoryBindingStore,
)
from maistro.capabilities.effect_context import new_effect_context
from maistro.capabilities.governed_invocation import InvocationDenied
from maistro.capabilities.invocation import (
    EffectNotApplied,
    InMemoryInvocationStore,
    InvocationExecutionService,
    InvocationStatus,
    UnsafeEffectRetry,
)


@dataclass(frozen=True)
class _Provider:
    name: str = "provider-a"
    slot: str = "external_write"
    trust_tier: str = "trusted"


async def _resolver(binding: Binding) -> _Provider:
    assert binding.capability == "external_write"
    return _Provider()


@pytest.mark.asyncio
async def test_unconfigured_effect_context_denies_before_provider_call() -> None:
    effects = new_effect_context()
    binding = await effects.bindings.put(_binding())
    calls = 0

    async def execute(_provider: _Provider, _request: Any) -> None:
        nonlocal calls
        calls += 1

    with pytest.raises(InvocationDenied, match="policy unavailable"):
        await effects.invocations.invoke(
            binding=binding,
            run_id="run-unconfigured",
            node_run_id="node-unconfigured",
            attempt_id="attempt-unconfigured",
            effect_key="effect-unconfigured",
            request={"write": True},
            resolver=_resolver,
            executor=execute,
        )

    assert calls == 0
    events = await effects.event_store.list_stream("workspace:ws-1")
    assert events[-1].type == "capability.invocation.policy_decision"
    assert events[-1].payload["decision"] == "deny"
    assert events[-1].payload["rule"] == "invocation.unconfigured"


def _binding(*, provider_name: str = "") -> Binding:
    return Binding(
        binding_id="binding-1",
        workspace_id="ws-1",
        project_id="project-1",
        node_id="node-1",
        capability="external_write",
        provider_name=provider_name,
        config={"mode": "safe"},
        credential_refs=("credential-1",),
        policy_refs=("policy-1",),
    )


def test_resolved_binding_records_provider_and_rejects_pin_mismatch() -> None:
    provider = _Provider()
    resolved = ResolvedBinding.from_provider(_binding(), provider)

    assert resolved.binding_id == "binding-1"
    assert resolved.provider_name == "provider-a"
    assert resolved.provider_trust_tier == "trusted"
    assert resolved.config == {"mode": "safe"}
    assert resolved.credential_refs == ("credential-1",)
    assert resolved.policy_refs == ("policy-1",)

    with pytest.raises(ValueError, match="pins provider"):
        ResolvedBinding.from_provider(_binding(provider_name="provider-b"), provider)


@pytest.mark.asyncio
async def test_completed_effect_is_deduplicated_across_attempt_recovery() -> None:
    store = InMemoryInvocationStore()
    service = InvocationExecutionService(store=store)
    calls = 0

    async def execute(_provider: _Provider, request: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"committed": request}

    first = await service.invoke(
        binding=_binding(),
        run_id="run-1",
        node_run_id="node-run-1",
        attempt_id="attempt-1",
        effect_key="ticket:create:123",
        request={"title": "one"},
        resolver=_resolver,
        executor=execute,
    )
    replay = await service.invoke(
        binding=_binding(),
        run_id="run-1",
        node_run_id="node-run-1",
        attempt_id="attempt-2",
        effect_key="ticket:create:123",
        request={"title": "one"},
        resolver=_resolver,
        executor=execute,
    )

    assert calls == 1
    assert first.status is InvocationStatus.COMPLETED
    assert replay.invocation_id == first.invocation_id
    assert replay.attempt_id == "attempt-1"


@pytest.mark.asyncio
async def test_unknown_external_outcome_blocks_automatic_retry() -> None:
    store = InMemoryInvocationStore()
    service = InvocationExecutionService(store=store)
    calls = 0

    async def ambiguous(_provider: _Provider, _request: Any) -> None:
        nonlocal calls
        calls += 1
        raise ConnectionError("connection lost after dispatch")

    with pytest.raises(ConnectionError, match="connection lost"):
        await service.invoke(
            binding=_binding(),
            run_id="run-1",
            node_run_id="node-run-1",
            attempt_id="attempt-1",
            effect_key="payment:capture:456",
            request={"amount": 10},
            resolver=_resolver,
            executor=ambiguous,
        )

    history = await store.list_effect(
        run_id="run-1",
        node_run_id="node-run-1",
        binding_id="binding-1",
        effect_key="payment:capture:456",
    )
    assert history[-1].status is InvocationStatus.UNKNOWN

    with pytest.raises(UnsafeEffectRetry, match="manual/reconciliation evidence"):
        await service.invoke(
            binding=_binding(),
            run_id="run-1",
            node_run_id="node-run-1",
            attempt_id="attempt-2",
            effect_key="payment:capture:456",
            request={"amount": 10},
            resolver=_resolver,
            executor=ambiguous,
        )
    assert calls == 1


@pytest.mark.asyncio
async def test_proven_not_applied_effect_can_retry_as_new_invocation() -> None:
    store = InMemoryInvocationStore()
    service = InvocationExecutionService(store=store)
    calls = 0

    async def execute(_provider: _Provider, _request: Any) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise EffectNotApplied("provider rejected before commit")
        return "committed"

    with pytest.raises(EffectNotApplied, match="before commit"):
        await service.invoke(
            binding=_binding(),
            run_id="run-1",
            node_run_id="node-run-1",
            attempt_id="attempt-1",
            effect_key="issue:create:789",
            request={"title": "retryable"},
            resolver=_resolver,
            executor=execute,
        )

    second = await service.invoke(
        binding=_binding(),
        run_id="run-1",
        node_run_id="node-run-1",
        attempt_id="attempt-2",
        effect_key="issue:create:789",
        request={"title": "retryable"},
        resolver=_resolver,
        executor=execute,
    )
    history = await store.list_effect(
        run_id="run-1",
        node_run_id="node-run-1",
        binding_id="binding-1",
        effect_key="issue:create:789",
    )

    assert calls == 2
    assert [item.status for item in history] == [
        InvocationStatus.FAILED,
        InvocationStatus.COMPLETED,
    ]
    assert [item.attempt_id for item in history] == ["attempt-1", "attempt-2"]
    assert second.result == "committed"


# --- InMemoryBindingStore: identity and scope resolution (#55) -------------


@pytest.mark.asyncio
async def test_binding_identity_is_immutable_across_re_registration() -> None:
    store = InMemoryBindingStore()
    first = await store.put(_binding())

    # Re-registering the exact same definition is idempotent...
    again = await store.put(first)
    assert again == first

    # ...but a changed definition behind the same id is refused rather than
    # silently widening the authority the id already grants.
    changed = _binding(provider_name="provider-b")
    with pytest.raises(ValueError, match="immutable and already registered"):
        await store.put(changed)


@pytest.mark.asyncio
async def test_resolve_requires_every_scope_field() -> None:
    store = InMemoryBindingStore()
    await store.put(_binding())

    with pytest.raises(BindingScopeDenied, match="workspace_id is required"):
        await store.resolve(
            "binding-1",
            workspace_id="",
            project_id="project-1",
            node_id="node-1",
            capability="external_write",
        )


@pytest.mark.asyncio
async def test_revoked_binding_cannot_be_recreated_or_resolved() -> None:
    store = InMemoryBindingStore()
    binding = await store.put(_binding())
    await store.revoke(binding.binding_id)

    with pytest.raises(BindingNotFound, match="has been revoked"):
        await store.resolve(
            binding.binding_id,
            workspace_id="ws-1",
            project_id="project-1",
            node_id="node-1",
            capability="external_write",
        )
    with pytest.raises(BindingNotFound, match="has been revoked"):
        await store.put(binding)


@pytest.mark.asyncio
async def test_resolve_of_an_unregistered_binding_is_not_found() -> None:
    store = InMemoryBindingStore()

    with pytest.raises(BindingNotFound, match="'binding-404' is not registered"):
        await store.resolve(
            "binding-404",
            workspace_id="ws-1",
            project_id="project-1",
            node_id="node-1",
            capability="external_write",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"project_id": "project-2"}, "belongs to Project 'project-1'"),
        ({"node_id": "node-2"}, "is restricted to Node 'node-1'"),
        ({"capability": "external_read"}, "authorizes Capability 'external_write'"),
    ],
)
async def test_resolve_denies_each_scope_mismatch_by_name(
    overrides: dict[str, str], fragment: str
) -> None:
    store = InMemoryBindingStore()
    await store.put(_binding())

    scope = {
        "workspace_id": "ws-1",
        "project_id": "project-1",
        "node_id": "node-1",
        "capability": "external_write",
    } | overrides

    with pytest.raises(BindingScopeDenied, match=fragment):
        await store.resolve("binding-1", **scope)


@pytest.mark.asyncio
async def test_unrestricted_node_binding_resolves_for_any_node() -> None:
    store = InMemoryBindingStore()
    await store.put(_binding().model_copy(update={"node_id": ""}))

    resolved = await store.resolve(
        "binding-1",
        workspace_id="ws-1",
        project_id="project-1",
        node_id="any-node-at-all",
        capability="external_write",
    )
    assert resolved.binding_id == "binding-1"
