"""The adapter a third-party implementation provides to run the shared suite.

The suite is family-neutral: a provider, a connector and a tool all conform by
exposing the same small surface, and the shared check bodies drive that surface
through the canonical platform seams (Binding, credential routing, the
Invocation service, the guarded outbound seam). Built-in implementations opt in
through the exact same protocol — there is no built-in fast path.

Every method is a real execution surface, never an introspection hook: the
checks call these to make the subject do its actual work, then assert what the
platform recorded. Nothing in conformance is decided by reading the subject's
source.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from maistro.capabilities.binding import Binding, ResolvedCapabilityProvider
from maistro.capabilities.invocation import InvocationUsage
from maistro.capabilities.types import Unavailable
from maistro.conformance.contract import BackendLeg, SubjectDescriptor


@dataclass(frozen=True)
class EffectRequest:
    """One physical effect the framework asks the subject to perform.

    ``url`` is a destination the subject's effect must reach through the
    platform's guarded outbound seam. ``hang_seconds`` asks the effect to stay
    async-busy (cancellable) for at least that long — the deadline probe relies
    on it. ``payload`` is opaque effect input the subject owns.
    """

    url: str = ""
    payload: Mapping[str, Any] = field(default_factory=dict)
    hang_seconds: float = 0.0


@runtime_checkable
class ConformanceSubject(Protocol):
    """The execution surface the shared conformance suite drives.

    A conforming subject:

    * refuses plaintext secrets in ``prepare_config`` (or strips them from its
      prepared configuration);
    * resolves its provider through the Binding it is given, so credential
      routing and scope resolution apply unchanged;
    * performs ``execute`` through the platform's guarded outbound seam and
      stays cancellable while working;
    * reports usage for its effects through ``usage_from``.
    """

    @property
    def descriptor(self) -> SubjectDescriptor: ...

    @property
    def backend(self) -> BackendLeg: ...

    def real_backend_available(self) -> bool:
        """Whether the subject's real-backend leg can run on this host.

        Checked before the egress probes start their local socket. ``False``
        makes those checks record a skip — which invalidates the claim and is
        fatal when the runner requires real backends.
        """
        ...

    def prepare_config(self, config: Mapping[str, Any]) -> Mapping[str, Any]:
        """Validate/normalize operator configuration for the subject.

        Receives a candidate configuration mapping (the same shape a Binding's
        ``config`` field carries). A conforming subject refuses plaintext
        credentials by raising, or returns a prepared view that contains no
        plaintext secret material — only references.
        """
        ...

    async def resolve_provider(self, binding: Binding) -> ResolvedCapabilityProvider | Unavailable:
        """Resolve the subject's provider for ``binding``.

        Same contract as the canonical ``ProviderResolver`` seam: returns the
        resolved provider (metadata-only view), or
        :class:`maistro.capabilities.types.Unavailable` when the subject
        cannot serve the binding. Credential routing wraps this seam exactly
        as it wraps production resolvers.
        """
        ...

    async def execute(self, provider: Any, request: EffectRequest) -> Any:
        """Perform one physical effect as the resolved ``provider``.

        When ``request.url`` is set the effect must fetch it through
        ``maistro.http`` (the guarded shared-client seam). Must honor
        cooperative cancellation while ``request.hang_seconds`` is pending.
        Returns the effect result; raises on failure.
        """
        ...

    def usage_from(self, result: Any) -> InvocationUsage | None:
        """Extract canonical usage evidence from one effect result.

        Returns ``None`` when the effect carries no usage — which the usage
        authority records as an explicit unreported marker, never as zero.
        """
        ...
