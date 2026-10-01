"""Composition root for the canonical governed capability-effect boundary.

This module owns no dispatch semantics. It composes the accepted Binding and
Invocation authorities so production consumers can cross one governed seam
instead of constructing private executors. The process default is intentionally
empty of Bindings: an unconfigured consumer fails closed rather than obtaining
a provider merely because one happens to be registered elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from maistro.capabilities.approval_store import ApprovalStore
from maistro.capabilities.binding import Binding
from maistro.capabilities.binding_store import (
    InMemoryBindingStore,
    RevocableBindingStore,
)
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
from maistro.quota.recorder import CanonicalInvocationUsageRecorder
from maistro.quota.usage_log import InMemoryUsageLog, get_default_usage_log


async def binding_scope_policy(
    binding: Binding,
    request: Any,
    context: InvocationPolicyContext,
) -> PolicyVerdict:
    """Explicit M1 baseline after canonical Binding scope resolution.

    Binding authorization is evaluated by ``BindingStore.resolve`` before this
    policy boundary. This evaluator is suitable only for a composition root
    that deliberately chooses the M1 baseline; it is never installed by
    ``new_effect_context`` implicitly.

    It also carries the legacy-tool effect floor: legacy workflow tools are
    still compatibility providers, but their actual calls must not inherit the
    workflow admission approval. A binding marked destructive/mutating
    therefore gets its own governed decision.
    """

    del request, context
    if binding.capability.startswith("legacy_tool:") and binding.config.get("effect") in {
        "mutate",
        "destroy",
    }:
        return PolicyVerdict(
            Decision.REQUIRE_APPROVAL,
            reason="legacy workflow effect requires independent approval",
            rule="m1.legacy-tool-effect",
        )
    return PolicyVerdict(
        Decision.ALLOW,
        reason="canonical Binding scope resolved before provider invocation",
        rule="m1.binding-scope",
    )


async def _unconfigured_policy(
    binding: Binding,
    request: Any,
    context: InvocationPolicyContext,
) -> PolicyVerdict:
    """Deny contexts whose application has not supplied an effect policy."""

    del binding, request, context
    return PolicyVerdict(
        Decision.DENY,
        reason="capability invocation policy unavailable",
        rule="invocation.unconfigured",
    )


@dataclass(frozen=True)
class CapabilityEffectContext:
    """Wired canonical Binding and Invocation authorities for effect consumers."""

    bindings: RevocableBindingStore
    invocations: GovernedInvocationExecutionService
    invocation_store: InvocationStore
    event_store: EventStore
    approval_store: ApprovalStore | None = None
    # Budget admission (reserve/observe) lives on the Invocation service. This
    # field is the same object, exposed so composition tests can see it.
    quota: InvocationQuota | None = None
    usage_log: InMemoryUsageLog = field(default_factory=get_default_usage_log)
    credentials: CredentialRouter = field(default_factory=CredentialRouter)

    def with_policy_evaluator(self, policy_evaluator: PolicyEvaluator) -> CapabilityEffectContext:
        """Narrow policy without creating competing Binding or Invocation stores."""
        return replace(
            self,
            invocations=self.invocations.with_policy_evaluator(policy_evaluator),
        )

    def credential_routing(self) -> CredentialRouting:
        """Credential routing for this context's Provider selection seam (#58).

        Consumers wrap their slot-specific resolver/executor pair with this, so
        credential selection is scoped by the resolved Binding and rotation
        reacts to real Invocation outcomes. The default router starts empty —
        absence of an authorized credential is a hard refusal, never a silent
        fallback to some other scope's key.
        """

        return CredentialRouting(self.credentials)


def new_effect_context(
    *,
    invocation_store: InvocationStore | None = None,
    binding_store: RevocableBindingStore | None = None,
    event_store: EventStore | None = None,
    approval_store: ApprovalStore | None = None,
    policy_evaluator: PolicyEvaluator | None = None,
    credentials: CredentialRouter | None = None,
    quota: InvocationQuota | None = None,
    usage_log: InMemoryUsageLog | None = None,
    quota_tracker: Any | None = None,
) -> CapabilityEffectContext:
    """Compose one canonical effect authority from caller-selected stores.

    ``invocation_store`` selects the canonical effect ledger; ephemeral
    composition defaults to the in-memory store while durable containers pass
    the SQLite/PostgreSQL capability Invocation stores. Production uses this
    constructor with stores selected by the Container's configured persistence
    backend; tests/local ephemeral composition can use
    :func:`new_in_memory_effect_context`. Keeping the service construction here
    means durability changes storage lifetime only; it cannot create a second
    policy or Invocation execution path.

    Omitted binding and event stores stay in memory so a caller that only
    selects an Invocation ledger does not silently gain a second durable
    authority. The Container passes the backend-selected stores explicitly.
    ``quota`` is the budget door and ``quota_tracker``/``usage_log`` are the
    usage ledger; both attach to this same Invocation service.
    """

    selected_bindings = binding_store or InMemoryBindingStore()
    store = invocation_store or InMemoryInvocationStore()
    events = event_store or InMemoryEventStore()
    selected_usage_log = usage_log or get_default_usage_log()
    usage_recorder = CanonicalInvocationUsageRecorder(selected_usage_log, quota_tracker)
    invocation_service = InvocationExecutionService(
        store=store,
        quota=quota,
        on_completed=usage_recorder.record,
    )
    governed = GovernedInvocationExecutionService(
        invocation_service=invocation_service,
        event_store=events,
        # Omitted policy is an unavailable dependency, not an authorization
        # decision. Application composition must opt into a real evaluator.
        policy_evaluator=policy_evaluator or _unconfigured_policy,
        approval_store=approval_store,
    )
    return CapabilityEffectContext(
        bindings=selected_bindings,
        invocations=governed,
        invocation_store=store,
        event_store=events,
        approval_store=approval_store,
        quota=quota,
        usage_log=selected_usage_log,
        credentials=credentials or CredentialRouter(),
    )


#: Published Container contexts, outermost first. A list rather than one slot
#: because containers nest: a test or an embedder can build a second Container
#: inside the lifetime of the first, and closing the inner one must hand the
#: default back to the outer rather than discard it. With a single slot, the
#: inner close left the process with no published context at all, so every
#: later registry-constructed node -- the bare `RunConsumer` fallback among
#: them -- got a fresh empty context and failed Binding resolution while a
#: perfectly usable Container was still open (Codex, #1362).
_published_contexts: list[CapabilityEffectContext] = []

#: The unpublished fallback, cached so nodes do not each get a private ledger.
_ephemeral_context: CapabilityEffectContext | None = None


def configure_default_effect_context(context: CapabilityEffectContext) -> None:
    """Publish a Container-owned context as the process default.

    Re-publishing a context already on the stack moves it to the top rather
    than recording it twice, so a later release cannot leave a stale duplicate
    behind it.
    """

    _drop_published(context)
    _published_contexts.append(context)


def release_default_effect_context(context: CapabilityEffectContext) -> None:
    """Withdraw one Container's context when that Container closes.

    Removes this context wherever it sits, so containers that close out of
    order still leave the remaining published contexts in their original
    relative order. The default becomes whichever is then outermost-last --
    not `None`, unless this was the only one.
    """

    _drop_published(context)


def _drop_published(context: CapabilityEffectContext) -> None:
    """Remove a context by identity; equality would match a distinct twin."""

    for index, published in enumerate(_published_contexts):
        if published is context:
            del _published_contexts[index]
            return


def default_effect_context() -> CapabilityEffectContext:
    """Process-wide canonical context used by registry-constructed effect nodes.

    When a Container has published its context, this returns that exact
    instance -- the innermost still-open one. Otherwise one ephemeral context
    is cached so nodes do not each receive a private ledger. No default
    Binding is created; absence remains a hard refusal.
    """

    if _published_contexts:
        return _published_contexts[-1]
    global _ephemeral_context
    if _ephemeral_context is None:
        # This named composition root deliberately selects the narrow scope
        # policy; unnamed contexts stay read-only until an application
        # supplies one.
        _ephemeral_context = new_effect_context(policy_evaluator=binding_scope_policy)
    return _ephemeral_context


def _clear_default_effect_context() -> None:
    global _ephemeral_context
    _published_contexts.clear()
    _ephemeral_context = None


# Tests and fixtures still call the lru_cache-style clearer.
default_effect_context.cache_clear = _clear_default_effect_context  # type: ignore[attr-defined]


new_in_memory_effect_context = new_effect_context


async def new_sqlite_effect_context(connection: Any) -> CapabilityEffectContext:
    """Compose durable effect stores on one SQLite connection.

    This is the same ``new_effect_context`` door with backend-selected stores.
    It does not construct a second Invocation service.
    """

    from maistro.capabilities.approval_store import SqliteApprovalStore
    from maistro.capabilities.binding_store import SqliteBindingStore
    from maistro.capabilities.invocation_store import SqliteInvocationStore
    from maistro.events.envelope import SqliteEventStore

    bindings = SqliteBindingStore(connection)
    invocations = SqliteInvocationStore(connection)
    approvals = SqliteApprovalStore(connection)
    events = SqliteEventStore(connection)
    await bindings.ensure_schema()
    await invocations.ensure_schema()
    await approvals.ensure_schema()
    await events.ensure_schema()
    return new_effect_context(
        binding_store=bindings,
        invocation_store=invocations,
        approval_store=approvals,
        event_store=events,
        # A named composition root selects the narrow scope policy; bare
        # contexts stay read-only until an application supplies one.
        policy_evaluator=binding_scope_policy,
    )


__all__ = [
    "CapabilityEffectContext",
    "binding_scope_policy",
    "configure_default_effect_context",
    "default_effect_context",
    "new_effect_context",
    "new_in_memory_effect_context",
    "new_sqlite_effect_context",
    "release_default_effect_context",
]
