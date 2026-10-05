"""Conformance suite subjects: a conformant reference and deliberate violators.

These are the legs the shared conformance suite (issue #965) runs against in
this repository's own tests:

- :class:`ReferenceConformantSubject` — a built-in implementation of the
  ``ConformanceSubject`` protocol that does everything the canonical way
  (credential references, guarded shared-client egress, cooperative
  cancellation, usage reporting). It is parameterized by family so the same
  bodies demonstrably run against provider, connector and tool subjects.
- :class:`PlaintextSecretSubject` — accepts plaintext secrets. Must fail.
- :class:`RawSocketEgressSubject` — fetches with a bare ``httpx.AsyncClient``
  instead of the guarded shared-client seam. Must fail with wire evidence
  (the audit server counts its request).
- :class:`UncancellableSubject` — shields its work from cancellation. Must
  fail the deadline check.
- :class:`UnavailableBackendSubject` — declares its real backend unusable, so
  the real-backend legs skip. Used to prove skip handling and the fatality
  rule.

Each violator subclasses the reference and breaks exactly one property, so a
failure names the broken semantic rather than something adjacent. The
unauthorized-credential-reference direction has no per-subject violator by
design: the shared check body itself wraps the subject's resolver in the
production ``CredentialRouting`` seam, so the loud denial of an unauthorized
reference is proven against every subject identically.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from maistro.capabilities.binding import Binding
from maistro.capabilities.invocation import InvocationUsage
from maistro.capabilities.types import Unavailable
from maistro.conformance.contract import (
    MEMORY_BACKEND,
    BackendLeg,
    SubjectDescriptor,
    SubjectFamily,
)
from maistro.conformance.subject import EffectRequest
from maistro.credentials.router import CredentialScopeError

_REPORTED_USAGE = InvocationUsage(
    units="tokens", input_units=7, output_units=3, model="conformance-model"
)


@dataclass(frozen=True)
class ReferenceProvider:
    """The subject's provider: metadata plus the credential-routing surface."""

    name: str = "reference-subject"
    slot: str = "conformance.effect"
    trust_tier: str = "trusted"
    credential_provider: str = "conformance"


class BaseConformanceSubject:
    """A conforming implementation of the conformance subject protocol.

    Every property the suite checks is implemented the canonical way here;
    violators below override exactly one method to break one property. This
    class is itself the "built-in implementations can opt into the same
    suite" leg: it is an in-repo implementation running the identical bodies a
    third party would run.
    """

    def __init__(
        self,
        *,
        name: str = "reference-subject",
        family: SubjectFamily = SubjectFamily.PROVIDER,
        declared_contract_version: str = "1.0.0",
        backend: BackendLeg = MEMORY_BACKEND,
        real_backend_available: bool = True,
    ) -> None:
        self._descriptor = SubjectDescriptor(
            name=name,
            family=family,
            declared_contract_version=declared_contract_version,
        )
        self._backend = backend
        self._real_backend_available = real_backend_available

    @property
    def descriptor(self) -> SubjectDescriptor:
        return self._descriptor

    @property
    def backend(self) -> BackendLeg:
        return self._backend

    def real_backend_available(self) -> bool:
        return self._real_backend_available

    def prepare_config(self, config: Mapping[str, Any]) -> Mapping[str, Any]:
        prepared = dict(config)
        secret = prepared.pop("api_key", None)
        if secret is not None:
            raise ValueError(
                "plaintext 'api_key' is not accepted: declare a credential reference "
                "instead (Binding.credential_refs)"
            )
        return prepared

    async def resolve_provider(self, binding: Binding) -> Any:
        del binding
        return ReferenceProvider(name=self._descriptor.name)

    async def execute(self, provider: Any, request: EffectRequest) -> Any:
        if request.hang_seconds > 0:
            await asyncio.sleep(request.hang_seconds)
        if request.url:
            await self._fetch(provider, request.url)
        if request.payload.get("report_usage", True):
            return {"usage": _REPORTED_USAGE, "echo": dict(request.payload)}
        return {"ok": True}

    async def _fetch(self, provider: Any, url: str) -> None:
        """Fetch through the platform's guarded shared-client seam."""
        from maistro.http import shared_client

        headers: dict[str, str] = {}
        credential = getattr(provider, "credential", None)
        if credential is not None:
            headers["authorization"] = f"Bearer {credential.api_key}"
        async with shared_client() as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()

    def usage_from(self, result: Any) -> InvocationUsage | None:
        if isinstance(result, dict) and isinstance(result.get("usage"), InvocationUsage):
            return result["usage"]
        return None


# Violators: each breaks exactly one property the suite checks.


class PlaintextSecretSubject(BaseConformanceSubject):
    """Breaks secret semantics: quietly keeps plaintext in prepared config."""

    def prepare_config(self, config: Mapping[str, Any]) -> Mapping[str, Any]:
        return dict(config)


class RawSocketEgressSubject(BaseConformanceSubject):
    """Breaks egress semantics: a bare httpx client bypasses the guarded seam."""

    async def _fetch(self, provider: Any, url: str) -> None:
        del provider
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()


class UncancellableSubject(BaseConformanceSubject):
    """Breaks cancellation semantics: shields the hang so a deadline cannot land."""

    async def execute(self, provider: Any, request: EffectRequest) -> Any:
        if request.hang_seconds > 0:
            try:
                await asyncio.shield(asyncio.sleep(request.hang_seconds))
            except asyncio.CancelledError:
                await asyncio.sleep(30)  # refuses to stop: blocks the grace period
        return await super().execute(provider, request)


class UnavailableBackendSubject(BaseConformanceSubject):
    """Declares its real backend unusable so the real-backend legs skip."""

    def real_backend_available(self) -> bool:
        return False


class AllRefusingSubject(BaseConformanceSubject):
    """Refuses to serve any binding — exercises the fail-closed probes."""

    async def resolve_provider(self, binding: Binding) -> Unavailable:
        return Unavailable(slot=binding.capability, reason="reference refusal leg")


# Single-property violators for the check bodies' own verdict branches. Each one
# pins one specific refusal/leak/fetch shape the shared body must classify
# differently from its neighbours, so a check that starts accepting the wrong
# shape fails by name instead of by coverage count.


class StrippingSecretSubject(BaseConformanceSubject):
    """Strips plaintext from prepared config without raising (acceptable shape)."""

    def prepare_config(self, config: Mapping[str, Any]) -> Mapping[str, Any]:
        prepared = dict(config)
        prepared.pop("api_key", None)
        return prepared


class WrongRefusalTypeSubject(BaseConformanceSubject):
    """Crashes with a non-refusal error type instead of a normalized refusal."""

    def prepare_config(self, config: Mapping[str, Any]) -> Mapping[str, Any]:
        del config
        raise KeyError("conformance probe: non-refusal crash")


class ScopeDenyingSubject(BaseConformanceSubject):
    """Refuses even its own authorized binding with the canonical scope error."""

    async def resolve_provider(self, binding: Binding) -> Any:
        raise CredentialScopeError("conformance probe: subject-side scope denial")


class QuietRefusalSubject(BaseConformanceSubject):
    """Refuses undeclared egress with its own error before any connection."""

    async def _fetch(self, provider: Any, url: str) -> None:
        del provider
        raise ValueError(f"origin not declared by policy: {url}")


class CrashingFetchSubject(BaseConformanceSubject):
    """Fails the egress effect with a non-refusal error before connecting."""

    async def _fetch(self, provider: Any, url: str) -> None:
        del provider
        raise RuntimeError("conformance probe: ambiguous transport failure")


class NoFetchSubject(BaseConformanceSubject):
    """Completes without fetching: a declared leg must then see zero hits."""

    async def _fetch(self, provider: Any, url: str) -> None:
        del provider, url


class DoubleFetchSubject(BaseConformanceSubject):
    """Fetches the probe URL twice: one declared request, two server hits."""

    async def _fetch(self, provider: Any, url: str) -> None:
        await super()._fetch(provider, url)
        await super()._fetch(provider, url)


class OffsiteFetchSubject(BaseConformanceSubject):
    """Fetches a second, undeclared origin even on the declared leg."""

    async def _fetch(self, provider: Any, url: str) -> None:
        del provider
        from maistro.http import shared_client

        offsite = url.rsplit(":", 1)[0].rsplit(":", 1)[0] + ":1/conformance-offsite"
        async with shared_client() as client:
            response = await client.get(offsite)
            response.raise_for_status()


class RawThenGuardedSubject(BaseConformanceSubject):
    """Raw-socket fetch first (wire moves), then the guarded seam refuses."""

    async def _fetch(self, provider: Any, url: str) -> None:
        del provider
        async with httpx.AsyncClient() as client:
            await client.get(url)
        from maistro.http import shared_client

        async with shared_client() as client:
            response = await client.get(url)
            response.raise_for_status()


class ExceptingOnCancelSubject(BaseConformanceSubject):
    """Surfaces a fresh RuntimeError on cancellation instead of propagating it."""

    async def execute(self, provider: Any, request: EffectRequest) -> Any:
        if request.hang_seconds > 0:
            try:
                await asyncio.sleep(request.hang_seconds)
            except asyncio.CancelledError:
                raise RuntimeError("conformance probe: cancellation swallowed") from None
        return await super().execute(provider, request)


class DriftedUsageSubject(BaseConformanceSubject):
    """Reports usage units that differ from what its effect actually produced."""

    def usage_from(self, result: Any) -> InvocationUsage | None:
        usage = super().usage_from(result)
        if usage is None:
            return None
        return InvocationUsage(units=usage.units, input_units=8, output_units=3, model=usage.model)


class IncompleteEffectSubject(BaseConformanceSubject):
    """The reported-usage effect itself fails, so nothing ever completes."""

    async def execute(self, provider: Any, request: EffectRequest) -> Any:
        if request.payload.get("report_usage", True):
            raise RuntimeError("conformance probe: effect never completed")
        return await super().execute(provider, request)


class UsageOnUnreportedSubject(BaseConformanceSubject):
    """Reports usage even for the effect that carried none."""

    def usage_from(self, result: Any) -> InvocationUsage | None:
        if isinstance(result, dict) and result.get("ok") is True:
            return _REPORTED_USAGE
        return super().usage_from(result)


__all__ = [
    "AllRefusingSubject",
    "BaseConformanceSubject",
    "CrashingFetchSubject",
    "DoubleFetchSubject",
    "DriftedUsageSubject",
    "ExceptingOnCancelSubject",
    "IncompleteEffectSubject",
    "NoFetchSubject",
    "OffsiteFetchSubject",
    "PlaintextSecretSubject",
    "QuietRefusalSubject",
    "RawSocketEgressSubject",
    "RawThenGuardedSubject",
    "ReferenceProvider",
    "ScopeDenyingSubject",
    "StrippingSecretSubject",
    "UnavailableBackendSubject",
    "UncancellableSubject",
    "UsageOnUnreportedSubject",
    "WrongRefusalTypeSubject",
]
