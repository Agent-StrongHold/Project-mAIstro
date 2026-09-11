"""Quota admission and accounting for the canonical Invocation boundary.

This module deliberately owns the quota *decision* for a physical effect. Router
and Agent objects may still carry legacy configuration for selection or reporting,
but they must not decide whether a provider call can start. A reservation is held
from admission through provider completion; successful usage is then committed to
the same scope, while proven failures release it and ambiguous outcomes remain
reserved until an explicit reconciliation arrives.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from uuid import uuid4

from maistro.quota.rate_profile import WINDOW_SECONDS, LimitUnit, ModelRateProfile
from maistro.quota.usage_log import InMemoryUsageLog
from maistro.types.errors import QuotaReserveError

if TYPE_CHECKING:
    from maistro.capabilities.binding import Binding
    from maistro.capabilities.invocation import InvocationUsage


class QuotaOutcome(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class QuotaAmount:
    """Conservative units reserved before a provider call starts."""

    requests: int = 1
    input_tokens: int = 0
    output_tokens: int = 0
    images: int = 0
    cost_usd: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def as_dict(self) -> dict[str, int | float]:
        return {
            "requests": self.requests,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "images": self.images,
            "cost_usd": self.cost_usd,
        }


@dataclass(frozen=True)
class QuotaReservation:
    """Secret-free evidence of the admission scope and reserved amount."""

    reservation_id: str
    invocation_id: str
    scope_key: str
    workspace_id: str
    project_id: str
    principal_id: str
    provider: str
    capability: str
    amount: QuotaAmount
    created_at: float


@dataclass(frozen=True)
class QuotaSettlement:
    """The accounting result attached to a terminal Invocation."""

    scope_key: str
    outcome: QuotaOutcome
    reserved: QuotaAmount
    final: QuotaAmount | None
    reconciled: bool = False


@runtime_checkable
class QuotaAdmission(Protocol):
    """Canonical reserve/settle contract for provider effects.

    Implementations must make ``reserve`` atomic with respect to all replicas
    sharing their backing store. The in-memory implementation is intentionally
    process-local and is suitable for tests and explicitly ephemeral deployments.
    """

    async def reserve(
        self,
        *,
        invocation_id: str,
        binding: Binding,
        provider: str,
        principal_id: str,
        capability: str,
        amount: QuotaAmount,
    ) -> QuotaReservation: ...

    async def settle(
        self,
        invocation_id: str,
        outcome: QuotaOutcome,
        usage: InvocationUsage | None = None,
    ) -> QuotaSettlement: ...

    async def reconcile(
        self,
        invocation_id: str,
        usage: InvocationUsage | None = None,
    ) -> QuotaSettlement: ...


class InMemoryInvocationQuota:
    """Atomic process-local quota gate backed by the shared usage log."""

    def __init__(
        self,
        *,
        usage_log: InMemoryUsageLog | None = None,
        profile_for: Callable[[str], ModelRateProfile] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.usage_log = usage_log or InMemoryUsageLog()
        self._profile_for = profile_for or _permissive_profile
        self._clock = clock
        self._reservations: dict[str, QuotaReservation] = {}
        self._uncertain: set[str] = set()
        self._lock = asyncio.Lock()

    async def reserve(
        self,
        *,
        invocation_id: str,
        binding: Binding,
        provider: str,
        principal_id: str,
        capability: str,
        amount: QuotaAmount,
    ) -> QuotaReservation:
        if (
            amount.requests <= 0
            or min(amount.input_tokens, amount.output_tokens, amount.images) < 0
        ):
            raise ValueError("quota reservation amounts must be non-negative")
        profile = self._profile_for(provider)
        scope_key = profile.scope_key(
            provider=provider,
            model=provider,
            workspace=binding.workspace_id,
            workspace_id=binding.workspace_id,
            project=binding.project_id,
            project_id=binding.project_id,
            principal=principal_id,
            principal_id=principal_id,
            capability=capability,
        )
        now = self._clock()
        reservation = QuotaReservation(
            reservation_id=uuid4().hex,
            invocation_id=invocation_id,
            scope_key=scope_key,
            workspace_id=binding.workspace_id,
            project_id=binding.project_id,
            principal_id=principal_id,
            provider=provider,
            capability=capability,
            amount=amount,
            created_at=now,
        )
        async with self._lock:
            for constraint in profile.constraints:
                used = self._used(constraint, scope_key, now)
                pending = self._pending(constraint, scope_key, now)
                requested = _amount_for(amount, constraint.unit)
                if used + pending + requested > constraint.limit:
                    raise QuotaReserveError(
                        f"quota reserve exhausted for provider {provider!r} "
                        f"({constraint.unit.value}/{constraint.window.value}: "
                        f"{used + pending:.0f}/{constraint.limit})"
                    )
            self._reservations[invocation_id] = reservation
        return reservation

    async def settle(
        self,
        invocation_id: str,
        outcome: QuotaOutcome,
        usage: InvocationUsage | None = None,
    ) -> QuotaSettlement:
        async with self._lock:
            reservation = self._reservations.get(invocation_id)
            if reservation is None:
                raise KeyError(f"no quota reservation for Invocation {invocation_id!r}")
            if outcome is QuotaOutcome.UNKNOWN:
                self._uncertain.add(invocation_id)
                return QuotaSettlement(
                    scope_key=reservation.scope_key,
                    outcome=outcome,
                    reserved=reservation.amount,
                    final=None,
                )
            self._reservations.pop(invocation_id)
            self._uncertain.discard(invocation_id)
            final = _usage_amount(usage) if outcome is QuotaOutcome.COMPLETED else None
            if final is not None:
                self.usage_log.record(
                    reservation.scope_key,
                    input_tokens=final.input_tokens,
                    output_tokens=final.output_tokens,
                    images=final.images,
                    cost_usd=final.cost_usd,
                    now=self._clock(),
                )
            return QuotaSettlement(
                scope_key=reservation.scope_key,
                outcome=outcome,
                reserved=reservation.amount,
                final=final,
            )

    async def reconcile(
        self,
        invocation_id: str,
        usage: InvocationUsage | None = None,
    ) -> QuotaSettlement:
        """Resolve an UNKNOWN provider outcome with evidence or rollback.

        ``usage=None`` means an operator/provider verifier proved that no usage
        occurred. It is not treated as zero-cost successful usage.
        """
        return await self.settle(
            invocation_id,
            QuotaOutcome.COMPLETED if usage is not None else QuotaOutcome.FAILED,
            usage,
        )

    def pending_invocations(self) -> tuple[str, ...]:
        """Read-only recovery visibility for uncertain/provider-delayed calls."""
        return tuple(self._uncertain)

    def _used(self, constraint: object, scope_key: str, now: float) -> float:
        # Kept in one place so reservation and committed usage use identical windows.
        assert hasattr(constraint, "unit") and hasattr(constraint, "window")
        unit = constraint.unit
        seconds = WINDOW_SECONDS[constraint.window]
        if unit is LimitUnit.REQUESTS:
            return self.usage_log.count_since(scope_key, seconds, now=now)
        return self.usage_log.tokens_since(scope_key, seconds, unit, now=now)

    def _pending(self, constraint: object, scope_key: str, now: float) -> float:
        assert hasattr(constraint, "unit") and hasattr(constraint, "window")
        cutoff = now - WINDOW_SECONDS[constraint.window]
        return sum(
            _amount_for(reservation.amount, constraint.unit)
            for reservation in self._reservations.values()
            if reservation.scope_key == scope_key and reservation.created_at > cutoff
        )


def _permissive_profile(provider: str) -> ModelRateProfile:
    return ModelRateProfile(provider=provider, model=provider)


def _amount_for(amount: QuotaAmount, unit: LimitUnit) -> float:
    return {
        LimitUnit.REQUESTS: float(amount.requests),
        LimitUnit.INPUT_TOKENS: float(amount.input_tokens),
        LimitUnit.OUTPUT_TOKENS: float(amount.output_tokens),
        LimitUnit.TOTAL_TOKENS: float(amount.total_tokens),
        LimitUnit.IMAGES: float(amount.images),
        LimitUnit.CREDITS_USD: amount.cost_usd,
    }[unit]


def _usage_amount(usage: InvocationUsage | None) -> QuotaAmount:
    if usage is None:
        return QuotaAmount()
    return QuotaAmount(
        input_tokens=usage.input_units,
        output_tokens=usage.output_units,
        cost_usd=(usage.cost_cents or 0.0) / 100.0,
    )


__all__ = [
    "InMemoryInvocationQuota",
    "QuotaAdmission",
    "QuotaAmount",
    "QuotaOutcome",
    "QuotaReservation",
    "QuotaSettlement",
]
