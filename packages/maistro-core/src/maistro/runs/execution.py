"""Canonical Attempt -> ExecutionRuntime execution seam.

This service owns the domain-side ordering around one physical try: persist the
physical Attempt lease before logical state claims execution, mark the Attempt
running, invoke Runtime using ``attempt_id`` as the physical execution identity,
and persist the terminal physical outcome. Simple callers may retain default
logical reconciliation; richer domains may defer acceptance and assign the
logical NodeRun disposition themselves. Runtime never mutates Run/NodeRun state.
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
    not failed. ``AttemptStatus.YIELDED`` is the physical disposition for that
    successful pause. Subclassing ``ExecutionPaused`` lets Runtime count the
    pause without learning what the domain is waiting for.
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
    """An exception that knows what its failed execution managed to do."""

    attempt_evidence: object


def attempt_evidence_of(exc: BaseException) -> object | None:
    """Evidence a raising executor attached to its failure, or None."""
    if isinstance(exc, CarriesAttemptEvidence):
        return exc.attempt_evidence
    return None


def _failure_disposition(
    exc: BaseException,
) -> tuple[AttemptStatus, CancellationCause, str]:
    """The physical outcome, cancellation meaning and recorded error for ``exc``."""
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
        if lease_ttl is not None and lease_ttl <= timedelta(0):
            raise ValueError("lease_ttl must be positive")
        self._store = store
        self._runtime = runtime
        self._lifecycle = AttemptLifecycleReconciler(store)
        self._after_reconcile = reconciler
        self._lease_ttl = lease_ttl

    def _start_heartbeat(self, attempt_id: str, token: str) -> asyncio.Task[None] | None:
        """Renew this Attempt's lease from this process while the executor runs."""
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
                    return

        return asyncio.create_task(_beat())

    @staticmethod
    async def _stop_heartbeat(heartbeat: asyncio.Task[None] | None) -> None:
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
        """Create, run and terminalize one physical Attempt.

        The Attempt and its lease are persisted before ``prepare_execution`` can
        move the containing Run/NodeRun into RUNNING. With a TTL that closes the
        crash window where logical durable state claimed work was active but the
        ordinary recovery sweep had no physical evidence to reclaim (#544).
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
        attempt = await self._store.create_attempt(
            node_run_id,
            runtime_id=runtime_name,
            executor_id=executor_id,
            deadline_at=deadline_at,
            resume_checkpoint_id=resume_checkpoint_id,
            lease_holder=executor_id or runtime_name,
            lease_ttl=self._lease_ttl,
        )
        if attempt.execution_lease is None:
            raise RunIntegrityError("store-created Attempt is missing its execution lease")

        await self._lifecycle.prepare_execution(node_run_id)
        return await self.execute_claimed(
            attempt,
            work_item,
            execution_context,
            executor=executor,
            timeout_s=timeout_s,
            reconcile_logical=reconcile_logical,
            context_factory=context_factory,
        )

    async def execute_claimed(
        self,
        attempt: Attempt,
        work_item: Any,
        execution_context: Any,
        *,
        executor: ExecutionCallable,
        timeout_s: float | None = None,
        reconcile_logical: bool = True,
        context_factory: AttemptContextFactory | None = None,
    ) -> Attempt:
        """Execute an Attempt whose consumer claim is already physically RUNNING.

        The consumer claim transaction persists Run, NodeRun and leased Attempt
        as RUNNING together. Nothing here repeats that claim. The CREATED branch
        remains only for compatibility with ordinary execution, which persists
        its Attempt before preparing logical execution and then enters this same
        Runtime, heartbeat, terminalization and reconciliation path.
        """
        lease = attempt.execution_lease
        if lease is None:
            raise RunIntegrityError("claimed Attempt is missing its execution lease")
        token = lease.fencing_token
        if attempt.status is AttemptStatus.CREATED:
            attempt = await self._store.transition_attempt(
                attempt.attempt_id,
                AttemptStatus.RUNNING,
                fencing_token=token,
            )
        elif attempt.status is not AttemptStatus.RUNNING:
            raise RunIntegrityError("execute_claimed requires an active Attempt")
        runtime_context = _materialize_execution_context(
            attempt,
            execution_context,
            context_factory,
        )

        heartbeat = self._start_heartbeat(attempt.attempt_id, token)
        try:
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
            terminal = await self._terminalize(
                attempt.attempt_id,
                AttemptStatus.YIELDED,
                fencing_token=token,
                result=exc.as_result(),
            )
            await self._reconcile(terminal)
            return terminal
        except (asyncio.CancelledError, RuntimeDeadlineExceeded, Exception) as exc:
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
