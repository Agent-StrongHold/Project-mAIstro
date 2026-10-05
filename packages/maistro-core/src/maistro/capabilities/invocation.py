"""Canonical Binding -> Invocation external-effect boundary.

An Invocation is one actual provider call beneath an Attempt. ``effect_key`` is
stable across retries of the same logical NodeRun so recovery can distinguish a
known completed effect from an outcome that is unsafe to repeat.

Generic provider exceptions are deliberately recorded as ``UNKNOWN`` rather
than retryable failure: an exception can arrive after the remote system has
already committed the side effect. A provider/adapter may raise
:class:`EffectNotApplied` only when it can prove no external effect occurred.

The container composes this service for capability-effect consumers, and its
governed wrapper through :mod:`maistro.capabilities.effect_context`. A provider
call is admitted, recorded, and reconciled here; no caller may mutate Invocation
rows directly. Ephemeral contexts still use the in-memory store, while
configured SQLite/PostgreSQL containers use the durable capability Invocation
stores, so the effect-key ledger is the retry authority rather than a
node-local convention.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from maistro.capabilities.binding import Binding, ResolvedBinding, ResolvedCapabilityProvider
from maistro.capabilities.types import Unavailable
from maistro.quota.invocation_quota import measured_usage_amounts

logger = logging.getLogger("maistro.capabilities.invocation")


def _id() -> str:
    return uuid4().hex


def _utc(value: datetime) -> datetime:
    """Read a naive timestamp as UTC; every writer here records UTC.

    Discovery compares persisted timestamps with a caller's cutoff, and a
    naive value on either side (a caller's ``datetime.now()``, a row an older
    writer stored without an offset) made that comparison raise instead of
    returning the ambiguous work it exists to find (#1118 review).
    """
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


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
        if self.cost_cents is not None and (
            self.cost_cents < 0 or not math.isfinite(self.cost_cents)
        ):
            raise ValueError("cost_cents must be finite and nonnegative")
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
        # `workspace_id`/`project_id` are deliberately not required: an
        # Invocation written before scope was persisted (pre-#1118 rows) has
        # none to give, and refusing its audit record would leave it with no
        # recovery path at all (#1118 review). The Invocation itself is
        # backfilled from the operator's scope on manual reconciliation.
        for field in (
            "source",
            "actor",
            "reason",
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
    # Recovered accounting for a call that succeeded before the process died
    # (#1118 review): without it an APPLIED reconciliation leaves `usage`
    # unset and downstream cost attribution under-reports a real call.
    usage: InvocationUsage | None = None

    @model_validator(mode="after")
    def _validate_evidence(self) -> InvocationReconciliationEvidence:
        for field in ("source", "actor", "reason"):
            _require(getattr(self, field), field)
        return self


def _correlate_scope(invocation: Invocation) -> None:
    """Default scope from the resolved Binding, then enforce correlation.

    Scope correlation is mandatory whenever the resolved Binding carries
    scope -- which every admission since #1133 does, because Binding itself
    requires a non-empty workspace. Rows written before scope correlation
    (empty on both sides) stay deserializable so they can still be reconciled
    instead of stranding durable evidence.
    """

    if not invocation.workspace_id:
        invocation.workspace_id = invocation.binding.workspace_id
    if not invocation.project_id:
        invocation.project_id = invocation.binding.project_id
    if invocation.binding.workspace_id:
        _require(invocation.workspace_id, "workspace_id")
        if invocation.workspace_id != invocation.binding.workspace_id:
            raise ValueError("Invocation workspace_id does not match its resolved Binding")
    if invocation.binding.project_id:
        _require(invocation.project_id, "project_id")
        if invocation.project_id != invocation.binding.project_id:
            raise ValueError("Invocation project_id does not match its resolved Binding")


class Invocation(BaseModel):
    """One actual provider call beneath one physical Attempt."""

    model_config = ConfigDict(extra="forbid")

    invocation_id: str = Field(default_factory=_id)
    run_id: str
    node_run_id: str
    attempt_id: str
    workspace_id: str = ""
    project_id: str = ""
    # Principal the quota door attributes this physical effect to. Empty when
    # the caller has no actor; budget matching treats that as "system".
    actor_id: str = ""
    binding: ResolvedBinding
    effect_key: str
    # Persisted replay-scope discriminator (#1194): when True this Invocation
    # is one logical effect for the whole Run -- admission, dedup, and the
    # unsafe-retry guard key on (run_id, binding_id, effect_key) across every
    # physical NodeRun -- so a concurrent retry under a new NodeRun collides
    # with the canonical row instead of double-dispatching. Ordinary
    # capability effects keep their physical per-NodeRun scope.
    logical_effect: bool = False
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
        _correlate_scope(self)
        if self.revision < 0:
            raise ValueError("revision cannot be negative")
        terminal = self.status in TERMINAL_INVOCATION_STATUSES
        if terminal and self.finished_at is None:
            raise ValueError("terminal Invocation requires finished_at")
        if not terminal and self.finished_at is not None:
            raise ValueError("non-terminal Invocation cannot have finished_at")
        for field in ("created_at", "started_at", "finished_at"):
            value = getattr(self, field)
            if value is not None and value.tzinfo is None:
                object.__setattr__(self, field, _utc(value))
        return self


def _settled_by_another_admission(
    candidate: Invocation, admitted: Invocation, effect_key: str
) -> Invocation | None:
    """What it means when admission returns a row we did not write.

    `_admit_effect` can hand back a pre-existing canonical row: another
    worker won the same logical effect. COMPLETED is a replay, returned
    without touching the provider again. A non-terminal row under a
    different invocation_id is the unsafe case -- the remote outcome cannot
    be proven absent, so dispatching again could apply the effect twice.
    `None` means our own candidate was admitted and dispatch proceeds.

    Extracted from `invoke` rather than left inline: it is one question about
    the admission result, and folding its two branches into the caller pushed
    `invoke` from C(13) to C(14) against the complexity ratchet without
    making either half easier to read.
    """

    if admitted.status is InvocationStatus.COMPLETED:
        return admitted
    non_terminal = {
        InvocationStatus.CREATED,
        InvocationStatus.RUNNING,
        InvocationStatus.UNKNOWN,
    }
    if admitted.status in non_terminal and admitted.invocation_id != candidate.invocation_id:
        raise UnsafeEffectRetry(
            f"effect {effect_key!r} has outcome {admitted.status.value!r}; "
            "manual/reconciliation evidence is required before retry"
        )
    return None


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
        node_run_id: str | None,
        binding_id: str,
        effect_key: str,
    ) -> list[Invocation]: ...

    async def list_ambiguous(self, *, stale_before: datetime) -> list[Invocation]: ...


@runtime_checkable
class EffectClaimStore(Protocol):
    """Optional atomic claim used by multi-worker durable Invocation stores."""

    async def claim(self, invocation: Invocation) -> Invocation: ...


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
                _same_admission_effect(item, invocation)
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
        node_run_id: str | None,
        binding_id: str,
        effect_key: str,
    ) -> list[Invocation]:
        return [
            item.model_copy(deep=True)
            for item in sorted(self._items.values(), key=lambda candidate: candidate.created_at)
            if item.run_id == run_id
            and (node_run_id is None or item.node_run_id == node_run_id)
            and item.binding.binding_id == binding_id
            and item.effect_key == effect_key
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

    async def claim(self, invocation: Invocation) -> Invocation:
        """Atomically claim an effect when contexts share this store."""
        async with self._lock:
            history = [
                item
                for item in sorted(self._items.values(), key=lambda candidate: candidate.created_at)
                # develop replaced Invocation.effect_identity with this helper,
                # which widens the comparison for a logical effect (#1194).
                if _same_admission_effect(item, invocation)
            ]
            if history and history[-1].status is not InvocationStatus.FAILED:
                return history[-1].model_copy(deep=True)
            if invocation.invocation_id in self._items:
                raise ValueError(f"Invocation {invocation.invocation_id!r} already exists")
            persisted = invocation.model_copy(deep=True)
            self._items[persisted.invocation_id] = persisted
            return persisted.model_copy(deep=True)


class EffectNotApplied(RuntimeError):
    """Provider proves the requested external effect definitely did not occur."""


class StaleInvocationUpdate(RuntimeError):
    """A completion/reconciliation was based on an obsolete Invocation copy."""


class UnsafeEffectRetry(RuntimeError):
    """Recovery cannot safely repeat an effect whose outcome may already exist."""


def _same_admission_effect(stored: Invocation, candidate: Invocation) -> bool:
    """One admission identity for two Invocations (#1194).

    A logical-effect Invocation is admitted against the Run-scoped identity
    ``(run_id, binding_id, effect_key)`` -- spanning every physical NodeRun --
    while an ordinary capability effect stays scoped to its own NodeRun
    visit. Either side opting into the logical scope widens the comparison,
    so a retry that carries a new NodeRun cannot be admitted beside the
    canonical row still recording the same logical effect.
    """
    if (
        stored.run_id,
        stored.binding.binding_id,
        stored.effect_key,
    ) != (
        candidate.run_id,
        candidate.binding.binding_id,
        candidate.effect_key,
    ):
        return False
    if stored.logical_effect or candidate.logical_effect:
        return True
    return stored.node_run_id == candidate.node_run_id


class CapabilityUnavailable(RuntimeError):
    """A Binding could not resolve an eligible provider."""


ProviderResolver = Callable[
    [Binding],
    Awaitable[ResolvedCapabilityProvider | Unavailable],
]
ProviderExecutor = Callable[[ResolvedCapabilityProvider, Any], Awaitable[Any]]
UsageExtractor = Callable[[Any], "InvocationUsage | None"]


class InvocationQuota(Protocol):
    """Accounting collaborator at the sole physical Invocation boundary.

    A reservation must commit before dispatch. Observation is idempotent and
    preserves holds for missing usage or unknown outcomes. Implementations
    finish an in-flight reservation transaction before propagating cancellation.
    """

    async def reserve(self, invocation: Invocation, binding: Binding) -> None: ...

    async def observe(self, invocation: Invocation) -> None: ...


# Shared across service instances in one worker so a second composition root
# cannot reconcile a dispatch that is still running in the first one.
_PROCESS_ACTIVE_DISPATCHES: set[str] = set()


def _require_scope(invocation: Invocation, *, workspace_id: str, project_id: str) -> None:
    """Refuse a caller whose scope is not the Invocation's own.

    The Invocation's persisted scope wins, then its Binding's. A row that
    carries neither was written before scope was persisted; the caller's
    scope is accepted for it (and backfilled by the settlement), because the
    alternative is a row with no recovery path at all.
    """
    expected_workspace = invocation.workspace_id or invocation.binding.workspace_id
    expected_project = invocation.project_id or invocation.binding.project_id
    if (expected_workspace and workspace_id != expected_workspace) or (
        expected_project and project_id != expected_project
    ):
        raise ValueError("reconciliation scope does not match the Invocation")


def _settlement_fields(
    disposition: ReconciliationDisposition,
    *,
    result: Any | None,
    reason: str,
    usage: InvocationUsage | None,
) -> dict[str, Any]:
    """The terminal status fields one reconciliation disposition projects.

    `APPLIED` completes the physical effect (adopting its result and, when the
    provider reported one, its usage); `NOT_APPLIED` fails it with the
    settlement reason; `INDETERMINATE` records the reason and leaves the
    lifecycle where it is.
    """
    if disposition is ReconciliationDisposition.APPLIED:
        fields: dict[str, Any] = {
            "status": InvocationStatus.COMPLETED,
            "result": result,
            "error": None,
            "finished_at": datetime.now(UTC),
        }
        if usage is not None:
            fields["usage"] = usage
        return fields
    if disposition is ReconciliationDisposition.NOT_APPLIED:
        return {
            "status": InvocationStatus.FAILED,
            "error": reason,
            "finished_at": datetime.now(UTC),
        }
    return {"error": reason}


@runtime_checkable
class ProviderReconciliationAdapter(Protocol):
    """Provider-specific evidence seam; it cannot mutate Invocation state."""

    async def reconcile(self, invocation: Invocation) -> InvocationReconciliationEvidence: ...


# Installed once by the composition root (see `effect_context`): every
# terminal physical effect — completed directly, or settled `APPLIED` by a
# reconciliation — crosses this hook so quota evidence is recorded by the
# Invocation authority itself, never by a per-caller response callback.
InvocationCompletionHook = Callable[["Invocation"], Awaitable[None]]


class InvocationExecutionService:
    """Resolve one Binding, persist one provider call, and guard effect retries.

    The service is the lifecycle authority for capability effects. Provider
    adapters can report evidence, but only this service changes Invocation
    state.
    """

    def __init__(
        self,
        *,
        store: InvocationStore,
        quota: InvocationQuota | None = None,
        on_completed: InvocationCompletionHook | None = None,
    ) -> None:
        self._store = store
        # One quota authority for every strategy. Callers cannot pass a
        # per-invoke override that would fork admission.
        self._quota = quota
        self._on_completed = on_completed
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
        logical_effect: bool = False,
    ) -> Invocation | None:
        """Return the latest canonical Invocation for one logical effect identity."""

        # Only an executable EFFECT_KEY contract may widen history across
        # NodeRuns; ordinary capability keys remain physical-visit scoped.
        history = await self._store.list_effect(
            run_id=run_id,
            node_run_id=None if logical_effect else node_run_id,
            binding_id=binding.binding_id,
            effect_key=effect_key,
        )
        return history[-1] if history else None

    async def _admit_effect(self, candidate: Invocation) -> Invocation:
        """Record one physical effect admission, deduplicating across workers.

        Stores that expose an atomic ``claim`` (``EffectClaimStore``) serialize
        the logical effect at the ledger itself; plain stores rely on the
        durable unique-effect constraint in ``create``. Either way, a loser of
        an admission race re-reads the canonical row so a stale admission
        returns the accepted result instead of dispatching or surfacing a
        misleading race error.

        The re-read honours the candidate's own scope: a logical effect reads
        its whole Run history, so a completed row under a different NodeRun is
        a replay rather than a race error (#1194).
        """

        try:
            return (
                await self._store.claim(candidate)
                if isinstance(self._store, EffectClaimStore)
                else await self._store.create(candidate)
            )
        except UnsafeEffectRetry:
            replay = await self._completed_replay_after_admission_race(
                run_id=candidate.run_id,
                node_run_id=candidate.node_run_id,
                binding_id=candidate.binding.binding_id,
                effect_key=candidate.effect_key,
                logical_effect=candidate.logical_effect,
            )
            if replay is not None:
                return replay
            raise

    async def _repair_quota(self, invocation: Invocation) -> None:
        """Re-apply a terminal fact. Observation is absolute, not another charge."""

        if self._quota is not None and invocation.status in {
            InvocationStatus.COMPLETED,
            InvocationStatus.FAILED,
            InvocationStatus.UNKNOWN,
        }:
            await self._quota.observe(invocation)

    async def _notify_completion(self, completed: Invocation) -> None:
        """Hand a completed effect to the composition-root usage recorder.

        A recorder failure is isolated rather than raised: the physical effect
        is already terminal, so failing the caller now would misreport its
        outcome and could drive a duplicate physical call under attempt retry.
        The recorder marks an Invocation recorded only after its writes
        succeed, so the next hand-out of the same completed effect re-confirms
        evidence and repairs the ledger. The failure is surfaced as an error
        event -- it is never swallowed silently (#718).
        """

        if completed.status is not InvocationStatus.COMPLETED:
            return
        if (on_completed := self._on_completed) is None:
            return
        try:
            await on_completed(completed)
        except Exception as exc:
            logger.error(
                "quota evidence recording failed for %s (effect %s, provider %s): %s",
                completed.invocation_id,
                completed.effect_key,
                completed.binding.provider_name,
                exc,
            )

    async def _prior_effect(self, history: list[Invocation], effect_key: str) -> Invocation | None:
        """Replay a completed effect or refuse an outcome that is not FAILED."""

        if not history:
            return None
        latest = history[-1]
        if latest.status is InvocationStatus.COMPLETED:
            return await self._repair_outcome_evidence(latest)
        if latest.status is InvocationStatus.FAILED:
            await self._repair_quota(latest)
        if latest.status in {
            InvocationStatus.CREATED,
            InvocationStatus.RUNNING,
            InvocationStatus.UNKNOWN,
        }:
            raise UnsafeEffectRetry(
                f"effect {effect_key!r} has outcome {latest.status.value!r}; "
                "manual/reconciliation evidence is required before retry"
            )
        return None

    async def _completed_replay_after_admission_race(
        self,
        *,
        run_id: str,
        node_run_id: str,
        # The id, not the binding. The only caller holds a candidate
        # Invocation, whose `binding` is the persisted `ResolvedBinding`
        # snapshot rather than the live `Binding`; annotating this `Binding`
        # made the one real call site a type error while the body reads
        # nothing but `binding_id`, which both models carry.
        binding_id: str,
        effect_key: str,
        logical_effect: bool = False,
    ) -> Invocation | None:
        """Re-read canonical history after an admission race with another worker.

        Another worker may have completed the effect between our initial
        history read and the store-level admission guard. Returns the accepted
        completed Invocation, or None when the race outcome is not a replay.
        The re-read uses the caller's scope: a logical effect re-reads its
        whole Run history, so a completed canonical row under a different
        NodeRun is a replay rather than a re-raised race error (#1194).

        A replay found here is a terminal fact the quota ledger has not yet
        observed in this process, so it repairs and notifies on the way out
        exactly as `_prior_effect` does.
        """
        latest_history = await self._store.list_effect(
            run_id=run_id,
            node_run_id=None if logical_effect else node_run_id,
            binding_id=binding_id,
            effect_key=effect_key,
        )
        if latest_history and latest_history[-1].status is InvocationStatus.COMPLETED:
            latest = latest_history[-1]
            return await self._repair_outcome_evidence(latest)
        return None

    async def _run_provider(
        self,
        invocation: Invocation,
        provider: Any,
        request: Any,
        executor: ProviderExecutor,
        usage_from: UsageExtractor | None,
    ) -> Invocation:
        """Dispatch one admitted Invocation and terminalize whatever comes back."""

        try:
            result = await executor(provider, request)
        except EffectNotApplied as exc:
            await self._terminalize(invocation, InvocationStatus.FAILED, error=str(exc))
            raise
        except asyncio.CancelledError:
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

        try:
            usage = usage_from(result) if usage_from is not None else None
            if usage is not None and not isinstance(usage, InvocationUsage):
                raise TypeError("usage extractor must return InvocationUsage or None")
        except (Exception, asyncio.CancelledError):
            await self._terminalize(
                invocation,
                InvocationStatus.COMPLETED,
                result=result,
                error="provider completed but usage extraction failed",
            )
            raise
        return await self._terminalize(
            invocation,
            InvocationStatus.COMPLETED,
            result=result,
            usage=usage,
        )

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
        actor_id: str = "",
        logical_effect: bool = False,
    ) -> Invocation:
        """Execute one effect, deduplicating or blocking unsafe recovery.

        A completed prior Invocation for the same logical effect is returned
        without another provider call. ``CREATED``, ``RUNNING``, or ``UNKNOWN``
        history blocks repetition because the remote outcome cannot be proven
        absent. Only a prior ``FAILED`` record, produced by ``EffectNotApplied``,
        is eligible for a new physical Invocation under a later Attempt.

        Admission is atomic against the same scope the caller declared: with
        ``logical_effect=True`` the persisted discriminator makes the store's
        admission guard Run-scoped across NodeRuns, so two workers racing a
        retry under different NodeRuns cannot both dispatch (#1194).
        """

        _require(effect_key, "effect_key")
        async with self._effect_lock:
            # An EFFECT_KEY node opts into a stable Run/node identity; all
            # other capability effects stay scoped to their physical NodeRun.
            history = await self._store.list_effect(
                run_id=run_id,
                node_run_id=None if logical_effect else node_run_id,
                binding_id=binding.binding_id,
                effect_key=effect_key,
            )
            if (prior := await self._prior_effect(history, effect_key)) is not None:
                return prior

            provider = await resolver(binding)
            if isinstance(provider, Unavailable):
                raise CapabilityUnavailable(
                    f"capability {binding.capability!r} unavailable: {provider.reason}"
                )
            resolved = ResolvedBinding.from_provider(binding, provider)
            candidate = Invocation(
                run_id=run_id,
                node_run_id=node_run_id,
                attempt_id=attempt_id,
                workspace_id=binding.workspace_id,
                project_id=binding.project_id,
                actor_id=actor_id,
                binding=resolved,
                effect_key=effect_key,
                request=request,
                logical_effect=logical_effect,
            )
            invocation = await self._admit_effect(candidate)
            settled = _settled_by_another_admission(candidate, invocation, effect_key)
            if settled is not None:
                # The ledger already holds this effect's accepted outcome,
                # written by whichever worker won admission. Re-notify (#718):
                # the recorder and the durable tracker are idempotent on
                # Invocation identity, so a healthy ledger sees a no-op and one
                # that missed the original terminalization is repaired.
                return await self._repair_outcome_evidence(settled)
            try:
                # The reservation sits inside the admitted effect, after the
                # dedup above: a loser of the admission race must not charge
                # quota for a physical call it will never make.
                if self._quota is not None:
                    await self._quota.reserve(invocation, binding)
                running = invocation.model_copy(
                    update={
                        "status": InvocationStatus.RUNNING,
                        "started_at": datetime.now(UTC),
                        "dispatch_active": True,
                    }
                )
                invocation = await self._store.save(running)
            except BaseException:
                # The physical executor has not been entered. Persist proof of
                # non-dispatch before releasing any quota reservation. A quota
                # denial stays FAILED so a later attempt can be admitted, and
                # the denial evidence itself is not rewritten into a release.
                await self._terminalize(
                    invocation,
                    InvocationStatus.FAILED,
                    error="provider dispatch did not start",
                )
                raise
            self._active_dispatches.add(invocation.invocation_id)
            _PROCESS_ACTIVE_DISPATCHES.add(invocation.invocation_id)

        try:
            return await self._run_provider(invocation, provider, request, executor, usage_from)
        finally:
            self._active_dispatches.discard(invocation.invocation_id)
            _PROCESS_ACTIVE_DISPATCHES.discard(invocation.invocation_id)

    async def discover_ambiguous(self, *, stale_before: datetime) -> list[Invocation]:
        """List evidence-requiring effects without changing their state."""

        return await self._store.list_ambiguous(stale_before=_utc(stale_before))

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
        usage: InvocationUsage | None = None,
    ) -> Invocation:
        """Apply operator/provider evidence through the Invocation authority.

        ``NOT_APPLIED`` deliberately becomes the same ``FAILED`` state produced
        by :class:`EffectNotApplied`; the normal effect lock then gates the next
        physical retry. No stale ``RUNNING`` row is changed merely because it is
        old, and absent evidence can only record another blocked state.

        The caller's scope is checked before anything is returned: a terminal
        Invocation from another Workspace/Project is not disclosed through the
        idempotent early return (#1118 review).
        """

        disposition = ReconciliationDisposition(disposition)
        cutoff = _utc(stale_before) if stale_before is not None else None
        async with self._effect_lock:
            invocation = await self._store.get(invocation_id)
            if invocation is None:
                raise KeyError(f"Invocation {invocation_id!r} does not exist")
            _require_scope(invocation, workspace_id=workspace_id, project_id=project_id)
            if invocation.status is InvocationStatus.COMPLETED:
                return await self._repair_outcome_evidence(invocation)
            if invocation.status is InvocationStatus.FAILED:
                return await self._repair_outcome_evidence(invocation)
            self._require_reconcilable(invocation, cutoff)
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
                usage=usage,
            )

    def _require_reconcilable(self, invocation: Invocation, cutoff: datetime | None) -> None:
        """Refuse to settle a dispatch that may still be running."""

        invocation_id = invocation.invocation_id
        if invocation_id in _PROCESS_ACTIVE_DISPATCHES:
            raise UnsafeEffectRetry(
                f"Invocation {invocation_id!r} is still being dispatched; "
                "reconciliation must wait for physical completion"
            )
        began = invocation.started_at or invocation.created_at
        if invocation.dispatch_active and (cutoff is None or began > cutoff):
            raise UnsafeEffectRetry(
                f"Invocation {invocation_id!r} is still being dispatched; stale evidence is required"
            )
        if invocation.status is InvocationStatus.RUNNING and (cutoff is None or began > cutoff):
            raise UnsafeEffectRetry(
                f"Invocation {invocation_id!r} is still live; stale evidence is required"
            )
        if invocation.status not in {
            InvocationStatus.CREATED,
            InvocationStatus.RUNNING,
            InvocationStatus.UNKNOWN,
        }:
            raise UnsafeEffectRetry(f"Invocation {invocation_id!r} is not reconciliation-eligible")

    async def reconcile_with_provider(
        self,
        invocation_id: str,
        adapter: ProviderReconciliationAdapter,
        *,
        stale_before: datetime | None = None,
    ) -> Invocation:
        """Ask a provider adapter for evidence, retaining lifecycle authority here.

        The adapter is consulted *outside* the effect lock: a slow or hanging
        provider endpoint must not block every unrelated Invocation on this
        service (#1118 review). Eligibility is checked under the lock before
        the lookup, and the report is applied under the lock only if the row
        is still at the revision the adapter saw -- anything that moved it in
        between (a completion, another reconciliation) makes the evidence
        stale, and stale evidence is refused rather than applied.
        """

        cutoff = _utc(stale_before) if stale_before is not None else None
        async with self._effect_lock:
            snapshot = await self._store.get(invocation_id)
            if snapshot is None:
                raise KeyError(f"Invocation {invocation_id!r} does not exist")
            if snapshot.status in {InvocationStatus.COMPLETED, InvocationStatus.FAILED}:
                return await self._repair_outcome_evidence(snapshot)
            self._require_reconcilable(snapshot, cutoff)

        try:
            report = await adapter.reconcile(snapshot)
        except Exception as exc:
            report = InvocationReconciliationEvidence(
                disposition=ReconciliationDisposition.INDETERMINATE,
                source="provider-adapter",
                actor="system",
                reason=f"reconciliation adapter failed: {type(exc).__name__}",
            )

        async with self._effect_lock:
            current = await self._store.get(invocation_id)
            if current is None:
                raise KeyError(f"Invocation {invocation_id!r} does not exist")
            if current.status in {InvocationStatus.COMPLETED, InvocationStatus.FAILED}:
                return await self._repair_outcome_evidence(current)
            if current.revision != snapshot.revision:
                raise UnsafeEffectRetry(
                    f"Invocation {invocation_id!r} changed while the provider was consulted; "
                    "the evidence is stale, reconcile again"
                )
            return await self._reconcile_locked(current, report)

    async def _reconcile_locked(
        self,
        invocation: Invocation,
        report: InvocationReconciliationEvidence,
    ) -> Invocation:
        """Apply an adapter report while the effect lock is held."""

        if invocation.status in {InvocationStatus.COMPLETED, InvocationStatus.FAILED}:
            return await self._repair_outcome_evidence(invocation)
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
            usage=report.usage,
        )

    async def _repair_outcome_evidence(self, invocation: Invocation) -> Invocation:
        """Repair downstream evidence before reporting a durable outcome as complete.

        Lifecycle persistence and quota/usage recording are separate commits.
        A prior failure between them must be repairable through reconciliation
        itself, without another provider call or another history entry.
        """
        await self._repair_quota(invocation)
        await self._notify_completion(invocation)
        return invocation

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
        usage: InvocationUsage | None = None,
    ) -> Invocation:
        """Shared implementation for provider reports and operator resolutions."""

        # Re-entering through reconcile would deadlock; keep the guarded state
        # transition in one helper so adapters cannot become lifecycle owners.
        disposition = ReconciliationDisposition(disposition)
        if disposition is not ReconciliationDisposition.INDETERMINATE and evidence is None:
            raise ValueError("applied/not_applied reconciliation requires evidence")
        if disposition is ReconciliationDisposition.APPLIED:
            measured_usage_amounts(usage if usage is not None else invocation.usage)
        _require_scope(invocation, workspace_id=workspace_id, project_id=project_id)
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
        update = _reconciled_update(
            invocation,
            audit=audit,
            disposition=disposition,
            reason=reason,
            workspace_id=workspace_id,
            project_id=project_id,
            result=result,
            usage=usage,
        )
        try:
            settled = await self._store.save(invocation.model_copy(update=update))
        except StaleInvocationUpdate:
            current = await self._store.get(invocation.invocation_id)
            if current is None:
                raise
            return await self._repair_outcome_evidence(current)
        return await self._repair_outcome_evidence(settled)

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
            persisted = await self._store.save(terminal)
        except StaleInvocationUpdate:
            current = await self._store.get(invocation.invocation_id)
            if current is None:
                raise
            return await self._repair_outcome_evidence(current)
        return await self._repair_outcome_evidence(persisted)


def _reconciled_update(
    invocation: Invocation,
    *,
    audit: InvocationReconciliation,
    disposition: ReconciliationDisposition,
    reason: str,
    workspace_id: str,
    project_id: str,
    result: Any | None,
    usage: InvocationUsage | None,
) -> dict[str, Any]:
    """The fields one reconciliation writes onto the Invocation row.

    Pure, so the guarded transition above stays a single readable sequence --
    validate, build, save, repair. The history and scope half lives here; the
    terminal status half is `_settlement_fields`, which arrived from the same
    refactor on the other side of this branch's merge. Composing them rather
    than keeping both was the merge's job and it did not get done: the two
    carried identical disposition logic and only this one was called, which
    is how vulture found the other dead.
    """

    update: dict[str, Any] = {
        "reconciliation_history": (*invocation.reconciliation_history, audit),
        "dispatch_active": False,
    }
    # A pre-scope row learns its scope from the evidence that settles it.
    if not invocation.workspace_id and workspace_id:
        update["workspace_id"] = workspace_id
    if not invocation.project_id and project_id:
        update["project_id"] = project_id
    update.update(_settlement_fields(disposition, result=result, reason=reason, usage=usage))
    return update


__all__ = [
    "CapabilityUnavailable",
    "EffectClaimStore",
    "EffectNotApplied",
    "InMemoryInvocationStore",
    "Invocation",
    "InvocationCompletionHook",
    "InvocationExecutionService",
    "InvocationQuota",
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
