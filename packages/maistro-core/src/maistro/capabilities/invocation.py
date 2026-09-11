"""Canonical Binding -> Invocation external-effect boundary.

An Invocation is one actual provider call beneath an Attempt. ``effect_key`` is
stable across retries of the same logical NodeRun so recovery can distinguish a
known completed effect from an outcome that is unsafe to repeat.

Generic provider exceptions are deliberately recorded as ``UNKNOWN`` rather
than retryable failure: an exception can arrive after the remote system has
already committed the side effect. A provider/adapter may raise
:class:`EffectNotApplied` only when it can prove no external effect occurred.

The container composes this service for capability-effect consumers. A
provider call is admitted, recorded, and reconciled here; no caller may mutate
Invocation rows directly. Ephemeral contexts still use the in-memory store,
while configured SQLite/PostgreSQL containers use the durable capability
Invocation stores.
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


class ReconciliationDisposition(StrEnum):
    """Evidence-backed disposition for an ambiguous provider call."""

    APPLIED = "applied"
    NOT_APPLIED = "not_applied"
    INDETERMINATE = "indeterminate"


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


class InvocationReconciliation(BaseModel):
    """Durable audit evidence for one attempted ambiguity resolution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    disposition: ReconciliationDisposition
    source: str
    actor: str
    reason: str
    evidence: Any | None = None
    result: Any | None = None
    workspace_id: str
    project_id: str
    run_id: str
    node_run_id: str
    attempt_id: str
    invocation_id: str
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def _validate_reconciliation(self) -> InvocationReconciliation:
        for field in (
            "source",
            "actor",
            "reason",
            "workspace_id",
            "project_id",
            "run_id",
            "node_run_id",
            "attempt_id",
            "invocation_id",
        ):
            _require(getattr(self, field), field)
        return self


class InvocationReconciliationEvidence(BaseModel):
    """Provider-adapter report, before the lifecycle service applies it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    disposition: ReconciliationDisposition
    source: str
    actor: str
    reason: str
    evidence: Any | None = None
    result: Any | None = None

    @model_validator(mode="after")
    def _validate_evidence(self) -> InvocationReconciliationEvidence:
        for field in ("source", "actor", "reason"):
            _require(getattr(self, field), field)
        return self


class Invocation(BaseModel):
    """One actual provider call beneath one physical Attempt."""

    model_config = ConfigDict(extra="forbid")

    invocation_id: str = Field(default_factory=_id)
    run_id: str
    node_run_id: str
    attempt_id: str
    workspace_id: str = ""
    project_id: str = ""
    binding: ResolvedBinding
    effect_key: str
    status: InvocationStatus = InvocationStatus.CREATED
    request: Any | None = None
    result: Any | None = None
    usage: InvocationUsage | None = None
    error: str | None = None
    reconciliation_history: tuple[InvocationReconciliation, ...] = ()
    # Monotonic compare-and-swap token for terminalization/reconciliation.
    # It prevents a late provider completion from overwriting an operator's
    # evidence-backed disposition.
    revision: int = 0
    dispatch_active: bool = False
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
        if self.revision < 0:
            raise ValueError("revision cannot be negative")
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

    async def list_ambiguous(self, *, stale_before: datetime) -> list[Invocation]: ...


class InMemoryInvocationStore:
    """Concurrency-safe in-memory InvocationStore for tests/local execution."""

    def __init__(self) -> None:
        self._items: dict[str, Invocation] = {}
        self._lock = asyncio.Lock()

    async def create(self, invocation: Invocation) -> Invocation:
        async with self._lock:
            if invocation.invocation_id in self._items:
                raise ValueError(f"Invocation {invocation.invocation_id!r} already exists")
            if any(
                item.effect_identity == invocation.effect_identity
                and item.status
                in {
                    InvocationStatus.CREATED,
                    InvocationStatus.RUNNING,
                    InvocationStatus.COMPLETED,
                    InvocationStatus.UNKNOWN,
                }
                for item in self._items.values()
            ):
                raise UnsafeEffectRetry(
                    f"effect {invocation.effect_key!r} already has an active or completed Invocation"
                )
            persisted = invocation.model_copy(deep=True)
            self._items[persisted.invocation_id] = persisted
            return persisted.model_copy(deep=True)

    async def get(self, invocation_id: str) -> Invocation | None:
        item = self._items.get(invocation_id)
        return item.model_copy(deep=True) if item is not None else None

    async def save(self, invocation: Invocation) -> Invocation:
        async with self._lock:
            current = self._items.get(invocation.invocation_id)
            if current is None:
                raise KeyError(f"Invocation {invocation.invocation_id!r} does not exist")
            if current.revision != invocation.revision:
                raise StaleInvocationUpdate(
                    f"Invocation {invocation.invocation_id!r} was updated concurrently"
                )
            persisted = invocation.model_copy(update={"revision": current.revision + 1}, deep=True)
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

    async def list_ambiguous(self, *, stale_before: datetime) -> list[Invocation]:
        return [
            item.model_copy(deep=True)
            for item in sorted(self._items.values(), key=lambda candidate: candidate.created_at)
            if item.status is InvocationStatus.UNKNOWN
            or (
                item.status in {InvocationStatus.CREATED, InvocationStatus.RUNNING}
                and (item.started_at or item.created_at) <= stale_before
            )
        ]


class EffectNotApplied(RuntimeError):
    """Provider proves the requested external effect definitely did not occur."""


class StaleInvocationUpdate(RuntimeError):
    """A completion/reconciliation was based on an obsolete Invocation copy."""


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

# Shared across service instances in one worker so a second composition root
# cannot reconcile a dispatch that is still running in the first one.
_PROCESS_ACTIVE_DISPATCHES: set[str] = set()


@runtime_checkable
class ProviderReconciliationAdapter(Protocol):
    """Provider-specific evidence seam; it cannot mutate Invocation state."""

    async def reconcile(self, invocation: Invocation) -> InvocationReconciliationEvidence: ...


class InvocationExecutionService:
    """Resolve one Binding, persist one provider call, and guard effect retries.

    The service is the lifecycle authority for capability effects. Provider
    adapters can report evidence, but only this service changes Invocation
    state.
    """

    def __init__(self, *, store: InvocationStore) -> None:
        self._store = store
        self._effect_lock = asyncio.Lock()
        # This process-local guard closes the window where an operator could
        # settle a dispatch that is still executing in any service instance in
        # this worker. Durable CAS and the persisted dispatch marker cover
        # process boundaries and crash recovery.
        self._active_dispatches: set[str] = set()

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
            try:
                invocation = await self._store.create(
                    Invocation(
                        run_id=run_id,
                        node_run_id=node_run_id,
                        attempt_id=attempt_id,
                        workspace_id=binding.workspace_id,
                        project_id=binding.project_id,
                        binding=resolved,
                        effect_key=effect_key,
                        request=request,
                    )
                )
            except UnsafeEffectRetry:
                # Another worker may have completed the effect after our
                # initial history read. Re-read the canonical row so a stale
                # admission returns the accepted result instead of dispatching
                # or surfacing a misleading race error.
                latest_history = await self._store.list_effect(
                    run_id=run_id,
                    node_run_id=node_run_id,
                    binding_id=binding.binding_id,
                    effect_key=effect_key,
                )
                if latest_history and latest_history[-1].status is InvocationStatus.COMPLETED:
                    return latest_history[-1]
                raise
            running = invocation.model_copy(
                update={
                    "status": InvocationStatus.RUNNING,
                    "started_at": datetime.now(UTC),
                    "dispatch_active": True,
                }
            )
            invocation = await self._store.save(running)
            self._active_dispatches.add(invocation.invocation_id)
            _PROCESS_ACTIVE_DISPATCHES.add(invocation.invocation_id)

        try:
            try:
                result = await executor(provider, request)
            except EffectNotApplied as exc:
                await self._terminalize(
                    invocation,
                    InvocationStatus.FAILED,
                    error=str(exc),
                )
                raise
            except asyncio.CancelledError:
                # Cancellation after provider dispatch has indeterminate external
                # outcome unless the slot-specific adapter proves otherwise.
                await self._terminalize(
                    invocation,
                    InvocationStatus.UNKNOWN,
                    error="provider invocation cancelled with unknown external outcome",
                )
                raise
            except Exception as exc:
                await self._terminalize(
                    invocation,
                    InvocationStatus.UNKNOWN,
                    error=str(exc) or type(exc).__name__,
                )
                raise

            usage = usage_from(result) if usage_from is not None else None
            return await self._terminalize(
                invocation,
                InvocationStatus.COMPLETED,
                result=result,
                usage=usage,
            )
        finally:
            self._active_dispatches.discard(invocation.invocation_id)
            _PROCESS_ACTIVE_DISPATCHES.discard(invocation.invocation_id)

    async def discover_ambiguous(self, *, stale_before: datetime) -> list[Invocation]:
        """List evidence-requiring effects without changing their state."""

        return await self._store.list_ambiguous(stale_before=stale_before)

    async def reconcile(
        self,
        invocation_id: str,
        *,
        disposition: ReconciliationDisposition,
        source: str,
        actor: str,
        reason: str,
        evidence: Any | None,
        workspace_id: str,
        project_id: str,
        result: Any | None = None,
        stale_before: datetime | None = None,
    ) -> Invocation:
        """Apply operator/provider evidence through the Invocation authority.

        ``NOT_APPLIED`` deliberately becomes the same ``FAILED`` state produced
        by :class:`EffectNotApplied`; the normal effect lock then gates the next
        physical retry. No stale ``RUNNING`` row is changed merely because it is
        old, and absent evidence can only record another blocked state.
        """

        disposition = ReconciliationDisposition(disposition)
        async with self._effect_lock:
            invocation = await self._store.get(invocation_id)
            if invocation is None:
                raise KeyError(f"Invocation {invocation_id!r} does not exist")
            if invocation.status is InvocationStatus.COMPLETED:
                return invocation
            if invocation.status is InvocationStatus.FAILED:
                return invocation
            if invocation.invocation_id in _PROCESS_ACTIVE_DISPATCHES:
                raise UnsafeEffectRetry(
                    f"Invocation {invocation_id!r} is still being dispatched; "
                    "reconciliation must wait for physical completion"
                )
            if invocation.dispatch_active and (
                stale_before is None
                or (invocation.started_at or invocation.created_at) > stale_before
            ):
                raise UnsafeEffectRetry(
                    f"Invocation {invocation_id!r} is still being dispatched; "
                    "stale evidence is required"
                )
            if invocation.status is InvocationStatus.RUNNING and (
                stale_before is None
                or (invocation.started_at or invocation.created_at) > stale_before
            ):
                raise UnsafeEffectRetry(
                    f"Invocation {invocation_id!r} is still live; stale evidence is required"
                )
            if invocation.status not in {
                InvocationStatus.CREATED,
                InvocationStatus.RUNNING,
                InvocationStatus.UNKNOWN,
            }:
                raise UnsafeEffectRetry(
                    f"Invocation {invocation_id!r} is not reconciliation-eligible"
                )
            return await self._reconcile_values_locked(
                invocation,
                disposition=disposition,
                source=source,
                actor=actor,
                reason=reason,
                evidence=evidence,
                workspace_id=workspace_id,
                project_id=project_id,
                result=result,
            )

    async def reconcile_with_provider(
        self,
        invocation_id: str,
        adapter: ProviderReconciliationAdapter,
        *,
        stale_before: datetime | None = None,
    ) -> Invocation:
        """Ask a provider adapter for evidence, retaining lifecycle authority here."""

        async with self._effect_lock:
            invocation = await self._store.get(invocation_id)
            if invocation is None:
                raise KeyError(f"Invocation {invocation_id!r} does not exist")
            if invocation.invocation_id in _PROCESS_ACTIVE_DISPATCHES:
                raise UnsafeEffectRetry(
                    f"Invocation {invocation_id!r} is still being dispatched; "
                    "reconciliation must wait for physical completion"
                )
            if invocation.dispatch_active and (
                stale_before is None
                or (invocation.started_at or invocation.created_at) > stale_before
            ):
                raise UnsafeEffectRetry(
                    f"Invocation {invocation_id!r} is still being dispatched; "
                    "stale evidence is required"
                )
            if invocation.status is InvocationStatus.RUNNING and (
                stale_before is None
                or (invocation.started_at or invocation.created_at) > stale_before
            ):
                raise UnsafeEffectRetry(
                    f"Invocation {invocation_id!r} is still live; stale evidence is required"
                )
            try:
                report = await adapter.reconcile(invocation)
            except Exception as exc:
                report = InvocationReconciliationEvidence(
                    disposition=ReconciliationDisposition.INDETERMINATE,
                    source="provider-adapter",
                    actor="system",
                    reason=f"reconciliation adapter failed: {type(exc).__name__}",
                )
            return await self._reconcile_locked(invocation, report)

    async def _reconcile_locked(
        self,
        invocation: Invocation,
        report: InvocationReconciliationEvidence,
    ) -> Invocation:
        """Apply an adapter report while the effect lock is held."""

        if invocation.status in {InvocationStatus.COMPLETED, InvocationStatus.FAILED}:
            return invocation
        return await self._reconcile_values_locked(
            invocation,
            disposition=report.disposition,
            source=report.source,
            actor=report.actor,
            reason=report.reason,
            evidence=report.evidence,
            workspace_id=invocation.workspace_id or invocation.binding.workspace_id,
            project_id=invocation.project_id or invocation.binding.project_id,
            result=report.result,
        )

    async def _reconcile_values_locked(
        self,
        invocation: Invocation,
        *,
        disposition: ReconciliationDisposition,
        source: str,
        actor: str,
        reason: str,
        evidence: Any | None,
        workspace_id: str,
        project_id: str,
        result: Any | None,
    ) -> Invocation:
        """Shared implementation for provider reports and operator resolutions."""

        # Re-entering through reconcile would deadlock; keep the guarded state
        # transition in one helper so adapters cannot become lifecycle owners.
        disposition = ReconciliationDisposition(disposition)
        if disposition is not ReconciliationDisposition.INDETERMINATE and evidence is None:
            raise ValueError("applied/not_applied reconciliation requires evidence")
        expected_workspace = invocation.workspace_id or invocation.binding.workspace_id
        expected_project = invocation.project_id or invocation.binding.project_id
        if workspace_id != expected_workspace or project_id != expected_project:
            raise ValueError("reconciliation scope does not match the Invocation")
        audit = InvocationReconciliation(
            disposition=disposition,
            source=source,
            actor=actor,
            reason=reason,
            evidence=evidence,
            result=result,
            workspace_id=workspace_id,
            project_id=project_id,
            run_id=invocation.run_id,
            node_run_id=invocation.node_run_id,
            attempt_id=invocation.attempt_id,
            invocation_id=invocation.invocation_id,
        )
        update: dict[str, Any] = {
            "reconciliation_history": (*invocation.reconciliation_history, audit),
            "dispatch_active": False,
        }
        if disposition is ReconciliationDisposition.APPLIED:
            update.update(
                status=InvocationStatus.COMPLETED,
                result=result,
                error=None,
                finished_at=datetime.now(UTC),
            )
        elif disposition is ReconciliationDisposition.NOT_APPLIED:
            update.update(
                status=InvocationStatus.FAILED,
                error=reason,
                finished_at=datetime.now(UTC),
            )
        else:
            update["error"] = reason
        try:
            return await self._store.save(invocation.model_copy(update=update))
        except StaleInvocationUpdate:
            current = await self._store.get(invocation.invocation_id)
            if current is None:
                raise
            return current

    async def _terminalize(
        self,
        invocation: Invocation,
        status: InvocationStatus,
        *,
        result: Any | None = None,
        error: str | None = None,
        usage: InvocationUsage | None = None,
    ) -> Invocation:
        terminal = invocation.model_copy(
            update={
                "status": status,
                "result": result,
                "usage": usage,
                "error": error,
                "finished_at": datetime.now(UTC),
                "dispatch_active": False,
            }
        )
        try:
            return await self._store.save(terminal)
        except StaleInvocationUpdate:
            current = await self._store.get(invocation.invocation_id)
            if current is None:
                raise
            return current


__all__ = [
    "CapabilityUnavailable",
    "EffectNotApplied",
    "InMemoryInvocationStore",
    "Invocation",
    "InvocationExecutionService",
    "InvocationReconciliation",
    "InvocationReconciliationEvidence",
    "InvocationStatus",
    "InvocationStore",
    "InvocationUsage",
    "ProviderExecutor",
    "ProviderReconciliationAdapter",
    "ProviderResolver",
    "ReconciliationDisposition",
    "StaleInvocationUpdate",
    "UnsafeEffectRetry",
    "UsageExtractor",
]
