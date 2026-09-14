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
import contextlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, Protocol, runtime_checkable

from maistro.observability.correlation import bind_execution_context
from maistro.runs.model import (
    PAUSE_AWAITS_HUMAN,
    TERMINAL_ATTEMPT_STATUSES,
    TERMINAL_RUN_STATUSES,
    AcceptedNodeOutcome,
    Attempt,
    AttemptStatus,
    NodeRun,
    RunStatus,
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


async def _active_run_attempts(store: AttemptExecutionStore, run_id: str) -> list[Attempt]:
    """Every non-terminal Attempt under one Run, in node-run then attempt order."""
    return [
        attempt
        for node_run in await store.list_node_runs(run_id)
        for attempt in await store.list_attempts(node_run.node_run_id)
        if attempt.status not in TERMINAL_ATTEMPT_STATUSES
    ]


async def _cancel_settled_node_runs(store: AttemptExecutionStore, run_id: str) -> None:
    """Cancel node runs whose Attempts have all settled (queue-only Nodes)."""
    for node_run in await store.list_node_runs(run_id):
        if node_run.status in TERMINAL_RUN_STATUSES:
            continue
        attempts = await store.list_attempts(node_run.node_run_id)
        if any(attempt.status not in TERMINAL_ATTEMPT_STATUSES for attempt in attempts):
            continue
        await store.transition_node_run(
            node_run.node_run_id,
            RunStatus.CANCELLED,
            error="execution cancelled",
        )


class AttemptExecutionService:
    """Execute physical Attempts while keeping lifecycle authority in domain code.

    The small process-local index is only a signal path to the owner of live
    physical work. Durable Run/Attempt state remains authoritative, so a
    restarted process can inspect the record but cannot claim that it stopped a
    worker it does not own.
    """

    _active_services: ClassVar[dict[str, AttemptExecutionService]] = {}

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
        # Serializes the small claim-to-launch window with cancellation. The
        # lock is released as soon as Runtime has its own active task, so it
        # never blocks cancellation while provider work is running.
        self._launch_lock = asyncio.Lock()

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
        """Execute one physical Attempt under the canonical correlation context.

        This wrapper exists only to own the correlation scope. `node_run_id` is
        known here; `attempt_id` is not known until the Attempt is persisted
        several awaits later, so the stack is handed down and the inner method
        pushes the second binding onto it when it has something true to say.
        Unwinding here rather than there means both bindings end with the try,
        including on the paths that re-raise.

        `context_factory` still exists and still does its own thing: it attaches
        canonical ids to the *domain's* execution context object, which is what
        the executor receives as an argument. This is the ambient context, which
        is what the executor's logs, spans and events read without being handed
        anything. Neither replaces the other.

        See :meth:`_execute_attempt` for the ordering this delegates to.
        """
        with contextlib.ExitStack() as correlation:
            correlation.enter_context(bind_execution_context(node_run_id=node_run_id))
            return await self._execute_attempt(
                node_run_id,
                work_item,
                execution_context,
                executor=executor,
                executor_id=executor_id,
                runtime_id=runtime_id,
                timeout_s=timeout_s,
                resume_checkpoint_id=resume_checkpoint_id,
                reconcile_logical=reconcile_logical,
                context_factory=context_factory,
                prior_completion_accepted=prior_completion_accepted,
                correlation=correlation,
            )

    async def _execute_attempt(
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
        correlation: contextlib.ExitStack,
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

        # Persist physical recovery evidence before logical state claims that
        # execution is active (#544). If the process dies after this point, the
        # ordinary lease sweep has an Attempt to reclaim.
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
        lease = attempt.execution_lease
        if lease is None:
            raise RunIntegrityError("claimed Attempt is missing its execution lease")
        token = lease.fencing_token
        if attempt.status not in {AttemptStatus.CREATED, AttemptStatus.RUNNING}:
            raise RunIntegrityError("execute_claimed requires an active Attempt")

        with contextlib.ExitStack() as correlation:
            correlation.enter_context(bind_execution_context(node_run_id=attempt.node_run_id))
            correlation.enter_context(bind_execution_context(attempt_id=attempt.attempt_id))
            heartbeat: asyncio.Task[None] | None = None
            runtime_task: asyncio.Task[Any] | None = None
            self._active_services[attempt.attempt_id] = self
            try:
                attempt, runtime_task, heartbeat = await self._launch_claimed(
                    attempt,
                    work_item,
                    execution_context,
                    executor=executor,
                    timeout_s=timeout_s,
                    context_factory=context_factory,
                    token=token,
                )
                result = await runtime_task
            except ExecutionYielded as exc:
                terminal, settled = await self._terminalize_if_open(
                    attempt.attempt_id,
                    AttemptStatus.YIELDED,
                    fencing_token=token,
                    result=exc.as_result(),
                )
                if settled:
                    await self._reconcile(terminal)
                return terminal
            except (asyncio.CancelledError, RuntimeDeadlineExceeded, Exception) as exc:
                if runtime_task is not None and not runtime_task.done():
                    runtime_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await runtime_task
                status, cause, error = _failure_disposition(exc)
                terminal, settled = await self._terminalize_if_open(
                    attempt.attempt_id,
                    status,
                    fencing_token=token,
                    result=attempt_evidence_of(exc),
                    error=error,
                )
                if settled:
                    await self._reconcile(terminal, cancellation=cause)
                raise
            else:
                return await self._settle_provider_success(
                    attempt,
                    fencing_token=token,
                    result=result,
                    reconcile_logical=reconcile_logical,
                )
            finally:
                await self._stop_heartbeat(heartbeat)
                self._active_services.pop(attempt.attempt_id, None)

    async def _settle_provider_success(
        self,
        attempt: Attempt,
        *,
        fencing_token: str,
        result: Any,
        reconcile_logical: bool,
    ) -> Attempt:
        """Publish a provider success — unless the durable Run fence forbids it.

        The durable Run transition is the cancellation fence. A provider that
        won the local task race cannot publish a stale successful Attempt
        after that fence: its success is converted to a cancelled Attempt
        instead, and the executor unwinds as cancelled.
        """
        current_node = await self._store.get_node_run(attempt.node_run_id)
        current_run = (
            await self._store.get_run(current_node.run_id) if current_node is not None else None
        )
        if current_run is not None and current_run.status is RunStatus.CANCELLED:
            terminal, settled = await self._terminalize_if_open(
                attempt.attempt_id,
                AttemptStatus.CANCELLED,
                fencing_token=fencing_token,
                error="execution cancelled by Run fence",
            )
            if settled:
                await self._reconcile(terminal, cancellation=CancellationCause.REQUESTED)
            raise asyncio.CancelledError
        terminal, settled = await self._terminalize_if_open(
            attempt.attempt_id,
            AttemptStatus.COMPLETED,
            fencing_token=fencing_token,
            result=result,
        )
        if settled and reconcile_logical:
            await self._reconcile(terminal)
        return terminal

    async def _claim_active_attempt(self, attempt: Attempt, *, token: str) -> Attempt:
        """Re-read and claim the Attempt as RUNNING, refusing terminal states.

        ``asyncio.CancelledError`` propagates for an already-cancelled Attempt
        so the caller's cleanup path records cancellation rather than an
        integrity failure; every other non-active state is an integrity error.
        """
        persisted_attempt = await self._store.get_attempt(attempt.attempt_id)
        if persisted_attempt is None:
            raise RunIntegrityError(f"Attempt {attempt.attempt_id!r} disappeared before launch")
        if persisted_attempt.status in TERMINAL_ATTEMPT_STATUSES:
            if persisted_attempt.status is AttemptStatus.CANCELLED:
                raise asyncio.CancelledError
            raise RunIntegrityError("execute_claimed requires an active Attempt")
        attempt = persisted_attempt
        if attempt.status is AttemptStatus.CREATED:
            attempt = await self._store.transition_attempt(
                attempt.attempt_id,
                AttemptStatus.RUNNING,
                fencing_token=token,
            )
        elif attempt.status is not AttemptStatus.RUNNING:
            raise RunIntegrityError("execute_claimed requires an active Attempt")
        return attempt

    async def _require_active_run_for_launch(self, node_run_id: str) -> None:
        """Refuse to launch under a Run that already reached a terminal state."""
        current_node = await self._store.get_node_run(node_run_id)
        current_run = (
            await self._store.get_run(current_node.run_id) if current_node is not None else None
        )
        if current_run is not None and current_run.status in TERMINAL_RUN_STATUSES:
            raise asyncio.CancelledError

    async def _launch_claimed(
        self,
        attempt: Attempt,
        work_item: Any,
        execution_context: Any,
        *,
        executor: ExecutionCallable,
        timeout_s: float | None,
        context_factory: AttemptContextFactory | None,
        token: str,
    ) -> tuple[Attempt, asyncio.Task[Any], asyncio.Task[None] | None]:
        """Claim and start Runtime without crossing a cancellation fence."""
        heartbeat: asyncio.Task[None] | None = None
        runtime_task: asyncio.Task[Any] | None = None
        try:
            async with self._launch_lock:
                attempt = await self._claim_active_attempt(attempt, token=token)
                await self._require_active_run_for_launch(attempt.node_run_id)
                runtime_context = _materialize_execution_context(
                    attempt,
                    execution_context,
                    context_factory,
                )
                heartbeat = self._start_heartbeat(attempt.attempt_id, token)
                runtime_task = asyncio.create_task(
                    self._runtime.execute(
                        work_item,
                        runtime_context,
                        execution_id=attempt.attempt_id,
                        executor=executor,
                        timeout_s=timeout_s,
                    )
                )
                # Runtime registers its execution before its first await.
                # Yield once while holding the launch lock so cancellation
                # either sees that owner or waits for this launch to finish.
                await asyncio.sleep(0)
            assert runtime_task is not None
            return attempt, runtime_task, heartbeat
        except BaseException:
            if runtime_task is not None and not runtime_task.done():
                runtime_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await runtime_task
            await self._stop_heartbeat(heartbeat)
            raise

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

    @classmethod
    async def cancel_registered(cls, attempt_id: str) -> bool:
        """Cancel the local owner and persist a pre-launch cancellation."""
        service = cls._active_services.get(attempt_id)
        if service is None:
            return False
        return await service._cancel_local_attempt(attempt_id)

    async def cancel(self, attempt_id: str) -> bool:
        return await self.cancel_registered(attempt_id)

    async def _cancel_local_attempt(self, attempt_id: str) -> bool:
        async with self._launch_lock:
            attempt = await self._store.get_attempt(attempt_id)
            if attempt is None:
                return False
            if attempt.status in TERMINAL_ATTEMPT_STATUSES:
                return attempt.status is AttemptStatus.CANCELLED
            cancelled = await self._runtime.cancel(attempt_id)
            if cancelled:
                return True
            lease = attempt.execution_lease
            if lease is None:
                raise RunIntegrityError("active Attempt is missing its execution lease")
            terminal = await self._terminalize(
                attempt_id,
                AttemptStatus.CANCELLED,
                fencing_token=lease.fencing_token,
                error="execution cancelled before Runtime launch",
            )
        await self._reconcile(terminal, cancellation=CancellationCause.REQUESTED)
        return True

    @classmethod
    async def cancel_registered_run(cls, run_id: str) -> bool:
        """Cancel the local owner of a Run, including its durable projection."""
        owners: set[AttemptExecutionService] = set()
        for service in set(cls._active_services.values()):
            run = await service._store.get_run(run_id)
            if run is not None:
                owners.add(service)
        for service in owners:
            await service._cancel_local_run(run_id)
        return bool(owners)

    async def _cancel_local_run(self, run_id: str) -> None:
        async with self._launch_lock:
            active = await _active_run_attempts(self._store, run_id)
            current_run = await self._store.get_run(run_id)
            if current_run is None:
                raise RunIntegrityError(f"Run {run_id!r} does not exist")
            if current_run.status is not RunStatus.CANCELLED:
                await self._store.transition_run(
                    run_id, RunStatus.CANCELLED, error="execution cancelled"
                )
            await asyncio.gather(*(self._runtime.cancel(attempt.attempt_id) for attempt in active))
            await _cancel_settled_node_runs(self._store, run_id)

    async def _terminalize_if_open(
        self,
        attempt_id: str,
        status: AttemptStatus,
        *,
        fencing_token: str,
        result: object | None = None,
        error: str | None = None,
    ) -> tuple[Attempt, bool]:
        """Transition an open Attempt; report whether THIS call settled it.

        ``True`` means this call wrote the terminal status and therefore owns
        the reconciliation that follows it. ``False`` means the Attempt was
        already terminal: another authority — crash reclamation, a run-level
        cancel, the pre-launch fence — settled the durable record and applied
        its own disposition. Reconciling that record again here would override
        the settled answer with this task's view of why the work stopped: a
        reclaimed Attempt's NodeRun would turn wrongly terminal instead of
        staying parked for the policy that owns the retry decision
        (ADR-082526-b36a).
        """
        current = await self._store.get_attempt(attempt_id)
        if current is None:
            raise RunIntegrityError(f"Attempt {attempt_id!r} disappeared during execution")
        if current.status in TERMINAL_ATTEMPT_STATUSES:
            return current, False
        return (
            await self._terminalize(
                attempt_id,
                status,
                fencing_token=fencing_token,
                result=result,
                error=error,
            ),
            True,
        )

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
