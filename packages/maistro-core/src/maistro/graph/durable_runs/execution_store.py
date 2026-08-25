"""RunStore-compatible lifecycle view over durable Graph persistence.

The durable Graph record already owns the canonical Run and NodeRuns. This
adapter keeps physical Attempts in that same optimistic-concurrency envelope so
AttemptExecutionService can operate without introducing a second lifecycle
store or dual-writing execution identity.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from maistro.runs.lifecycle import (
    lease_is_expired,
    reclaim_attempt,
    renew_attempt_lease,
    renewed_lease,
    transition_attempt,
    transition_node_run,
    transition_run,
)
from maistro.runs.model import (
    TERMINAL_RUN_STATUSES,
    AcceptedNodeOutcome,
    Attempt,
    AttemptStatus,
    ExecutionLease,
    NodeRun,
    Run,
    RunStatus,
)
from maistro.runs.store import (
    DEFAULT_RECLAIM_BATCH,
    ActiveAttemptExists,
    AttemptNotFound,
    RunIntegrityError,
    StaleExecutionFence,
)

from .protocol import DurableRunStore
from .types import DurableRunRecord


class DurableRunExecutionStore:
    """Expose canonical execution lifecycle operations for one durable Run."""

    def __init__(self, store: DurableRunStore, *, run_id: str) -> None:
        self._store = store
        self._run_id = run_id
        self._lock = asyncio.Lock()

    async def get_run(self, run_id: str) -> Run | None:
        if run_id != self._run_id:
            return None
        record = await self._store.get(self._run_id)
        return record.run.model_copy(deep=True) if record is not None else None

    async def transition_run(
        self,
        run_id: str,
        target: RunStatus,
        *,
        at: datetime | None = None,
        result: object | None = None,
        error: str | None = None,
    ) -> Run:
        self._require_run_id(run_id)
        updated = await self._mutate(
            lambda record: record.model_copy(
                update={
                    "run": transition_run(
                        record.run,
                        target,
                        at=at,
                        result=result,
                        error=error,
                    )
                }
            )
        )
        return updated.run.model_copy(deep=True)

    async def get_node_run(self, node_run_id: str) -> NodeRun | None:
        record = await self._get_record()
        node_run = next(
            (item for item in record.node_runs if item.node_run_id == node_run_id),
            None,
        )
        return node_run.model_copy(deep=True) if node_run is not None else None

    async def list_node_runs(self, run_id: str) -> list[NodeRun]:
        self._require_run_id(run_id)
        record = await self._get_record()
        return [node_run.model_copy(deep=True) for node_run in record.node_runs]

    async def transition_node_run(
        self,
        node_run_id: str,
        target: RunStatus,
        *,
        at: datetime | None = None,
        result: object | None = None,
        error: str | None = None,
        accepted_outcome: AcceptedNodeOutcome | None = None,
    ) -> NodeRun:
        def update(record: DurableRunRecord) -> DurableRunRecord:
            node_runs = list(record.node_runs)
            for index, node_run in enumerate(node_runs):
                if node_run.node_run_id != node_run_id:
                    continue
                node_runs[index] = transition_node_run(
                    node_run,
                    target,
                    at=at,
                    result=result,
                    error=error,
                    accepted_outcome=accepted_outcome,
                )
                return record.model_copy(update={"node_runs": tuple(node_runs)})
            raise RunIntegrityError(f"NodeRun {node_run_id!r} does not exist")

        updated = await self._mutate(update)
        node_run = next(item for item in updated.node_runs if item.node_run_id == node_run_id)
        return node_run.model_copy(deep=True)

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
    ) -> Attempt:
        created: Attempt | None = None

        def update(record: DurableRunRecord) -> DurableRunRecord:
            nonlocal created
            node_run = next(
                (item for item in record.node_runs if item.node_run_id == node_run_id),
                None,
            )
            if node_run is None:
                raise RunIntegrityError(f"NodeRun {node_run_id!r} does not exist")
            if node_run.status in TERMINAL_RUN_STATUSES:
                raise RunIntegrityError("cannot create Attempt under a terminal NodeRun")

            existing = [
                attempt for attempt in record.attempts if attempt.node_run_id == node_run_id
            ]
            if any(
                attempt.status in {AttemptStatus.CREATED, AttemptStatus.RUNNING}
                for attempt in existing
            ):
                raise ActiveAttemptExists(f"NodeRun {node_run_id!r} already has an active Attempt")
            ordinal = max((attempt.ordinal for attempt in existing), default=0) + 1
            created = Attempt(
                node_run_id=node_run_id,
                ordinal=ordinal,
                runtime_id=runtime_id,
                executor_id=executor_id,
                deadline_at=deadline_at,
                resume_checkpoint_id=resume_checkpoint_id,
            )
            if lease_holder is not None:
                lease = ExecutionLease(
                    node_run_id=node_run_id,
                    attempt_id=created.attempt_id,
                    lease_epoch=ordinal,
                    holder=lease_holder,
                )
                if lease_ttl is not None:
                    lease = renewed_lease(lease, at=lease.issued_at, ttl=lease_ttl)
                created = Attempt.model_validate(
                    {**created.model_dump(mode="python"), "execution_lease": lease}
                )
            return record.model_copy(update={"attempts": (*record.attempts, created)})

        await self._mutate(update)
        assert created is not None
        return created.model_copy(deep=True)

    async def renew_lease(
        self,
        attempt_id: str,
        *,
        fencing_token: str,
        ttl: timedelta,
        at: datetime | None = None,
    ) -> Attempt:
        """Prove the holder is still alive, and push its expiry out by ``ttl``.

        The fourth store implementing this, and it needs it for the same reason
        the other three do: `AttemptExecutionService` renews through whatever
        store it was given, and a durable Graph node is executed by a process
        that can die exactly like a task worker.
        """
        renewed: Attempt | None = None

        def update(record: DurableRunRecord) -> DurableRunRecord:
            nonlocal renewed
            attempts = list(record.attempts)
            for index, attempt in enumerate(attempts):
                if attempt.attempt_id != attempt_id:
                    continue
                renewed = renew_attempt_lease(attempt, fencing_token=fencing_token, ttl=ttl, at=at)
                attempts[index] = renewed
                return record.model_copy(update={"attempts": tuple(attempts)})
            raise AttemptNotFound(f"Attempt {attempt_id!r} does not exist")

        await self._mutate(update)
        assert renewed is not None
        return renewed.model_copy(deep=True)

    async def reclaim_expired_attempts(
        self,
        *,
        now: datetime | None = None,
        limit: int = DEFAULT_RECLAIM_BATCH,
    ) -> list[Attempt]:
        """Settle this Run's Attempts whose holder stopped renewing.

        Scoped to one Run, because this store is: it is a lifecycle view over a
        single `DurableRunRecord`. A sweep across every durable Run is the
        `DurableRunStore`'s question, not this view's, and answering it here
        would quietly widen what a caller holding one Run can touch.
        """
        moment = now if now is not None else datetime.now(UTC)
        reclaimed: list[Attempt] = []

        def update(record: DurableRunRecord) -> DurableRunRecord:
            reclaimed.clear()
            attempts = list(record.attempts)
            doomed = sorted(
                (a for a in attempts if lease_is_expired(a, moment)),
                key=lambda a: (a.execution_lease.expires_at, a.attempt_id),  # type: ignore[union-attr]
            )[:limit]
            if not doomed:
                return record
            by_id = {a.attempt_id for a in doomed}
            for index, attempt in enumerate(attempts):
                if attempt.attempt_id not in by_id:
                    continue
                settled = reclaim_attempt(attempt, at=moment)
                attempts[index] = settled
                reclaimed.append(settled)
            return record.model_copy(update={"attempts": tuple(attempts)})

        await self._mutate(update)
        return [item.model_copy(deep=True) for item in reclaimed]

    async def get_attempt(self, attempt_id: str) -> Attempt | None:
        record = await self._get_record()
        attempt = next(
            (item for item in record.attempts if item.attempt_id == attempt_id),
            None,
        )
        return attempt.model_copy(deep=True) if attempt is not None else None

    async def list_attempts(self, node_run_id: str) -> list[Attempt]:
        record = await self._get_record()
        if not any(item.node_run_id == node_run_id for item in record.node_runs):
            raise RunIntegrityError(f"NodeRun {node_run_id!r} does not exist")
        return [
            attempt.model_copy(deep=True)
            for attempt in record.attempts
            if attempt.node_run_id == node_run_id
        ]

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
    ) -> Attempt:
        def update(record: DurableRunRecord) -> DurableRunRecord:
            attempts = list(record.attempts)
            for index, attempt in enumerate(attempts):
                if attempt.attempt_id != attempt_id:
                    continue
                self._validate_fence(attempt, fencing_token)
                attempts[index] = transition_attempt(
                    attempt,
                    target,
                    at=at,
                    result=result,
                    error=error,
                    metrics=metrics,
                )
                return record.model_copy(update={"attempts": tuple(attempts)})
            raise RunIntegrityError(f"Attempt {attempt_id!r} does not exist")

        updated = await self._mutate(update)
        attempt = next(item for item in updated.attempts if item.attempt_id == attempt_id)
        return attempt.model_copy(deep=True)

    @staticmethod
    def _validate_fence(attempt: Attempt, fencing_token: str | None) -> None:
        lease = attempt.execution_lease
        if lease is not None and fencing_token != lease.fencing_token:
            raise StaleExecutionFence(
                f"Attempt {attempt.attempt_id!r} update rejected by execution fence"
            )

    async def _get_record(self) -> DurableRunRecord:
        record = await self._store.get(self._run_id)
        if record is None:
            raise RunIntegrityError(f"Run {self._run_id!r} does not exist")
        return record

    async def _mutate(
        self,
        mutate: Callable[[DurableRunRecord], DurableRunRecord],
    ) -> DurableRunRecord:
        async with self._lock:
            current = await self._get_record()
            changed = mutate(current)
            candidate = changed.model_copy(update={"version": current.version + 1})
            return await self._store.update(candidate)

    def _require_run_id(self, run_id: str) -> None:
        if run_id != self._run_id:
            raise RunIntegrityError(
                f"execution store is bound to Run {self._run_id!r}, not {run_id!r}"
            )


__all__ = ["DurableRunExecutionStore"]
