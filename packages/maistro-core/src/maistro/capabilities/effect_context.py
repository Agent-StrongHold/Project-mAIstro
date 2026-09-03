"""Composition root for the canonical governed capability-effect boundary.

This module owns no dispatch semantics. It composes the accepted Binding and
Invocation authorities so production consumers can cross one governed seam
instead of constructing private executors. The process default is intentionally
empty of Bindings: an unconfigured consumer fails closed rather than obtaining
a provider merely because one happens to be registered elsewhere.
"""

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
    """M1 baseline after canonical Binding scope resolution has succeeded.

    Binding authorization is evaluated by ``BindingStore.resolve`` before this
    policy boundary. M2 may inject stronger policy semantics here; M1 does not
    manufacture a second permission system just to make governed Invocation
    reachable.
    """

    del binding, request, context
    return PolicyVerdict(
        Decision.ALLOW,
        reason="canonical Binding scope resolved before provider invocation",
        rule="m1.binding-scope",
    )


@dataclass(frozen=True)
class CapabilityEffectContext:
    """Wired canonical Binding and Invocation authorities for effect consumers."""

    bindings: BindingStore
    invocations: GovernedInvocationExecutionService
    invocation_store: InvocationStore
    event_store: EventStore
    credentials: CredentialRouter = field(default_factory=CredentialRouter)

    def credential_routing(self) -> CredentialRouting:
        """Credential routing for this context's Provider selection seam (#58).

        Consumers wrap their slot-specific resolver/executor pair with this, so
        credential selection is scoped by the resolved Binding and rotation
        reacts to real Invocation outcomes. The default router starts empty —
        absence of an authorized credential is a hard refusal, never a silent
        fallback to some other scope's key.
        """

        return CredentialRouting(self.credentials)


def new_in_memory_effect_context(
    *,
    policy_evaluator: PolicyEvaluator | None = None,
    credentials: CredentialRouter | None = None,
) -> CapabilityEffectContext:
    """Build an isolated canonical effect context for local/runtime composition.

    ``credentials`` supplies the scoped credential pool for Provider selection
    (#58); omitted, the router exists but holds no credentials, so routed
    acquisitions fail closed until one is registered in the requesting scope.
    """

    binding_store = InMemoryBindingStore()
    invocation_store = InMemoryInvocationStore()
    event_store = InMemoryEventStore()
    invocation_service = InvocationExecutionService(store=invocation_store)
    governed = GovernedInvocationExecutionService(
        invocation_service=invocation_service,
        event_store=event_store,
        policy_evaluator=policy_evaluator or _m1_binding_authorized_policy,
    )
    return CapabilityEffectContext(
        bindings=binding_store,
        invocations=governed,
        invocation_store=invocation_store,
        event_store=event_store,
        credentials=credentials or CredentialRouter(),
    )


@lru_cache(maxsize=1)
def default_effect_context() -> CapabilityEffectContext:
    """Process-wide canonical context used by registry-constructed effect nodes.

    The shared instance matters: a Node must resolve the same Binding authority
    an application populated, and retries must consult the same Invocation
    ledger. No default Binding is created here; absence remains a hard refusal.
    """

    return new_in_memory_effect_context()


__all__ = [
    "CapabilityEffectContext",
    "default_effect_context",
    "new_in_memory_effect_context",
]
