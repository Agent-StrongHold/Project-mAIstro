"""Canonical Binding -> Invocation external-effect boundary.

An Invocation is one actual provider call beneath an Attempt. ``effect_key`` is
stable across retries of the same logical NodeRun so recovery can distinguish a
known completed effect from an outcome that is unsafe to repeat.

Generic provider exceptions are deliberately recorded as ``UNKNOWN`` rather
than retryable failure: an exception can arrive after the remote system has
already committed the side effect. A provider/adapter may raise
:class:`EffectNotApplied` only when it can prove no external effect occurred.

The composition root constructs this service for governed effect consumers.
Provider selection, quota reservation, physical dispatch, usage settlement and
retry safety therefore meet here; router and Agent quota arguments are retained
only for legacy selection/reporting compatibility. Durable deployments may
provide a shared ``QuotaAdmission`` implementation, while ephemeral contexts
use the explicitly process-local implementation from ``quota.invocation``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from maistro.capabilities.binding import Binding, ResolvedBinding, ResolvedCapabilityProvider
from maistro.capabilities.types import Unavailable
from maistro.quota.invocation import (
    QuotaAdmission,
    QuotaAmount,
    QuotaOutcome,
    QuotaReservation,
    QuotaSettlement,
)


def _id() -> str:
    return uuid4().hex


def _require(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} must be a non-empty string")


class InvocationStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"


TERMINAL_INVOCATION_STATUSES = frozenset(
    {
        InvocationStatus.COMPLETED,
        InvocationStatus.FAILED,
        InvocationStatus.UNKNOWN,
    }
)


class InvocationUsage(BaseModel):
    """Usage/provenance metadata for one provider call (ADR-081226-6b46).

    ``input_units``/``output_units`` are measured in ``units`` ("tokens" for
    model inference). ``cost_cents`` is computed from registry metadata when
    the selected model is registered and stays ``None`` when it is not -- an
    unmeasured cost is absent, not zero. ``model_version`` is the concrete
    version the provider reported, which may differ from the requested alias.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    units: str = "tokens"
    input_units: int = 0
    output_units: int = 0
    cost_cents: float | None = None
    model: str = ""
    model_version: str = ""
    provider: str = ""

    @model_validator(mode="after")
    def _validate_usage(self) -> InvocationUsage:
        if not self.units.strip():
            raise ValueError("units must be a non-empty string")
        if self.input_units < 0 or self.output_units < 0:
            raise ValueError("usage units cannot be negative")
        if self.cost_cents is not None and self.cost_cents < 0:
            raise ValueError("cost_cents cannot be negative")
        return self


class InvocationQuotaEvidence(BaseModel):
    """Secret-free admission and accounting evidence for one Invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scope_key: str
    workspace_id: str
    project_id: str
    principal_id: str = ""
    provider: str
    capability: str
    state: str
    reserved: dict[str, int | float] = Field(default_factory=dict)
    final: dict[str, int | float] | None = None
    reason: str | None = None


class Invocation(BaseModel):
    """One actual provider call beneath one physical Attempt."""

    model_config = ConfigDict(extra="forbid")

    invocation_id: str = Field(default_factory=_id)
    run_id: str
    node_run_id: str
    attempt_id: str
    principal_id: str = ""
    binding: ResolvedBinding
    effect_key: str
    status: InvocationStatus = InvocationStatus.CREATED
    quota: InvocationQuotaEvidence | None = None
    request: Any | None = None
    result: Any | None = None
    usage: InvocationUsage | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @model_validator(mode="after")
    def _validate_invocation(self) -> Invocation:
        _require(self.invocation_id, "invocation_id")
        _require(self.run_id, "run_id")
        _require(self.node_run_id, "node_run_id")
        _require(self.attempt_id, "attempt_id")
        _require(self.effect_key, "effect_key")
        terminal = self.status in TERMINAL_INVOCATION_STATUSES
        if terminal and self.finished_at is None:
            raise ValueError("terminal Invocation requires finished_at")
        if not terminal and self.finished_at is not None:
            raise ValueError("non-terminal Invocation cannot have finished_at")
        return self

    @property
    def effect_identity(self) -> tuple[str, str, str, str]:
        """Logical effect identity stable across physical Attempt retries."""

        return (self.run_id, self.node_run_id, self.binding.binding_id, self.effect_key)


@runtime_checkable
class InvocationStore(Protocol):
    """Durable persistence contract for capability Invocations."""

    async def create(self, invocation: Invocation) -> Invocation: ...

    async def get(self, invocation_id: str) -> Invocation | None: ...

    async def save(self, invocation: Invocation) -> Invocation: ...

    async def list_effect(
        self,
        *,
        run_id: str,
        node_run_id: str,
        binding_id: str,
        effect_key: str,
    ) -> list[Invocation]: ...


class InMemoryInvocationStore:
    """Concurrency-safe in-memory InvocationStore for tests/local execution."""

    def __init__(self) -> None:
        self._items: dict[str, Invocation] = {}
        self._lock = asyncio.Lock()

    async def create(self, invocation: Invocation) -> Invocation:
        async with self._lock:
            if invocation.invocation_id in self._items:
                raise ValueError(f"Invocation {invocation.invocation_id!r} already exists")
            persisted = invocation.model_copy(deep=True)
            self._items[persisted.invocation_id] = persisted
            return persisted.model_copy(deep=True)

    async def get(self, invocation_id: str) -> Invocation | None:
        item = self._items.get(invocation_id)
        return item.model_copy(deep=True) if item is not None else None

    async def save(self, invocation: Invocation) -> Invocation:
        async with self._lock:
            if invocation.invocation_id not in self._items:
                raise KeyError(f"Invocation {invocation.invocation_id!r} does not exist")
            persisted = invocation.model_copy(deep=True)
            self._items[persisted.invocation_id] = persisted
            return persisted.model_copy(deep=True)

    async def list_effect(
        self,
        *,
        run_id: str,
        node_run_id: str,
        binding_id: str,
        effect_key: str,
    ) -> list[Invocation]:
        identity = (run_id, node_run_id, binding_id, effect_key)
        return [
            item.model_copy(deep=True)
            for item in sorted(self._items.values(), key=lambda candidate: candidate.created_at)
            if item.effect_identity == identity
        ]


class EffectNotApplied(RuntimeError):
    """Provider proves the requested external effect definitely did not occur."""


class UnsafeEffectRetry(RuntimeError):
    """Recovery cannot safely repeat an effect whose outcome may already exist."""


class CapabilityUnavailable(RuntimeError):
    """A Binding could not resolve an eligible provider."""


ProviderResolver = Callable[
    [Binding],
    Awaitable[ResolvedCapabilityProvider | Unavailable],
]
ProviderExecutor = Callable[[ResolvedCapabilityProvider, Any], Awaitable[Any]]
UsageExtractor = Callable[[Any], "InvocationUsage | None"]


class InvocationExecutionService:
    """Resolve one Binding, persist one provider call, and guard effect retries.

    The composition root supplies this service to governed effect consumers;
    no caller may dispatch around its reservation and accounting seam (#55).
    """

    def __init__(
        self,
        *,
        store: InvocationStore,
        quota_admission: QuotaAdmission | None = None,
    ) -> None:
        self._store = store
        self._quota = quota_admission
        self._effect_lock = asyncio.Lock()

    async def latest_effect(
        self,
        *,
        binding: Binding,
        run_id: str,
        node_run_id: str,
        effect_key: str,
    ) -> Invocation | None:
        """Return the latest canonical Invocation for one logical effect identity."""

        history = await self._store.list_effect(
            run_id=run_id,
            node_run_id=node_run_id,
            binding_id=binding.binding_id,
            effect_key=effect_key,
        )
        return history[-1] if history else None

    async def invoke(
        self,
        *,
        binding: Binding,
        run_id: str,
        node_run_id: str,
        attempt_id: str,
        effect_key: str,
        request: Any,
        resolver: ProviderResolver,
        executor: ProviderExecutor,
        usage_from: UsageExtractor | None = None,
        principal_id: str = "",
        quota_estimate: QuotaAmount | None = None,
    ) -> Invocation:
        """Execute one effect, deduplicating or blocking unsafe recovery.

        A completed prior Invocation for the same logical effect is returned
        without another provider call. ``CREATED``, ``RUNNING``, or ``UNKNOWN``
        history blocks repetition because the remote outcome cannot be proven
        absent. Only a prior ``FAILED`` record, produced by ``EffectNotApplied``,
        is eligible for a new physical Invocation under a later Attempt.
        """

        _require(effect_key, "effect_key")
        async with self._effect_lock:
            history = await self._store.list_effect(
                run_id=run_id,
                node_run_id=node_run_id,
                binding_id=binding.binding_id,
                effect_key=effect_key,
            )
            if history:
                latest = history[-1]
                if latest.status is InvocationStatus.COMPLETED:
                    return latest
                if latest.status in {
                    InvocationStatus.CREATED,
                    InvocationStatus.RUNNING,
                    InvocationStatus.UNKNOWN,
                }:
                    raise UnsafeEffectRetry(
                        f"effect {effect_key!r} has outcome {latest.status.value!r}; "
                        "manual/reconciliation evidence is required before retry"
                    )

            provider = await resolver(binding)
            if isinstance(provider, Unavailable):
                raise CapabilityUnavailable(
                    f"capability {binding.capability!r} unavailable: {provider.reason}"
                )
            resolved = ResolvedBinding.from_provider(binding, provider)
            invocation = await self._store.create(
                Invocation(
                    run_id=run_id,
                    node_run_id=node_run_id,
                    attempt_id=attempt_id,
                    principal_id=principal_id,
                    binding=resolved,
                    effect_key=effect_key,
                    request=request,
                )
            )
            running = invocation.model_copy(
                update={
                    "status": InvocationStatus.RUNNING,
                    "started_at": datetime.now(UTC),
                }
            )
            invocation = await self._store.save(running)

        invocation, reservation = await self._admit_quota(
            invocation,
            binding=binding,
            provider=provider,
            principal_id=principal_id,
            quota_estimate=quota_estimate,
        )

        try:
            result = await executor(provider, request)
        except EffectNotApplied as exc:
            settlement = await self._settle(reservation, QuotaOutcome.FAILED)
            await self._terminalize(
                invocation,
                InvocationStatus.FAILED,
                error=str(exc),
                quota=_settled_evidence(invocation.quota, settlement),
            )
            raise
        except asyncio.CancelledError:
            # Cancellation after provider dispatch is indeterminate. Keep the
            # reservation until a verifier explicitly reconciles the outcome.
            settlement = await self._settle(reservation, QuotaOutcome.UNKNOWN)
            await self._terminalize(
                invocation,
                InvocationStatus.UNKNOWN,
                error="provider invocation cancelled with unknown external outcome",
                quota=_settled_evidence(invocation.quota, settlement),
            )
            raise
        except Exception as exc:
            settlement = await self._settle(reservation, QuotaOutcome.UNKNOWN)
            await self._terminalize(
                invocation,
                InvocationStatus.UNKNOWN,
                error=str(exc) or type(exc).__name__,
                quota=_settled_evidence(invocation.quota, settlement),
            )
            raise

        try:
            usage = usage_from(result) if usage_from is not None else None
        except Exception as exc:
            # The provider succeeded but its report could not be interpreted;
            # retain the reservation until delayed usage evidence reconciles it.
            settlement = await self._settle(reservation, QuotaOutcome.UNKNOWN)
            await self._terminalize(
                invocation,
                InvocationStatus.UNKNOWN,
                error=f"provider usage could not be recorded: {exc}",
                quota=_settled_evidence(invocation.quota, settlement),
            )
            raise
        settlement = await self._settle(reservation, QuotaOutcome.COMPLETED, usage)

        return await self._terminalize(
            invocation,
            InvocationStatus.COMPLETED,
            result=result,
            usage=usage,
            quota=_settled_evidence(invocation.quota, settlement),
        )

    async def _admit_quota(
        self,
        invocation: Invocation,
        *,
        binding: Binding,
        provider: ResolvedCapabilityProvider,
        principal_id: str,
        quota_estimate: QuotaAmount | None,
    ) -> tuple[Invocation, QuotaReservation | None]:
        if self._quota is None:
            return invocation, None
        try:
            reservation = await self._quota.reserve(
                invocation_id=invocation.invocation_id,
                binding=binding,
                provider=provider.name,
                principal_id=principal_id,
                capability=binding.capability,
                amount=quota_estimate or QuotaAmount(),
            )
        except Exception as exc:
            denied = invocation.model_copy(
                update={
                    "quota": InvocationQuotaEvidence(
                        scope_key="",
                        workspace_id=binding.workspace_id,
                        project_id=binding.project_id,
                        principal_id=principal_id,
                        provider=provider.name,
                        capability=binding.capability,
                        state="denied",
                        reason=str(exc) or type(exc).__name__,
                    )
                }
            )
            await self._terminalize(
                denied,
                InvocationStatus.FAILED,
                error=str(exc) or type(exc).__name__,
            )
            raise
        admitted = await self._store.save(
            invocation.model_copy(update={"quota": _reserved_evidence(reservation)})
        )
        return admitted, reservation

    async def reconcile_unknown(
        self,
        invocation_id: str,
        *,
        usage: InvocationUsage | None = None,
        error: str | None = None,
    ) -> Invocation:
        """Apply delayed provider evidence to an UNKNOWN Invocation.

        A positive usage report commits the held reservation; an explicit
        ``usage=None`` report proves the effect did not consume quota and rolls
        it back. This is intentionally a method on the canonical service, not
        a router/Agent recovery hook.
        """
        invocation = await self._store.get(invocation_id)
        if invocation is None:
            raise KeyError(f"Invocation {invocation_id!r} does not exist")
        if invocation.status is not InvocationStatus.UNKNOWN:
            raise ValueError("only UNKNOWN Invocations can be reconciled")
        if self._quota is None:
            raise ValueError("Invocation has no quota admission authority")
        settlement = await self._quota.reconcile(invocation_id, usage)
        status = InvocationStatus.COMPLETED if usage is not None else InvocationStatus.FAILED
        return await self._terminalize(
            invocation,
            status,
            usage=usage,
            error=error or (None if usage is not None else "provider proved no effect occurred"),
            quota=_settled_evidence(invocation.quota, settlement),
        )

    async def _terminalize(
        self,
        invocation: Invocation,
        status: InvocationStatus,
        *,
        result: Any | None = None,
        error: str | None = None,
        usage: InvocationUsage | None = None,
        quota: InvocationQuotaEvidence | None = None,
    ) -> Invocation:
        terminal = invocation.model_copy(
            update={
                "status": status,
                "result": result,
                "usage": usage,
                "error": error,
                "finished_at": datetime.now(UTC),
                **({"quota": quota} if quota is not None else {}),
            }
        )
        return await self._store.save(terminal)

    async def _settle(
        self,
        reservation: QuotaReservation | None,
        outcome: QuotaOutcome,
        usage: InvocationUsage | None = None,
    ) -> QuotaSettlement | None:
        if self._quota is None or reservation is None:
            return None
        return await self._quota.settle(reservation.invocation_id, outcome, usage)


def _reserved_evidence(reservation: QuotaReservation) -> InvocationQuotaEvidence:
    return InvocationQuotaEvidence(
        scope_key=reservation.scope_key,
        workspace_id=reservation.workspace_id,
        project_id=reservation.project_id,
        principal_id=reservation.principal_id,
        provider=reservation.provider,
        capability=reservation.capability,
        state="reserved",
        reserved=reservation.amount.as_dict(),
    )


def _settled_evidence(
    prior: InvocationQuotaEvidence | None,
    settlement: QuotaSettlement | None,
) -> InvocationQuotaEvidence | None:
    if settlement is None:
        return prior
    if prior is None:
        return None
    state = {
        QuotaOutcome.COMPLETED: "committed",
        QuotaOutcome.FAILED: "rolled_back",
        QuotaOutcome.UNKNOWN: "uncertain",
    }[settlement.outcome]
    return prior.model_copy(
        update={
            "state": state,
            "final": settlement.final.as_dict() if settlement.final is not None else None,
        }
    )


__all__ = [
    "CapabilityUnavailable",
    "EffectNotApplied",
    "InMemoryInvocationStore",
    "Invocation",
    "InvocationExecutionService",
    "InvocationQuotaEvidence",
    "InvocationStatus",
    "InvocationStore",
    "InvocationUsage",
    "ProviderExecutor",
    "ProviderResolver",
    "UnsafeEffectRetry",
    "UsageExtractor",
]
