"""Composition root for the canonical governed capability-effect boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from maistro.capabilities.binding import Binding
from maistro.capabilities.binding_store import BindingStore, InMemoryBindingStore
from maistro.capabilities.credential_routing import CredentialRouting
from maistro.capabilities.governed_invocation import (
    GovernedInvocationExecutionService,
    InvocationPolicyContext,
    PolicyEvaluator,
)
from maistro.capabilities.invocation import (
    InMemoryInvocationStore,
    InvocationExecutionService,
    InvocationQuota,
    InvocationStore,
)
from maistro.credentials.router import CredentialRouter
from maistro.events.envelope import EventStore, InMemoryEventStore
from maistro.policy.types import Decision, PolicyVerdict


async def _m1_binding_authorized_policy(
    binding: Binding,
    request: Any,
    context: InvocationPolicyContext,
) -> PolicyVerdict:
    del binding, request, context
    return PolicyVerdict(
        Decision.ALLOW,
        reason="canonical Binding scope resolved before provider invocation",
        rule="m1.binding-scope",
    )


@dataclass(frozen=True)
class CapabilityEffectContext:
    """Wired canonical Binding, Invocation, and quota authorities."""

    bindings: BindingStore
    invocations: GovernedInvocationExecutionService
    invocation_store: InvocationStore
    event_store: EventStore
    credentials: CredentialRouter = field(default_factory=CredentialRouter)

    def credential_routing(self) -> CredentialRouting:
        return CredentialRouting(self.credentials)


def new_in_memory_effect_context(
    *,
    policy_evaluator: PolicyEvaluator | None = None,
    credentials: CredentialRouter | None = None,
    quota: InvocationQuota | None = None,
    bindings: BindingStore | None = None,
    invocation_store: InvocationStore | None = None,
    event_store: EventStore | None = None,
) -> CapabilityEffectContext:
    """Compose the canonical effect seam from backend-selected authorities.

    The historical name is retained for compatibility. Production may supply
    durable stores and quota; omitted collaborators intentionally select the
    isolated in-memory implementations used by tests and ephemeral deployments.
    """

    binding_store = bindings or InMemoryBindingStore()
    inv_store = invocation_store or InMemoryInvocationStore()
    events = event_store or InMemoryEventStore()
    invocation_service = InvocationExecutionService(store=inv_store, quota=quota)
    governed = GovernedInvocationExecutionService(
        invocation_service=invocation_service,
        event_store=events,
        policy_evaluator=policy_evaluator or _m1_binding_authorized_policy,
    )
    return CapabilityEffectContext(
        bindings=binding_store,
        invocations=governed,
        invocation_store=inv_store,
        event_store=events,
        credentials=credentials or CredentialRouter(),
    )


@lru_cache(maxsize=1)
def default_effect_context() -> CapabilityEffectContext:
    """Ephemeral default; production Container constructs its context explicitly."""

    return new_in_memory_effect_context()


__all__ = [
    "CapabilityEffectContext",
    "default_effect_context",
    "new_in_memory_effect_context",
]
