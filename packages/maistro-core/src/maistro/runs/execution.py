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

from maistro.runs.model import AcceptedNodeOutcome, Attempt, AttemptStatus, NodeRun
from maistro.runs.reconciliation import (
    AttemptLifecycleReconciler,
    AttemptLifecycleStore,
    CancellationCause,
)
from maistro.runs.store import RunIntegrityError
from maistro.runtime import ExecutionCallable, ExecutionRuntime, RuntimeDeadlineExceeded

AttemptReconciler = Callable[[Attempt], Awaitable[None]]
AttemptContextFactory = Callable[[Attempt, Any], Any]


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
    ) -> None:
        self._store = store
        self._runtime = runtime
        self._lifecycle = AttemptLifecycleReconciler(store)
        self._after_reconcile = reconciler

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

        try:
            result = await self._runtime.execute(
                work_item,
                runtime_context,
                execution_id=attempt.attempt_id,
                executor=executor,
                timeout_s=timeout_s,
            )
        except asyncio.CancelledError as exc:
            terminal = await self._terminalize(
                attempt.attempt_id,
                AttemptStatus.CANCELLED,
                fencing_token=token,
                result=attempt_evidence_of(exc),
                error="execution cancelled",
            )
            # REQUESTED: this coroutine was cancelled while running, which means
            # something asked the work to stop. The NodeRun is terminal, not
            # parked awaiting a retry decision that has already been taken
            # (#230). Recovery's cancellations reconcile elsewhere and keep the
            # parking default.
            await self._reconcile(terminal, cancellation=CancellationCause.REQUESTED)
            raise
        except RuntimeDeadlineExceeded as exc:
            terminal = await self._terminalize(
                attempt.attempt_id,
                AttemptStatus.TIMED_OUT,
                fencing_token=token,
                result=attempt_evidence_of(exc),
                error=str(exc),
            )
            await self._reconcile(terminal)
            raise
        except Exception as exc:
            terminal = await self._terminalize(
                attempt.attempt_id,
                AttemptStatus.FAILED,
                fencing_token=token,
                result=attempt_evidence_of(exc),
                error=str(exc),
            )
            await self._reconcile(terminal)
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
    "AttemptContextFactory",
    "AttemptExecutionService",
    "AttemptExecutionStore",
    "AttemptReconciler",
    "CarriesAttemptEvidence",
    "attempt_evidence_of",
]
