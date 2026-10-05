"""Host-side composition seam for the extension contract (#950).

The host runtime — never extension code — owns the authorities this module
composes: the governed effect authorities (Binding, provider resolver and
executor, policy), the granted service instances, the configuration values,
and the progress event sink. :class:`ExtensionHost` turns those authorities
into :class:`ExtensionContext` objects whose every seam is already narrowed to
one extension's descriptor.

This module is a context factory and lifecycle driver. It is not a scheduler,
run store, or execution authority: physical execution truth remains owned by
the canonical ``Graph → Run → NodeRun → Attempt`` chain, and the host runtime
that drives extensions through it keeps calling ``AttemptExecutionService``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from maistro.events.envelope import EventEnvelope, EventStore
from maistro.extensions.context import (
    EffectDispatcher,
    EffectReceipt,
    ExtensionCancellation,
    ExtensionConfigView,
    ExtensionContext,
    UngrantedProgressReporter,
)
from maistro.extensions.errors import EffectNotDeclared, ScopeMismatch
from maistro.extensions.identity import ExtensionDescriptor, InvocationScope
from maistro.extensions.lifecycle import (
    run_activation,
    run_deactivation,
    run_invocation,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    # The governed capability authorities are annotation-only here, and the
    # import must stay that way: any `maistro.capabilities` import executes
    # that package's __init__, which pulls the credential plane (and its
    # cryptography dependency) into every `import maistro`. The auth module's
    # fail-closed degradation depends on cryptography staying optional at
    # import time. Host composition code that builds routes imports the real
    # types itself — it is host-side and already has the authorities loaded.
    from maistro.capabilities.binding import Binding
    from maistro.capabilities.governed_invocation import GovernedInvocationExecutionService
    from maistro.capabilities.invocation import (
        ProviderExecutor,
        ProviderResolver,
        UsageExtractor,
    )

PROGRESS_EVENT_TYPE = "extension.progress"
EFFECT_EVENT_TYPE = "extension.effect.invoked"


@runtime_checkable
class EffectRoute(Protocol):
    """The host-side route for one declared effect across the governed seam."""

    async def dispatch(self, *, scope: InvocationScope, request: Any) -> EffectReceipt: ...


class GovernedEffectRoute:
    """One declared effect routed through ``GovernedInvocationExecutionService``.

    This is the reference wiring of the canonical
    ``Capability → Provider → Binding → Invocation`` path for extensions: the
    Binding is host-resolved authorization, the resolver and executor are
    host-owned provider machinery, and the resulting Invocation row carries
    the canonical run/node-run/attempt correlation. The governed service
    itself appends the canonical policy and terminal events; extension
    attribution (who triggered this effect) is the host's job — see
    ``ExtensionHost._record_effect_provenance``.
    """

    def __init__(
        self,
        *,
        effect_key: str,
        binding: Binding,
        invocations: GovernedInvocationExecutionService,
        resolver: ProviderResolver,
        executor: ProviderExecutor,
        usage_from: UsageExtractor | None = None,
    ) -> None:
        self._effect_key = effect_key
        self._binding = binding
        self._invocations = invocations
        self._resolver = resolver
        self._executor = executor
        self._usage_from = usage_from

    async def dispatch(self, *, scope: InvocationScope, request: Any) -> EffectReceipt:
        if not scope.in_attempt:
            raise EffectNotDeclared(
                f"effect {self._effect_key!r} cannot dispatch outside an Attempt: "
                "governed Invocations require canonical run/node-run/attempt correlation"
            )
        if scope.workspace_id != self._binding.workspace_id:
            # A route resolved for one workspace must never spend another
            # workspace's binding: the governed service derives the Invocation
            # and its policy events from the binding, while provenance follows
            # the scope, so a mismatched pair would split authority and audit
            # trail across tenants.
            raise ScopeMismatch(
                f"effect {self._effect_key!r} cannot dispatch: invocation scope "
                f"workspace {scope.workspace_id!r} does not match binding "
                f"workspace {self._binding.workspace_id!r}"
            )
        invocation = await self._invocations.invoke(
            binding=self._binding,
            run_id=scope.run_id,
            node_run_id=scope.node_run_id,
            attempt_id=scope.attempt_id,
            effect_key=self._effect_key,
            request=request,
            resolver=self._resolver,
            executor=self._executor,
            usage_from=self._usage_from,
        )
        return EffectReceipt(
            invocation_id=invocation.invocation_id,
            binding_id=invocation.binding.binding_id,
            capability=invocation.binding.capability,
            effect_key=self._effect_key,
            status=invocation.status.value,
            result=invocation.result,
        )


@runtime_checkable
class ProgressSink(Protocol):
    """The host-installed destination for one extension's progress reports."""

    async def report(self, progress: Any) -> None: ...


class _ScopedProgress:
    """Internal (progress, invoking-context) pair passed to the sink."""

    __slots__ = ("context", "progress")

    def __init__(self, *, progress: Any, context: ExtensionContext) -> None:
        self.progress = progress
        self.context = context


class EventStoreProgressSink:
    """Append progress reports to the canonical workspace event stream.

    Each report becomes an ``extension.progress`` envelope correlated to the
    invoking Attempt, with the extension identity recorded in the canonical
    ``provenance`` field. The sink is host-side: an extension reports through
    its context hook and never touches the event store itself.

    M1 product-local projection: Event
    """

    def __init__(self, events: EventStore) -> None:
        self._events = events

    async def report(self, bound: _ScopedProgress) -> None:
        context = bound.context
        progress = bound.progress
        correlation = context.scope.correlation
        await self._events.append(
            EventEnvelope(
                type=PROGRESS_EVENT_TYPE,
                workspace_id=correlation["workspace_id"],
                run_id=correlation["run_id"],
                node_run_id=correlation["node_run_id"],
                attempt_id=correlation["attempt_id"],
                correlation_id=correlation["run_id"],
                source="maistro.extensions",
                provenance=dict(context.identity.provenance),
                payload={
                    "extension_id": context.identity.extension_id,
                    "message": progress.message,
                    "percent": progress.percent,
                },
            )
        )


class BoundProgressReporter:
    """The :class:`ProgressReporter` one invocation actually receives.

    Carries the invoking context to the sink so the sink can correlate the
    report without the extension ever touching the sink or its store.
    """

    __slots__ = ("_context", "_sink")

    def __init__(self, *, sink: ProgressSink, context: ExtensionContext) -> None:
        self._sink = sink
        self._context = context

    async def report(self, progress: Any) -> None:
        bound = _ScopedProgress(progress=progress, context=self._context)
        await self._sink.report(bound)


class ExtensionHost:
    """Compose authorities into narrowed contexts and drive lifecycle hooks.

    The host is constructed once per extension per scope with everything the
    extension may reach: declared configuration values, granted service
    instances, routed effects, and the progress sink. Composition itself is
    least-authority: grants the descriptor does not declare are dropped here,
    before any context exists, so undeclared secrets and objects never travel
    with the context at all — not even behind the context's private storage.
    """

    def __init__(
        self,
        *,
        descriptor: ExtensionDescriptor,
        config_values: Mapping[str, Any] | None = None,
        service_grants: Mapping[str, object] | None = None,
        effect_routes: Mapping[str, EffectRoute] | None = None,
        progress_sink: ProgressSink | None = None,
        events: EventStore | None = None,
    ) -> None:
        self.descriptor = descriptor
        # Least-authority at composition: keep only descriptor-declared
        # entries, so undeclared host-side values (secrets, live objects) are
        # discarded before they could reach any context's storage.
        self._config_values = {
            key: value
            for key, value in (config_values or {}).items()
            if key in descriptor.config_keys
        }
        self._service_grants = {
            key: service
            for key, service in (service_grants or {}).items()
            if key in descriptor.services
        }
        self._effect_routes = dict(effect_routes or {})
        self._progress_sink = progress_sink
        # Attribution authority: when the host supplies the canonical event
        # store, every dispatched effect and progress report lands there with
        # the extension identity in the envelope's provenance field.
        self._events = events

    def activation_context(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        cancellation: ExtensionCancellation | None = None,
    ) -> ExtensionContext:
        """Build the once-per-scope activation context (no Attempt bound)."""
        scope = InvocationScope(workspace_id=workspace_id, agent_id=agent_id)
        return self._build_context(scope, cancellation)

    def invocation_context(
        self,
        scope: InvocationScope,
        *,
        cancellation: ExtensionCancellation | None = None,
    ) -> ExtensionContext:
        """Build the per-invocation context bound to a canonical Attempt."""
        if not scope.in_attempt:
            raise ValueError(
                "invocation_context requires a scope bound to "
                "run/node_run/attempt; use activation_context for activation"
            )
        return self._build_context(scope, cancellation)

    def _build_context(
        self,
        scope: InvocationScope,
        cancellation: ExtensionCancellation | None,
    ) -> ExtensionContext:
        context = ExtensionContext(
            descriptor=self.descriptor,
            scope=scope,
            config=ExtensionConfigView(
                extension_id=self.descriptor.identity.extension_id,
                declared=self.descriptor.config_keys,
                values=self._config_values,
            ),
            cancellation=cancellation or ExtensionCancellation.of_current_task(),
            progress=UngrantedProgressReporter(self.descriptor.identity.extension_id),
            services=self._service_grants,
            dispatch_effect=self._dispatch_effect(scope),
        )
        # Bind the sink reporter to its owning context now that construction
        # is complete, so progress events correlate to this invocation's scope.
        if self._progress_sink is not None:
            context.progress = BoundProgressReporter(sink=self._progress_sink, context=context)
        return context

    def _dispatch_effect(self, scope: InvocationScope) -> EffectDispatcher:
        async def dispatch(effect_key: str, request: Any) -> EffectReceipt:
            if effect_key not in self.descriptor.effects:
                raise EffectNotDeclared(
                    f"effect {effect_key!r} is not declared by extension "
                    f"{self.descriptor.identity.extension_id!r}"
                )
            route = self._effect_routes.get(effect_key)
            if route is None:
                raise EffectNotDeclared(
                    f"effect {effect_key!r} is declared by extension "
                    f"{self.descriptor.identity.extension_id!r} but the host "
                    "granted no governed route"
                )
            receipt = await route.dispatch(scope=scope, request=request)
            await self._record_effect_provenance(scope, receipt)
            return receipt

        return dispatch

    async def _record_effect_provenance(
        self,
        scope: InvocationScope,
        receipt: EffectReceipt,
    ) -> None:
        """Attribute a settled effect to this extension on the canonical stream."""
        if self._events is None:
            return
        correlation = scope.correlation
        await self._events.append(
            EventEnvelope(
                type=EFFECT_EVENT_TYPE,
                workspace_id=correlation["workspace_id"],
                run_id=correlation["run_id"],
                node_run_id=correlation["node_run_id"],
                attempt_id=correlation["attempt_id"],
                invocation_id=receipt.invocation_id,
                correlation_id=correlation["run_id"],
                source="maistro.extensions",
                provenance=dict(self.descriptor.identity.provenance),
                payload={
                    "effect_key": receipt.effect_key,
                    "binding_id": receipt.binding_id,
                    "capability": receipt.capability,
                    "status": receipt.status,
                },
            )
        )

    async def activate(
        self,
        lifecycle: Any,
        context: ExtensionContext,
    ) -> None:
        await run_activation(lifecycle, context)

    async def invoke(self, lifecycle: Any, context: ExtensionContext) -> Any:
        return await run_invocation(lifecycle, context)

    async def deactivate(self, lifecycle: Any, context: ExtensionContext) -> None:
        await run_deactivation(lifecycle, context)


__all__ = [
    "EFFECT_EVENT_TYPE",
    "PROGRESS_EVENT_TYPE",
    "BoundProgressReporter",
    "EffectRoute",
    "EventStoreProgressSink",
    "ExtensionHost",
    "GovernedEffectRoute",
    "ProgressSink",
]
