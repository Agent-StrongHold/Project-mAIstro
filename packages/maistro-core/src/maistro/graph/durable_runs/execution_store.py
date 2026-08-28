"""RunStore-compatible lifecycle view over durable Graph persistence.

The durable Graph record carries projections of canonical Run/NodeRun/Attempt
rows. When a canonical RunStore is wired, identity and physical lifecycle live
there; this adapter keeps the graph checkpoint synchronized without minting a
second execution universe.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from maistro.runs.lifecycle import (
    InvalidLifecycleTransition,
    lease_is_expired,
    reclaim_attempt,
    renew_attempt_lease,
    renewed_lease,
    transition_attempt,
    transition_node_run,
    transition_run,
)
from maistro.runs.model import (
    TERMINAL_ATTEMPT_STATUSES,
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
    RunStore,
    StaleExecutionFence,
)

from .protocol import DurableRunStore
from .types import DurableRunRecord


class DurableRunExecutionStore:
    """Expose canonical execution lifecycle operations for one durable Run."""

    def __init__(
        self,
        store: DurableRunStore,
        *,
        run_id: str,
        run_store: RunStore | None = None,
    ) -> None:
        self._store = store
        self._run_id = run_id
        self._run_store = run_store
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
        """Create or adopt exactly one Attempt under the requested NodeRun.

        A canonical create can commit before the graph checkpoint that mirrors
        it. Retrying that boundary must adopt the store-owned identity rather
        than ask the store to mint ordinal N+1 while ordinal N is still active.
        """
        if self._run_store is not None:
            record = await self._get_record()
            existing = self._require_creatable(record, node_run_id)
            expected_ordinal = max((attempt.ordinal for attempt in existing), default=0) + 1
            adopted = await self._adoptable_canonical_attempt(
                record,
                node_run_id,
                expected_ordinal=expected_ordinal,
                runtime_id=runtime_id,
                executor_id=executor_id,
                deadline_at=deadline_at,
                resume_checkpoint_id=resume_checkpoint_id,
                lease_holder=lease_holder,
            )
            if adopted is not None:
                await self._mutate(
                    lambda current: current.model_copy(
                        update={"attempts": (*current.attempts, adopted)}
                    )
                )
                return adopted.model_copy(deep=True)

            created = await self._run_store.create_attempt(
                node_run_id,
                runtime_id=runtime_id,
                executor_id=executor_id,
                deadline_at=deadline_at,
                resume_checkpoint_id=resume_checkpoint_id,
                lease_holder=lease_holder,
                lease_ttl=lease_ttl,
            )
            await self._mutate(
                lambda current: current.model_copy(
                    update={"attempts": (*current.attempts, created)}
                )
            )
            return created.model_copy(deep=True)

        minted: Attempt | None = None

        def update(record: DurableRunRecord) -> DurableRunRecord:
            nonlocal minted
            existing = self._require_creatable(record, node_run_id)
            ordinal = max((attempt.ordinal for attempt in existing), default=0) + 1
            minted = Attempt(
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
                    attempt_id=minted.attempt_id,
                    lease_epoch=ordinal,
                    holder=lease_holder,
                )
                if lease_ttl is not None:
                    lease = renewed_lease(lease, at=lease.issued_at, ttl=lease_ttl)
                minted = Attempt.model_validate(
                    {**minted.model_dump(mode="python"), "execution_lease": lease}
                )
            return record.model_copy(update={"attempts": (*record.attempts, minted)})

        await self._mutate(update)
        assert minted is not None
        return minted.model_copy(deep=True)

    async def _adoptable_canonical_attempt(
        self,
        record: DurableRunRecord,
        node_run_id: str,
        *,
        expected_ordinal: int,
        runtime_id: str,
        executor_id: str,
        deadline_at: datetime | None,
        resume_checkpoint_id: str | None,
        lease_holder: str | None,
    ) -> Attempt | None:
        """Return the one canonical Attempt a failed checkpoint omitted."""
        assert self._run_store is not None
        projected_ids = {attempt.attempt_id for attempt in record.attempts}
        canonical = await self._run_store.list_attempts(node_run_id)
        missing = [attempt for attempt in canonical if attempt.attempt_id not in projected_ids]
        if not missing:
            return None
        missing.sort(key=lambda attempt: attempt.ordinal)
        candidate = missing[0]
        if candidate.ordinal != expected_ordinal or len(missing) != 1:
            raise RunIntegrityError(
                f"canonical Attempt history for NodeRun {node_run_id!r} is not a one-row "
                f"continuation of durable ordinal {expected_ordinal - 1}"
            )
        if candidate.status not in {AttemptStatus.CREATED, AttemptStatus.RUNNING}:
            raise RunIntegrityError(
                f"unmirrored canonical Attempt {candidate.attempt_id!r} is already "
                f"{candidate.status.value!r}"
            )
        lease = candidate.execution_lease
        holder = lease.holder if lease is not None else None
        if (
            candidate.runtime_id != runtime_id
            or candidate.executor_id != executor_id
            or candidate.deadline_at != deadline_at
            or candidate.resume_checkpoint_id != resume_checkpoint_id
            or holder != lease_holder
        ):
            raise RunIntegrityError(
                f"unmirrored canonical Attempt {candidate.attempt_id!r} does not match "
                "the retried creation contract"
            )
        return candidate

    @staticmethod
    def _require_creatable(record: DurableRunRecord, node_run_id: str) -> list[Attempt]:
        node_run = next(
            (item for item in record.node_runs if item.node_run_id == node_run_id),
            None,
        )
        if node_run is None:
            raise RunIntegrityError(f"NodeRun {node_run_id!r} does not exist")
        if node_run.status in TERMINAL_RUN_STATUSES:
            raise RunIntegrityError("cannot create Attempt under a terminal NodeRun")
        existing = [attempt for attempt in record.attempts if attempt.node_run_id == node_run_id]
        if any(
            attempt.status in {AttemptStatus.CREATED, AttemptStatus.RUNNING} for attempt in existing
        ):
            raise ActiveAttemptExists(f"NodeRun {node_run_id!r} already has an active Attempt")
        return existing

    async def renew_lease(
        self,
        attempt_id: str,
        *,
        fencing_token: str,
        ttl: timedelta,
        at: datetime | None = None,
    ) -> Attempt:
        if self._run_store is not None:
            canonical = await self._run_store.renew_lease(
                attempt_id, fencing_token=fencing_token, ttl=ttl, at=at
            )
            await self._mutate(lambda record: self._replace_attempt(record, canonical))
            return canonical.model_copy(deep=True)

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
        """Settle only this Run's expired Attempts, canonically when wired."""
        moment = now if now is not None else datetime.now(UTC)
        if self._run_store is not None:
            return await self._reclaim_canonical_attempts(moment=moment, limit=limit)

        reclaimed: list[Attempt] = []

        def update(record: DurableRunRecord) -> DurableRunRecord:
            reclaimed.clear()
            attempts = list(record.attempts)
            doomed = sorted(
                (attempt for attempt in attempts if lease_is_expired(attempt, moment)),
                key=lambda attempt: (
                    attempt.execution_lease.expires_at,  # type: ignore[union-attr]
                    attempt.attempt_id,
                ),
            )[:limit]
            if not doomed:
                return record
            by_id = {attempt.attempt_id for attempt in doomed}
            for index, attempt in enumerate(attempts):
                if attempt.attempt_id not in by_id:
                    continue
                settled = reclaim_attempt(attempt, at=moment)
                attempts[index] = settled
                reclaimed.append(settled)
            return record.model_copy(update={"attempts": tuple(attempts)})

        await self._mutate(update)
        return [item.model_copy(deep=True) for item in reclaimed]

    async def _reclaim_canonical_attempts(
        self,
        *,
        moment: datetime,
        limit: int,
    ) -> list[Attempt]:
        """Reclaim exact canonical identities without sweeping unrelated Runs.

        Safety relies on the shared renewal rule refusing to resurrect an
        already-expired lease. Once this view observes expiry at ``moment``, the
        fencing token can therefore settle that exact Attempt without a global
        RunStore sweep racing a late renewal.
        """
        assert self._run_store is not None
        record = await self._get_record()
        doomed = sorted(
            (attempt for attempt in record.attempts if lease_is_expired(attempt, moment)),
            key=lambda attempt: (
                attempt.execution_lease.expires_at,  # type: ignore[union-attr]
                attempt.attempt_id,
            ),
        )[:limit]
        if not doomed:
            return []

        replacements: dict[str, Attempt] = {}
        reclaimed: list[Attempt] = []
        for projected in doomed:
            canonical = await self._run_store.get_attempt(projected.attempt_id)
            if canonical is None:
                raise RunIntegrityError(
                    f"canonical Attempt {projected.attempt_id!r} disappeared during reclaim"
                )
            if canonical.status in TERMINAL_ATTEMPT_STATUSES:
                replacements[projected.attempt_id] = canonical
                if canonical.status is reclaim_attempt(projected, at=moment).status:
                    reclaimed.append(canonical)
                continue
            if not lease_is_expired(canonical, moment):
                # The canonical holder renewed before recovery observed it.
                # Repair the stale projection instead of cancelling live work.
                replacements[projected.attempt_id] = canonical
                continue

            lease = canonical.execution_lease
            if lease is None:
                raise RunIntegrityError(
                    f"expired canonical Attempt {canonical.attempt_id!r} has no execution lease"
                )
            settled = reclaim_attempt(canonical, at=moment)
            try:
                canonical = await self._run_store.transition_attempt(
                    canonical.attempt_id,
                    settled.status,
                    at=moment,
                    error=settled.error,
                    fencing_token=lease.fencing_token,
                )
            except (InvalidLifecycleTransition, StaleExecutionFence):
                refreshed = await self._run_store.get_attempt(canonical.attempt_id)
                if refreshed is None or refreshed.status not in TERMINAL_ATTEMPT_STATUSES:
                    raise
                canonical = refreshed
            replacements[projected.attempt_id] = canonical
            reclaimed.append(canonical)

        def update(current: DurableRunRecord) -> DurableRunRecord:
            attempts = [replacements.get(item.attempt_id, item) for item in current.attempts]
            return current.model_copy(update={"attempts": tuple(attempts)})

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
        if self._run_store is not None:
            canonical = await self._run_store.transition_attempt(
                attempt_id,
                target,
                at=at,
                result=result,
                error=error,
                metrics=metrics,
                fencing_token=fencing_token,
            )
            await self._mutate(lambda record: self._replace_attempt(record, canonical))
            return canonical.model_copy(deep=True)

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
    def _replace_attempt(record: DurableRunRecord, updated: Attempt) -> DurableRunRecord:
        attempts = list(record.attempts)
        for index, attempt in enumerate(attempts):
            if attempt.attempt_id == updated.attempt_id:
                attempts[index] = updated
                return record.model_copy(update={"attempts": tuple(attempts)})
        raise RunIntegrityError(f"Attempt {updated.attempt_id!r} does not exist")

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
