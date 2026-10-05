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


__all__ = [
    "AllRefusingSubject",
    "BaseConformanceSubject",
    "PlaintextSecretSubject",
    "RawSocketEgressSubject",
    "ReferenceProvider",
    "UnavailableBackendSubject",
    "UncancellableSubject",
]
