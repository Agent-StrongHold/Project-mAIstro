"""Canonical Attempt -> ExecutionRuntime execution seam.

This service owns the domain-side ordering around one physical try: prepare the
logical Run/NodeRun, create and persist the Attempt, mark it running, invoke
Runtime using ``attempt_id`` as the physical execution identity, and persist the
terminal physical outcome. Simple callers may retain default logical
reconciliation; richer domains may defer acceptance and assign the logical
NodeRun disposition themselves. Runtime never mutates Run/NodeRun state.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, runtime_checkable

from maistro.runs.model import (
    PAUSE_AWAITS_HUMAN,
    AcceptedNodeOutcome,
    Attempt,
    AttemptStatus,
    NodeRun,
)
from maistro.runs.reconciliation import (
    AttemptLifecycleReconciler,
    AttemptLifecycleStore,
    CancellationCause,
)
from maistro.runs.store import RunIntegrityError
from maistro.runtime import (
    ExecutionCallable,
    ExecutionPaused,
    ExecutionRuntime,
    RuntimeDeadlineExceeded,
)

AttemptReconciler = Callable[[Attempt], Awaitable[None]]
AttemptContextFactory = Callable[[Attempt, Any], Any]


class ExecutionYielded(ExecutionPaused):
    """The work paused rather than finishing or failing.

    A wait or HITL node that returns successfully with ``status="paused"`` has
    not failed, and recording it as a failure loses the two things a pause is
    for: what it waits on, and when to come back. `AttemptStatus.YIELDED` is
    the physical outcome the canonical model already had for this -- it was
    simply never produced by anything.

    Carrying the disposition on an exception rather than a return value is
    deliberate: it is the same seam `RuntimeDeadlineExceeded` uses, so the
    generic Runtime keeps knowing nothing about wait or HITL semantics.

    It subclasses `ExecutionPaused` so that Runtime can count the pause without
    learning what it waits on (#642). Runtime's broad `except Exception` had no
    way to tell a deliberate stop from a crash, so every successful pause was
    recorded as a failed execution -- the same defect this class fixes one level
    up, in the record the migration decision is actually read from.
    """

    def __init__(self, *, awaits_human: bool = False, evidence: object = None) -> None:
        super().__init__("execution yielded")
        self.awaits_human = awaits_human
        self.evidence = evidence

    def as_result(self) -> dict[str, object]:
        """The JSON-safe record persisted on the yielded Attempt."""
        record: dict[str, object] = {PAUSE_AWAITS_HUMAN: self.awaits_human}
        if isinstance(self.evidence, dict):
            record.update(self.evidence)
        elif self.evidence is not None:
            record["evidence"] = self.evidence
        return record


@runtime_checkable
class CarriesAttemptEvidence(Protocol):
    """An exception that knows what its failed execution managed to do.

    An executor that fails may attach JSON-safe evidence to the exception it
    raises. Without it a failed Attempt records only the exception text, so a
    domain whose failures carry partial work — files written before the error, a
    rejected draft answer — loses that half of the record precisely where an
    audit or a retry goes looking for it.

    A Protocol rather than a `getattr` probe, so the attribute is a real
    reference that static analysis can see and a domain can be type-checked
    against.
    """

    attempt_evidence: object


def attempt_evidence_of(exc: BaseException) -> object | None:
    """Evidence a raising executor attached to its failure, or None.

    Read rather than required: the runtime treats results as opaque, so it can
    offer the slot without any domain having to fill it.
    """
    if isinstance(exc, CarriesAttemptEvidence):
        return exc.attempt_evidence
    return None


def _failure_disposition(
    exc: BaseException,
) -> tuple[AttemptStatus, CancellationCause, str]:
    """The physical outcome, cancellation meaning and recorded error for `exc`.

    `CancellationCause.REQUESTED` for a cancelled coroutine: something asked the
    work to stop, so the NodeRun is terminal rather than parked awaiting a retry
    decision that has already been taken (#230). Recovery's own cancellations
    reconcile elsewhere and keep the parking default.
    """
    if isinstance(exc, asyncio.CancelledError):
        return AttemptStatus.CANCELLED, CancellationCause.REQUESTED, "execution cancelled"
    if isinstance(exc, RuntimeDeadlineExceeded):
        return AttemptStatus.TIMED_OUT, CancellationCause.RECOVERED, str(exc)
    return AttemptStatus.FAILED, CancellationCause.RECOVERED, str(exc)


def _materialize_execution_context(
    attempt: Attempt,
    execution_context: Any,
    context_factory: AttemptContextFactory | None,
) -> Any:
    if context_factory is None:
        return execution_context
    return context_factory(attempt, execution_context)


@runtime_checkable
class AttemptExecutionStore(AttemptLifecycleStore, Protocol):
    async def create_attempt(
        self,
        node_run_id: str,
        *,
        runtime_id: str = "python",
        executor_id: str = "",
        deadline_at: datetime | None = None,
        resume_checkpoint_id: str | None = None,
        lease_holder: str | None = None,
        lease_ttl: timedelta | None = None,
    ) -> Attempt: ...

    async def renew_lease(
        self,
        attempt_id: str,
        *,
        fencing_token: str,
        ttl: timedelta,
        at: datetime | None = None,
    ) -> Attempt: ...

    async def list_attempts(self, node_run_id: str) -> list[Attempt]: ...

    async def transition_attempt(
        self,
        attempt_id: str,
        target: AttemptStatus,
        *,
        at: datetime | None = None,
        result: object | None = None,
        error: str | None = None,
        metrics: dict[str, object] | None = None,
        fencing_token: str | None = None,
    ) -> Attempt: ...


class AttemptExecutionService:
    """Execute physical Attempts while keeping lifecycle authority in domain code."""

    def __init__(
        self,
        *,
        store: AttemptExecutionStore,
        runtime: ExecutionRuntime,
        reconciler: AttemptReconciler | None = None,
        lease_ttl: timedelta | None = None,
    ) -> None:
        """``lease_ttl`` opts this executor's Attempts into crash recovery.

        When set, every Attempt this service creates carries an expiring lease
        and is renewed from *this process* while the executor runs. If the
        process dies, the renewals stop with it, the lease lapses, and
        `reclaim_expired_attempts` settles the Attempt (ADR-082526-b36a).

        Left None, an Attempt's lease never expires and is never reclaimable —
        exactly today's behaviour, which is what makes the opt-in additive.
        """
        if lease_ttl is not None and lease_ttl <= timedelta(0):
            raise ValueError("lease_ttl must be positive")
        self._store = store
        self._runtime = runtime
        self._lifecycle = AttemptLifecycleReconciler(store)
        self._after_reconcile = reconciler
        self._lease_ttl = lease_ttl

    def _start_heartbeat(self, attempt_id: str, token: str) -> asyncio.Task[None] | None:
        """Renew this Attempt's lease from this process while the executor runs.

        Returns None when no TTL was configured, which is the default and means
        no heartbeat and no reclamation.

        The cadence is a third of the TTL, so two consecutive missed renewals
        are needed before the lease lapses — one lost tick under load must not
        look like a dead worker (ADR-082526-b36a).

        Liveness is exactly what this proves: the task runs *in* this process,
        so if the process dies the heartbeat dies with it and the lease lapses
        on its own. Nothing has to notice the death.
        """
        ttl = self._lease_ttl
        if ttl is None:
            return None

        async def _beat() -> None:
            interval = ttl.total_seconds() / 3
            while True:
                await asyncio.sleep(interval)
                try:
                    await self._store.renew_lease(attempt_id, fencing_token=token, ttl=ttl)
                except Exception:
                    # The Attempt may have terminalized under us, or the store
                    # may be briefly unavailable. Neither is this task's problem
                    # to solve: stop renewing and let the lease lapse, which is
                    # the same outcome as the process dying and is safe.
                    return

        return asyncio.create_task(_beat())

    @staticmethod
    async def _stop_heartbeat(heartbeat: asyncio.Task[None] | None) -> None:
        """Stop renewing. Idempotent, and never raises into the caller's path."""
        if heartbeat is None:
            return
        heartbeat.cancel()
        try:
            await heartbeat
        except (asyncio.CancelledError, Exception):
            return

    async def execute(
        self,
        node_run_id: str,
        work_item: Any,
        execution_context: Any,
        *,
        executor: ExecutionCallable,
        executor_id: str = "",
        runtime_id: str | None = None,
        timeout_s: float | None = None,
        resume_checkpoint_id: str | None = None,
        reconcile_logical: bool = True,
        context_factory: AttemptContextFactory | None = None,
        prior_completion_accepted: bool = False,
    ) -> Attempt:
        """Create, run, terminalize, and optionally defer successful reconciliation.

        ``reconcile_logical=False`` allows Graph-like domains to interpret a
        successfully completed physical result themselves. It never suppresses
        reconciliation of cancellation, timeout, or failure. A deferred
        completion must be accepted before redispatch so recovery cannot repeat
        an external side effect whose physical outcome is already durable.

        ``context_factory`` runs only after the Attempt has been persisted and
        marked running. It lets a domain attach canonical ``attempt_id`` and
        related correlation data to its execution context without teaching the
        generic Runtime about Graph or capability semantics.

        ``prior_completion_accepted=True`` is a narrow continuation escape hatch
        for domains that can prove the latest completed Attempt was previously
        accepted and that new durable input now requires a fresh physical try.
        """
        await self._reject_unaccepted_completion(
            node_run_id,
            prior_completion_accepted=prior_completion_accepted,
        )

        deadline_at = None
        if timeout_s is not None:
            if timeout_s <= 0:
                raise ValueError("timeout_s must be > 0")
            deadline_at = datetime.now(UTC) + timedelta(seconds=timeout_s)

        runtime_name = runtime_id or type(self._runtime).__name__
        await self._lifecycle.prepare_execution(node_run_id)
        attempt = await self._store.create_attempt(
            node_run_id,
            runtime_id=runtime_name,
            executor_id=executor_id,
            deadline_at=deadline_at,
            resume_checkpoint_id=resume_checkpoint_id,
            lease_holder=executor_id or runtime_name,
            lease_ttl=self._lease_ttl,
        )
        lease = attempt.execution_lease
        if lease is None:
            raise RunIntegrityError("store-created Attempt is missing its execution lease")
        token = lease.fencing_token
        attempt = await self._store.transition_attempt(
            attempt.attempt_id,
            AttemptStatus.RUNNING,
            fencing_token=token,
        )
        runtime_context = _materialize_execution_context(
            attempt,
            execution_context,
            context_factory,
        )

        heartbeat = self._start_heartbeat(attempt.attempt_id, token)
        try:
            # Nested so the `finally` runs *before* any handler below: a renewal
            # landing between the executor stopping and the Attempt terminalizing
            # would race the terminal write, and the whole point of stopping is
            # that this process is done vouching for the work.
            try:
                result = await self._runtime.execute(
                    work_item,
                    runtime_context,
                    execution_id=attempt.attempt_id,
                    executor=executor,
                    timeout_s=timeout_s,
                )
            finally:
                await self._stop_heartbeat(heartbeat)
        except ExecutionYielded as exc:
            # Before the combined handler below, and it has to stay there:
            # `ExecutionYielded` is an `Exception`, so the broader clause would
            # catch it first and record a pause as a failure -- which is the
            # defect this whole change exists to remove.
            terminal = await self._terminalize(
                attempt.attempt_id,
                AttemptStatus.YIELDED,
                fencing_token=token,
                result=exc.as_result(),
            )
            # A pause is a disposition, not an error, so this returns where the
            # handler below re-raises. The reconciler reads the persisted result
            # to decide PAUSED against WAITING.
            await self._reconcile(terminal)
            return terminal
        except (asyncio.CancelledError, RuntimeDeadlineExceeded, Exception) as exc:
            # One handler, with the physical outcome as data. These were three
            # `except` blocks whose bodies differed only in the status and the
            # error text; separating the mapping from the writing keeps "which
            # status does this exception mean" reviewable in one place.
            status, cause, error = _failure_disposition(exc)
            terminal = await self._terminalize(
                attempt.attempt_id,
                status,
                fencing_token=token,
                result=attempt_evidence_of(exc),
                error=error,
            )
            await self._reconcile(terminal, cancellation=cause)
            raise

        terminal = await self._terminalize(
            attempt.attempt_id,
            AttemptStatus.COMPLETED,
            fencing_token=token,
            result=result,
        )
        if reconcile_logical:
            await self._reconcile(terminal)
        return terminal

    async def accept_outcome(self, outcome: AcceptedNodeOutcome) -> NodeRun:
        """Accept one persisted physical result with an explicit logical disposition."""
        return await self._lifecycle.accept_outcome(outcome)

    async def _reject_unaccepted_completion(
        self,
        node_run_id: str,
        *,
        prior_completion_accepted: bool = False,
    ) -> None:
        node_run = await self._store.get_node_run(node_run_id)
        if node_run is None:
            raise RunIntegrityError(f"NodeRun {node_run_id!r} does not exist")
        if node_run.accepted_outcome is not None:
            return
        attempts = await self._store.list_attempts(node_run_id)
        pending = next(
            (
                attempt
                for attempt in reversed(attempts)
                if attempt.status is AttemptStatus.COMPLETED
            ),
            None,
        )
        if pending is not None and not prior_completion_accepted:
            raise RunIntegrityError(
                "completed Attempt awaits domain acceptance; reconcile persisted evidence "
                "before redispatch"
            )

    async def cancel(self, attempt_id: str) -> bool:
        return await self._runtime.cancel(attempt_id)

    async def _terminalize(
        self,
        attempt_id: str,
        status: AttemptStatus,
        *,
        fencing_token: str,
        result: object | None = None,
        error: str | None = None,
    ) -> Attempt:
        return await self._store.transition_attempt(
            attempt_id,
            status,
            result=result,
            error=error,
            fencing_token=fencing_token,
        )

    async def _reconcile(
        self,
        attempt: Attempt,
        *,
        cancellation: CancellationCause = CancellationCause.RECOVERED,
    ) -> None:
        await self._lifecycle.reconcile(attempt, cancellation=cancellation)
        if self._after_reconcile is not None:
            await self._after_reconcile(attempt.model_copy(deep=True))


__all__ = [
    "PAUSE_AWAITS_HUMAN",
    "AttemptContextFactory",
    "AttemptExecutionService",
    "AttemptExecutionStore",
    "AttemptReconciler",
    "CarriesAttemptEvidence",
    "ExecutionYielded",
    "attempt_evidence_of",
]
