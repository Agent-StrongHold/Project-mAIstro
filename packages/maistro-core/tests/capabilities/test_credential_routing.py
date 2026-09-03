"""Credential routing through the governed Invocation path (#58 / M1-D4).

Proves the acceptance shape of the move: real Provider/Invocation paths reach
credential-pool logic; authorized Workspace/Project/Binding scope constrains
credential use; rotation reacts to actual provider outcomes recorded as
Invocation results; and secrets never enter Invocation or event persistence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest

from maistro.capabilities.binding import Binding, ResolvedBinding, ResolvedCapabilityProvider
from maistro.capabilities.credential_routing import (
    CredentialBackedProvider,
    CredentialConsumer,
    CredentialRouting,
)
from maistro.capabilities.effect_context import (
    CapabilityEffectContext,
    new_in_memory_effect_context,
)
from maistro.capabilities.invocation import (
    CapabilityUnavailable,
    EffectNotApplied,
    InvocationStatus,
)
from maistro.credentials.router import CredentialRouter, CredentialScopeError
from maistro.credentials.types import CredentialRecord

WS = "ws-1"
PROJECT = "project-1"
CAPABILITY = "external_write"
CREDENTIAL_PROVIDER = "openai"


class _HttpRejection(EffectNotApplied):
    """Provider rejection proven to precede any external effect."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response = type("Resp", (), {"status_code": status_code, "headers": {}})


@dataclass(frozen=True)
class _CredentialUsingProvider:
    """A resolved capability provider that authenticates from the pool."""

    name: str = "provider-a"
    slot: str = CAPABILITY
    trust_tier: str = "trusted"
    credential_provider: str = CREDENTIAL_PROVIDER


@dataclass(frozen=True)
class _BareProvider:
    name: str = "provider-bare"
    slot: str = CAPABILITY
    trust_tier: str = "trusted"


def _record(key_id: str) -> CredentialRecord:
    return CredentialRecord(
        key_id=key_id, provider=CREDENTIAL_PROVIDER, api_key=f"sk-secret-{key_id}"
    )


def _binding(*, credential_refs: tuple[str, ...] = ("key-a", "key-b")) -> Binding:
    return Binding(
        binding_id="binding-1",
        workspace_id=WS,
        project_id=PROJECT,
        node_id="node-1",
        capability=CAPABILITY,
        credential_refs=credential_refs,
    )


def _context_with_pool(*, keys: tuple[str, ...] = ("key-a", "key-b")) -> CapabilityEffectContext:
    context = new_in_memory_effect_context()
    for key in keys:
        context.credentials.add(workspace_id=WS, project_id=PROJECT, record=_record(key))
    return context


async def _resolve_provider(binding: Binding) -> ResolvedCapabilityProvider:
    assert binding.capability == CAPABILITY
    return _CredentialUsingProvider()


async def _invoke(context: CapabilityEffectContext, *, executor, attempt_id: str, effect_key: str):
    routing = context.credential_routing()
    return await context.invocations.invoke(
        binding=_binding(),
        run_id="run-1",
        node_run_id="node-run-1",
        attempt_id=attempt_id,
        effect_key=effect_key,
        request={"title": "ticket"},
        resolver=routing.resolver(_resolve_provider),
        executor=routing.executor(executor),
    )


class TestRoutedInvocation:
    async def test_governed_invocation_selects_a_scoped_credential(self):
        context = _context_with_pool()
        seen: list[str] = []

        async def executor(provider: Any, request: Any) -> dict[str, Any]:
            assert isinstance(provider, CredentialBackedProvider)
            seen.append(provider.credential.api_key)
            return {"committed": True}

        invocation = await _invoke(
            context, executor=executor, attempt_id="attempt-1", effect_key="ticket:create:1"
        )

        assert invocation.status is InvocationStatus.COMPLETED
        assert invocation.binding.provider_name == "provider-a"
        assert invocation.binding.credential_refs == ("key-a", "key-b")
        assert seen == ["sk-secret-key-a"]

        stats = context.credentials.stats(
            workspace_id=WS, project_id=PROJECT, provider=CREDENTIAL_PROVIDER
        )
        assert stats is not None
        assert stats.total_use_count == 1  # outcome recorded on the real path

    async def test_rotation_reacts_to_real_invocation_outcomes(self):
        context = _context_with_pool()
        calls: list[str] = []

        async def executor(provider: Any, request: Any) -> dict[str, Any]:
            credential = provider.credential
            calls.append(credential.key_id)
            if credential.key_id == "key-a":
                raise _HttpRejection("Rate limit exceeded", 429)
            return {"committed": True}

        first_failed = False
        try:
            await _invoke(
                context, executor=executor, attempt_id="attempt-1", effect_key="ticket:create:2"
            )
        except _HttpRejection:
            first_failed = True
        second = await _invoke(
            context, executor=executor, attempt_id="attempt-2", effect_key="ticket:create:2"
        )

        # Attempt 1 failed having proven no effect was applied; attempt 2 is a
        # new Invocation whose acquisition rotated off the cooled-down key.
        assert first_failed
        assert second.status is InvocationStatus.COMPLETED
        assert calls == ["key-a", "key-b"]

        stats = context.credentials.stats(
            workspace_id=WS, project_id=PROJECT, provider=CREDENTIAL_PROVIDER
        )
        assert stats is not None
        by_key = {row["key_id"]: row for row in stats.per_key}
        assert by_key["key-a"]["is_available"] is False  # cooling down from the 429
        assert by_key["key-b"]["use_count"] == 1

    async def test_exhausted_pool_surfaces_as_capability_unavailable(self):
        context = _context_with_pool()

        async def executor(provider: Any, request: Any) -> dict[str, Any]:
            raise _HttpRejection("Rate limit exceeded", 429)

        for attempt in ("attempt-1", "attempt-2"):
            with pytest.raises(_HttpRejection):
                await _invoke(context, executor=executor, attempt_id=attempt, effect_key="ticket:3")

        with pytest.raises(CapabilityUnavailable, match="credential pool exhausted"):
            await _invoke(
                context, executor=executor, attempt_id="attempt-3", effect_key="ticket:3"
            )


class TestScopedAuthorization:
    async def test_binding_without_credential_refs_fails_closed(self):
        context = _context_with_pool()

        async def executor(provider: Any, request: Any) -> dict[str, Any]:
            raise AssertionError("must not execute")

        routing = context.credential_routing()
        with pytest.raises(CredentialScopeError, match="credential_refs is empty"):
            await context.invocations.invoke(
                binding=_binding(credential_refs=()),
                run_id="run-1",
                node_run_id="node-run-1",
                attempt_id="attempt-1",
                effect_key="ticket:4",
                request={"title": "ticket"},
                resolver=routing.resolver(_resolve_provider),
                executor=executor,
            )

    async def test_binding_cannot_use_creds_its_refs_do_not_name(self):
        context = _context_with_pool()

        async def executor(provider: Any, request: Any) -> dict[str, Any]:
            raise AssertionError("must not execute")

        routing = context.credential_routing()
        with pytest.raises(CredentialScopeError, match="authorizes credentials"):
            await context.invocations.invoke(
                binding=_binding(credential_refs=("key-c",)),
                run_id="run-1",
                node_run_id="node-run-1",
                attempt_id="attempt-1",
                effect_key="ticket:5",
                request={"title": "ticket"},
                resolver=routing.resolver(_resolve_provider),
                executor=executor,
            )

    async def test_foreign_workspace_scope_is_denied(self):
        context = _context_with_pool()
        foreign = _binding().model_copy(update={"workspace_id": "ws-2"})

        async def executor(provider: Any, request: Any) -> dict[str, Any]:
            raise AssertionError("must not execute")

        routing = context.credential_routing()
        with pytest.raises(CredentialScopeError, match="no credentials configured"):
            await context.invocations.invoke(
                binding=foreign,
                run_id="run-1",
                node_run_id="node-run-1",
                attempt_id="attempt-1",
                effect_key="ticket:6",
                request={"title": "ticket"},
                resolver=routing.resolver(_resolve_provider),
                executor=executor,
            )

    async def test_provider_without_credential_surface_is_unavailable(self):
        context = _context_with_pool()

        async def bare_resolver(binding: Binding) -> ResolvedCapabilityProvider:
            return _BareProvider()

        async def executor(provider: Any, request: Any) -> dict[str, Any]:
            raise AssertionError("must not execute")

        routing = context.credential_routing()
        with pytest.raises(CapabilityUnavailable, match="credential_provider surface"):
            await context.invocations.invoke(
                binding=_binding(),
                run_id="run-1",
                node_run_id="node-run-1",
                attempt_id="attempt-1",
                effect_key="ticket:7",
                request={"title": "ticket"},
                resolver=routing.resolver(bare_resolver),
                executor=executor,
            )


class TestSecretContainment:
    async def test_secrets_never_enter_invocation_or_event_records(self):
        context = _context_with_pool()

        async def executor(provider: Any, request: Any) -> dict[str, Any]:
            if provider.credential.key_id == "key-a":
                raise _HttpRejection("Rate limit exceeded", 429)
            return {"committed": True}

        with pytest.raises(_HttpRejection):
            await _invoke(context, executor=executor, attempt_id="attempt-1", effect_key="ticket:8")
        await _invoke(context, executor=executor, attempt_id="attempt-2", effect_key="ticket:8")

        secrets = ["sk-secret-key-a", "sk-secret-key-b"]

        history = await context.invocation_store.list_effect(
            run_id="run-1",
            node_run_id="node-run-1",
            binding_id="binding-1",
            effect_key="ticket:8",
        )
        assert len(history) == 2
        for invocation in history:
            persisted = json.dumps(invocation.model_dump(mode="json"))
            for secret in secrets:
                assert secret not in persisted

        events = json.dumps(
            [vars(env) for env in getattr(context.event_store, "_events_by_id", {}).values()],
            default=str,
        )
        for secret in secrets:
            assert secret not in events

    def test_provider_repr_shows_key_id_only(self):
        provider = CredentialBackedProvider(
            base=_CredentialUsingProvider(),
            credential=_record("key-a"),
            workspace_id=WS,
            project_id=PROJECT,
        )

        rendered = repr(provider)

        assert "key-a" in rendered
        assert "sk-secret-key-a" not in rendered

    def test_resolved_binding_from_routed_provider_carries_no_secret(self):
        provider = CredentialBackedProvider(
            base=_CredentialUsingProvider(),
            credential=_record("key-a"),
            workspace_id=WS,
            project_id=PROJECT,
        )

        resolved = ResolvedBinding.from_provider(_binding(), provider)

        assert resolved.provider_name == "provider-a"
        assert resolved.provider_trust_tier == "trusted"
        assert "credential" not in ResolvedBinding.model_fields


class TestCompositionSurface:
    def test_default_context_router_starts_empty_and_fails_closed(self):
        context = new_in_memory_effect_context()

        stats = context.credentials.stats(
            workspace_id=WS, project_id=PROJECT, provider=CREDENTIAL_PROVIDER
        )

        assert stats is None
        assert isinstance(context.credential_routing(), CredentialRouting)

    async def test_router_is_shared_with_the_context_it_was_built_with(self):
        router = CredentialRouter()
        router.add(workspace_id=WS, project_id=PROJECT, record=_record("key-a"))
        context = new_in_memory_effect_context(credentials=router)

        acquired = await context.credentials.acquire(
            workspace_id=WS,
            project_id=PROJECT,
            provider=CREDENTIAL_PROVIDER,
            credential_refs=("key-a",),
        )

        assert acquired.key_id == "key-a"
