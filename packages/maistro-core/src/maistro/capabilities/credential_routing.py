"""Credential routing composed onto the canonical Invocation path (#58).

Wraps the two seams :class:`~maistro.capabilities.invocation.InvocationExecutionService`
already owns — ``ProviderResolver`` and ``ProviderExecutor`` — so credential
selection happens exactly where the Provider choice is known, and rotation
happens exactly where the provider call's outcome is known:

- the wrapped :term:`resolver` resolves the Binding's provider, then acquires a
  credential from the :class:`~maistro.credentials.router.CredentialRouter`
  under the Binding's own Workspace/Project scope, restricted to the
  ``credential_refs`` the Binding authorizes;
- the wrapped :term:`executor` hands the selected credential to the provider
  call and folds the call's real outcome back into the pool (success, cooldown,
  or permanent block per the ADR-063 table).

There is deliberately no retry loop here. A retry is a new Attempt producing a
new Invocation, owned by the canonical execution model; this module only makes
each physical call authenticate with an authorized credential and makes the
pool react to what the provider actually said. Secrets stop at the executor:
:class:`CredentialBackedProvider` is never persisted —
:meth:`maistro.capabilities.binding.ResolvedBinding.from_provider` copies only
provider metadata — and its repr shows the key id alone.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from maistro.capabilities.binding import ResolvedCapabilityProvider
from maistro.capabilities.invocation import ProviderExecutor, ProviderResolver
from maistro.capabilities.types import Unavailable
from maistro.credentials.router import CredentialRouter
from maistro.credentials.types import CredentialRecord, PoolExhaustedError

RoutedResolver = Callable[[ProviderResolver], ProviderResolver]
RoutedExecutor = Callable[[ProviderExecutor], ProviderExecutor]


@runtime_checkable
class CredentialConsumer(Protocol):
    """A resolved provider that authenticates from the scoped credential pool.

    ``credential_provider`` names the *credential* provider (``"openai"``,
    ``"jira"``, …) whose pool the provider consumes — distinct from the
    capability-provider name it also carries. Only providers that declare this
    surface are routed through the pool; a resolver-facing provider that does
    not is reported unavailable rather than silently run without governed
    credentials.
    """

    @property
    def credential_provider(self) -> str: ...


@dataclass(frozen=True)
class CredentialBackedProvider:
    """Resolved provider paired with the scoped credential selected for it.

    Carries the Binding's scope so the executor can report the outcome back to
    the right pool. ``name``/``slot``/``trust_tier`` delegate to the wrapped
    provider, satisfying :class:`ResolvedCapabilityProvider`, which is all that
    is persisted — the credential itself never reaches an Invocation or an
    event.
    """

    base: ResolvedCapabilityProvider
    credential: CredentialRecord
    workspace_id: str
    project_id: str

    @property
    def name(self) -> str:
        return self.base.name

    @property
    def slot(self) -> str:
        return self.base.slot

    @property
    def trust_tier(self) -> str:
        return self.base.trust_tier

    @property
    def credential_provider(self) -> str:
        """The credential pool this selection came from (matches the record)."""

        return self.credential.provider

    def __repr__(self) -> str:  # pragma: no cover - defensive, asserted in tests
        # The dataclass default would embed ``credential`` — and with it the
        # api_key — into any traceback or log that reprs this provider. Only
        # non-secret identity is ever shown.
        return (
            f"CredentialBackedProvider(name={self.name!r}, key_id={self.credential.key_id!r}, "
            f"workspace_id={self.workspace_id!r}, project_id={self.project_id!r})"
        )


@dataclass(frozen=True)
class CredentialRouting:
    """Compose credential-routed resolver/executor pairs for one router."""

    router: CredentialRouter

    def resolver(self, base: ProviderResolver) -> ProviderResolver:
        """Wrap ``base`` so resolution acquires a Binding-scoped credential.

        Authorization failures from the router propagate as
        :class:`~maistro.credentials.router.CredentialScopeError` (a
        :class:`PermissionError`): they are durable misconfigurations a retry
        cannot fix. Pool exhaustion is surfaced as the typed
        :class:`~maistro.capabilities.types.Unavailable` the canonical service
        already converts to
        :class:`~maistro.capabilities.invocation.CapabilityUnavailable`, with
        the soonest cooldown included, so a later Attempt can succeed once a
        key recovers.
        """

        async def resolve(binding: Any) -> ResolvedCapabilityProvider | Unavailable:
            provider = await base(binding)
            if isinstance(provider, Unavailable):
                return provider
            if not isinstance(provider, CredentialConsumer):
                return Unavailable(
                    slot=binding.capability,
                    reason=(
                        f"provider {provider.name!r} does not declare the "
                        "credential_provider surface required by credential routing"
                    ),
                )
            try:
                credential = await self.router.acquire(
                    workspace_id=binding.workspace_id,
                    project_id=binding.project_id,
                    provider=provider.credential_provider,
                    credential_refs=binding.credential_refs,
                )
            except PoolExhaustedError as exc:
                return Unavailable(
                    slot=binding.capability,
                    reason=(
                        f"credential pool exhausted for {provider.credential_provider!r}: "
                        f"{exc.message} (soonest recovery in {exc.wait_seconds:.0f}s)"
                    ),
                )
            return CredentialBackedProvider(
                base=provider,
                credential=credential,
                workspace_id=binding.workspace_id,
                project_id=binding.project_id,
            )

        return resolve

    def executor(self, base: ProviderExecutor) -> ProviderExecutor:
        """Wrap ``base`` so each provider call's outcome rotates the pool.

        The wrapped provider (a :class:`CredentialBackedProvider`) is passed
        through to ``base`` unchanged, so the physical executor reads
        ``provider.credential`` to authenticate. Outcome recording happens
        before the exception re-raises, so the very next acquisition sees the
        cooldown. :class:`asyncio.CancelledError` is deliberately not folded
        in: cancellation is not a provider outcome, and its external effect is
        unknown — the Invocation records UNKNOWN and the key is not penalized.
        """

        async def execute(provider: Any, request: Any) -> Any:
            if not isinstance(provider, CredentialBackedProvider):
                return await base(provider, request)
            try:
                result = await base(provider, request)
            except Exception as exc:
                await self.router.record_outcome(
                    workspace_id=provider.workspace_id,
                    project_id=provider.project_id,
                    provider=provider.credential_provider,
                    key_id=provider.credential.key_id,
                    error=exc,
                )
                raise
            await self.router.record_outcome(
                workspace_id=provider.workspace_id,
                project_id=provider.project_id,
                provider=provider.credential_provider,
                key_id=provider.credential.key_id,
                error=None,
            )
            return result

        return execute


__all__ = [
    "CredentialBackedProvider",
    "CredentialConsumer",
    "CredentialRouting",
    "RoutedExecutor",
    "RoutedResolver",
]
