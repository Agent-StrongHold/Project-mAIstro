"""`DurableRunStore` reimplemented over the canonical spine (#44).

The interface survives; the second system of record does not. A
`DurableRunRecord` handed to this store is split: Run, NodeRuns and Attempts
are written back to `RunStore`, which already holds them because the executor
obtained their identities there, and the Graph continuation is persisted beside
them. A record read back is assembled from those two halves, so there is one
answer to "what is this Run doing" rather than two that can disagree
(ADR-082826-d9f5).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from maistro.runs.aggregation import derive_run_terminal_status, terminal_run_payload
from maistro.runs.lifecycle import (
    InvalidLifecycleTransition,
    lease_is_expired,
    reclaim_attempt,
)
from maistro.runs.model import (
    TERMINAL_ATTEMPT_STATUSES,
    TERMINAL_RUN_STATUSES,
    Attempt,
    AttemptStatus,
    NodeRun,
    Run,
    RunStatus,
)
from maistro.runs.reconciliation import AttemptLifecycleReconciler, CancellationCause
from maistro.runs.store import RunIntegrityError, RunStore, StaleExecutionFence

from .continuation import GraphContinuation, GraphContinuationStore
from .spine import mirror_lifecycle
from .stores import answer_record, settle_hitl_record
from .types import DurableRunRecord

_RECOVERY_VISIBLE_STATUSES = frozenset({RunStatus.WAITING, RunStatus.PAUSED, RunStatus.RUNNING})

logger = logging.getLogger(__name__)


class CanonicalDurableRunStore:
    """Persist and assemble durable graph runs over `RunStore` + continuations."""

    def __init__(
        self,
        run_store: RunStore,
        continuations: GraphContinuationStore,
    ) -> None:
        self._run_store = run_store
        self._continuations = continuations
        self._lock = asyncio.Lock()

    async def create(self, record: DurableRunRecord) -> DurableRunRecord:
        if await self._run_store.get_run(record.run_id) is None:
            raise RunIntegrityError(
                f"Run {record.run_id!r} is not on the canonical spine; durable graph "
                "execution must obtain its Run from RunStore before checkpointing"
            )
        await self._continuations.create(GraphContinuation.of(record))
        await mirror_lifecycle(record, run_store=self._run_store)
        return await self._require(record.run_id)

    async def get(self, run_id: str) -> DurableRunRecord | None:
        continuation = await self._continuations.get(run_id)
        if continuation is None:
            return None
        run = await self._run_store.get_run(run_id)
        if run is None:
            raise RunIntegrityError(
                f"graph continuation {run_id!r} has no canonical Run; "
                "run persistence was purged without reconciling Graph continuation state"
            )
        node_runs = await self._run_store.list_node_runs(run_id)
        attempts = await self._attempts_for(node_runs)
        return DurableRunRecord(
            run=run,
            graph_state=continuation.graph_state,
            node_runs=tuple(node_runs),
            attempts=attempts,
            traversal_checkpoints=continuation.traversal_checkpoints,
            traversal_commits=continuation.traversal_commits,
            resume_at=continuation.resume_at,
            version=continuation.version,
        )

    async def update(self, record: DurableRunRecord) -> DurableRunRecord:
        async with self._lock:
            await self._continuations.update(GraphContinuation.of(record))
            await mirror_lifecycle(record, run_store=self._run_store)
            return await self._require(record.run_id)

    async def reconcile_persistence(self, *, limit: int = 100) -> int:
        """Boundedly repair split persistence and stranded canonical RUNNING Runs.

        Continuations are an indexed candidate source for cross-store residue;
        the canonical status index is the candidate source for stranded Runs.
        Reading both is intentional: a missing continuation is itself one of
        the crash windows this sweep closes.
        """
        if limit <= 0:
            return 0
        changed, seen = await self._reconcile_continuation_candidates(limit)
        remaining = limit - len(seen)
        if remaining <= 0:
            return changed
        running = await self._run_store.list_by_status(RunStatus.RUNNING, limit=remaining)
        for run in running:
            if run.run_id in seen:
                continue
            seen.add(run.run_id)
            if await self._reconcile_running_run(run):
                changed += 1
        return changed

    async def _reconcile_continuation_candidates(self, limit: int) -> tuple[int, set[str]]:
        """Repair at most ``limit`` continuation-indexed candidates."""
        changed = 0
        seen: set[str] = set()
        for status in RunStatus:
            remaining = limit - len(seen)
            if remaining <= 0:
                break
            run_ids = await self._continuations.list_run_ids_by_status(
                status,
                limit=remaining,
            )
            for run_id in run_ids:
                if run_id in seen:
                    continue
                seen.add(run_id)
                if await self._reconcile_run(run_id):
                    changed += 1
        return changed, seen

    async def _reconcile_run(self, run_id: str) -> bool:
        """Repair one run's cross-store residue; report whether state changed."""
        continuation = await self._continuations.get(run_id)
        if continuation is None:
            return False
        canonical = await self._run_store.get_run(run_id)
        if canonical is None:
            # No canonical Run means a true orphan: purge the continuation.
            # Logged rather than deleted silently, because a Run purge that
            # outran this reconciliation must remain inspectable evidence
            # (#62), not a continuation that quietly stopped existing.
            logger.warning(
                "purging orphaned Graph continuation %s (status=%s version=%d): "
                "its canonical Run was purged or never persisted",
                run_id,
                continuation.status.value,
                continuation.version,
            )
            return await self._continuations.delete(run_id)

        if canonical.status is RunStatus.RUNNING:
            return await self._reconcile_running_projection(canonical, continuation)

        # RunStore is the universal lifecycle authority. A continuation status
        # that lags a terminal/parked Run is only a stale lookup projection and
        # must be repaired in place; it must never move the canonical Run back.
        if continuation.status is not canonical.status:
            await self._update_continuation_status(continuation, canonical.status)
            return True
        return False

    async def _reconcile_running_projection(
        self,
        run: Run,
        continuation: GraphContinuation,
    ) -> bool:
        """Repair a continuation whose canonical Run is still RUNNING."""
        if continuation.status in {RunStatus.WAITING, RunStatus.PAUSED}:
            return await self._transition_run_if_needed(run.run_id, continuation.status)
        if continuation.status is RunStatus.QUEUED:
            # Checkpoint 1 may have moved the canonical Run first. The spine's
            # RUNNING claim is authoritative; advance only the continuation
            # projection and make the frontier recoverable.
            await self._update_continuation_status(
                continuation,
                RunStatus.RUNNING,
                resume_at=datetime.now(UTC),
            )
            return True
        if continuation.status in TERMINAL_RUN_STATUSES:
            node_runs = await self._run_store.list_node_runs(run.run_id)
            target = self._terminal_target(
                continuation.status,
                node_runs,
                work_owed=bool(continuation.graph_state.active_node_ids),
            )
            if target is None:
                return False
            result, error = terminal_run_payload(node_runs, target)
            changed = await self._transition_run_if_needed(
                run.run_id,
                target,
                result=result,
                error=error,
            )
            if changed:
                await self._update_continuation_status(continuation, target, resume_at=None)
            return changed
        if continuation.status is RunStatus.RUNNING:
            return await self._reconcile_running_run(run)
        return False

    async def _reconcile_running_run(self, run: Run) -> bool:
        """Derive one indexed canonical RUNNING candidate from durable facts."""
        node_runs = await self._run_store.list_node_runs(run.run_id)
        attempts = await self._attempts_for(node_runs)
        changed = await self._reclaim_expired_attempts(attempts)
        current = await self._run_store.get_run(run.run_id)
        continuation = await self._continuations.get(run.run_id)
        if current is None or current.status is not RunStatus.RUNNING:
            if continuation is not None and current is not None:
                await self._update_continuation_status(
                    continuation,
                    current.status,
                    resume_at=datetime.now(UTC) if current.status is RunStatus.WAITING else None,
                )
            return True
        node_runs = await self._run_store.list_node_runs(run.run_id)
        if continuation is None:
            return await self._settle_without_continuation(current, node_runs) or changed
        if continuation.status in TERMINAL_RUN_STATUSES:
            return changed or await self._reconcile_run(run.run_id)
        if continuation.status in {RunStatus.WAITING, RunStatus.PAUSED}:
            return await self._transition_run_if_needed(run.run_id, continuation.status)
        if (
            continuation.graph_state.active_node_ids
            and continuation.resume_at is None
            and not self._has_live_attempt(attempts)
        ):
            # This is the checkpoint-failure window: the frontier is persisted
            # but the claim deadline was not. Make it visible to the indexed
            # due query without claiming any physical Attempt here.
            await self._update_continuation_status(
                continuation,
                RunStatus.RUNNING,
                resume_at=datetime.now(UTC),
            )
            changed = True
        if not continuation.graph_state.active_node_ids:
            changed = (
                await self._settle_empty_frontier(
                    current,
                    continuation,
                    node_runs,
                )
                or changed
            )
        return changed

    async def _reclaim_expired_attempts(self, attempts: tuple[Attempt, ...]) -> bool:
        """Reclaim only expired leased Attempts in this candidate Run."""
        lifecycle = AttemptLifecycleReconciler(self._run_store)
        changed = False
        for attempt in attempts:
            lease = attempt.execution_lease
            if (
                attempt.status not in {AttemptStatus.CREATED, AttemptStatus.RUNNING}
                or lease is None
                or not lease_is_expired(attempt, datetime.now(UTC))
            ):
                continue
            settled = reclaim_attempt(attempt)
            try:
                settled = await self._run_store.transition_attempt(
                    attempt.attempt_id,
                    settled.status,
                    error=settled.error,
                    fencing_token=lease.fencing_token,
                )
            except (InvalidLifecycleTransition, StaleExecutionFence):
                refreshed = await self._run_store.get_attempt(attempt.attempt_id)
                if refreshed is None:
                    raise
                if refreshed.status not in TERMINAL_ATTEMPT_STATUSES:
                    continue
                settled = refreshed
            await lifecycle.reconcile(settled, cancellation=CancellationCause.RECOVERED)
            changed = True
        return changed

    async def _settle_without_continuation(
        self,
        run: Run,
        node_runs: list[NodeRun],
    ) -> bool:
        """Settle only fully observed acyclic work when Graph state is absent."""
        graph = run.graph.materialize()
        observed = {node_run.node_id for node_run in node_runs}
        required = {node.node_id for node in graph.nodes}
        if required - observed or not self._graph_is_acyclic(graph):
            return False
        target = self._terminal_target(RunStatus.COMPLETED, node_runs, work_owed=False)
        if target is None:
            return False
        result, error = terminal_run_payload(node_runs, target)
        return await self._transition_run_if_needed(
            run.run_id,
            target,
            result=result,
            error=error,
        )

    async def _settle_empty_frontier(
        self,
        run: Run,
        continuation: GraphContinuation,
        node_runs: list[NodeRun],
    ) -> bool:
        """Settle a continuation that proves no Graph work remains."""
        target = self._terminal_target(RunStatus.COMPLETED, node_runs, work_owed=False)
        if target is None:
            return False
        result, error = terminal_run_payload(node_runs, target)
        changed = await self._transition_run_if_needed(
            run.run_id,
            target,
            result=result,
            error=error,
        )
        await self._update_continuation_status(continuation, target, resume_at=None)
        return changed

    @staticmethod
    def _graph_is_acyclic(graph: Any) -> bool:
        """Avoid settling a cycle when the missing frontier is unknowable."""
        indegree = {node.node_id: 0 for node in graph.nodes}
        outgoing: dict[str, list[str]] = {node_id: [] for node_id in indegree}
        for edge in graph.edges:
            outgoing[edge.from_node].append(edge.to_node)
            indegree[edge.to_node] += 1
        ready = [node_id for node_id, degree in indegree.items() if degree == 0]
        visited = 0
        while ready:
            node_id = ready.pop()
            visited += 1
            for successor in outgoing[node_id]:
                indegree[successor] -= 1
                if indegree[successor] == 0:
                    ready.append(successor)
        return visited == len(indegree)

    @staticmethod
    def _has_live_attempt(attempts: tuple[Attempt, ...]) -> bool:
        now = datetime.now(UTC)
        return any(
            attempt.status in {AttemptStatus.CREATED, AttemptStatus.RUNNING}
            and attempt.execution_lease is not None
            and not lease_is_expired(attempt, now)
            for attempt in attempts
        )

    @staticmethod
    def _terminal_target(
        continuation_status: RunStatus,
        node_runs: list[NodeRun],
        *,
        work_owed: bool,
    ) -> RunStatus | None:
        derived = derive_run_terminal_status(node_runs, work_owed=work_owed)
        if continuation_status is RunStatus.COMPLETED:
            # A failed logical NodeRun outranks a stale successful projection.
            return derived
        if continuation_status in {
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.TIMED_OUT,
        }:
            # These are explicit Graph terminal decisions. They remain
            # authoritative even when the canonical Run mirror died before its
            # write; terminal NodeRuns still supply any available payload.
            return continuation_status
        return None

    async def _transition_run_if_needed(
        self,
        run_id: str,
        target: RunStatus,
        *,
        result: object | None = None,
        error: str | None = None,
    ) -> bool:
        """Make concurrent sweepers converge on one legal Run transition."""
        try:
            await self._run_store.transition_run(
                run_id,
                target,
                result=result,
                error=error,
            )
        except InvalidLifecycleTransition:
            current = await self._run_store.get_run(run_id)
            if current is None or current.status is not target:
                raise
            return False
        return True

    async def _update_continuation_status(
        self,
        continuation: GraphContinuation,
        status: RunStatus,
        *,
        resume_at: datetime | None | object = ...,
    ) -> None:
        updates: dict[str, object] = {"status": status, "version": continuation.version + 1}
        if resume_at is not ...:
            updates["resume_at"] = resume_at
        try:
            await self._continuations.update(continuation.model_copy(update=updates))
        except ValueError:
            latest = await self._continuations.get(continuation.run_id)
            if latest is None or latest.status is not status:
                raise

    async def list_by_status(
        self,
        status: RunStatus,
        *,
        limit: int = 100,
        project_id: str | None = None,
    ) -> list[DurableRunRecord]:
        run_ids = await self._continuations.list_run_ids_by_status(
            status,
            limit=limit,
            project_id=project_id,
        )
        return await self._assemble_all(run_ids)

    async def list_due(
        self,
        *,
        now: datetime,
        limit: int = 100,
    ) -> list[DurableRunRecord]:
        run_ids = await self._continuations.list_due_run_ids(now=now, limit=limit)
        records = await self._assemble_all(run_ids)
        return [
            record
            for record in records
            if record.run.status in _RECOVERY_VISIBLE_STATUSES
            and record.resume_at is not None
            and record.resume_at <= now
        ][:limit]

    async def list_for_project(
        self,
        project_id: str,
        *,
        limit: int = 25,
    ) -> list[DurableRunRecord]:
        run_ids = await self._continuations.list_run_ids_for_project(
            project_id,
            limit=limit,
        )
        return await self._assemble_all(run_ids)

    async def submit_hitl_answer(
        self,
        run_id: str,
        node_id: str,
        answer: dict[str, Any],
        *,
        at: datetime | None = None,
    ) -> DurableRunRecord:
        """Attach an answer and queue the paused canonical Run for resume.

        The rule stays where it already was: `answer_record` decides which
        paused NodeRun the answer belongs to, what the remaining pause
        metadata is, and when the Run becomes runnable again. Only where the
        result lands has changed.
        """
        return await self._mutate_hitl(
            run_id,
            lambda current: answer_record(current, node_id, answer, at=at),
        )

    async def timeout_hitl(
        self,
        run_id: str,
        node_id: str,
        *,
        at: datetime | None = None,
    ) -> DurableRunRecord:
        """Persist an elapsed HITL deadline and mirror its terminal lifecycle."""
        return await self._mutate_hitl(
            run_id,
            lambda current: settle_hitl_record(current, node_id, "timed_out", at=at),
        )

    async def cancel_hitl(
        self,
        run_id: str,
        node_id: str,
        *,
        at: datetime | None = None,
    ) -> DurableRunRecord:
        """Persist explicit HITL cancellation and mirror its terminal lifecycle."""
        return await self._mutate_hitl(
            run_id,
            lambda current: settle_hitl_record(current, node_id, "cancelled", at=at),
        )

    async def _mutate_hitl(
        self,
        run_id: str,
        mutate: Callable[[DurableRunRecord], DurableRunRecord],
    ) -> DurableRunRecord:
        async with self._lock:
            current = await self.get(run_id)
            if current is None:
                raise KeyError(f"no such run: {run_id!r}")
            updated = mutate(current)
            await self._continuations.update(GraphContinuation.of(updated))
            await mirror_lifecycle(updated, run_store=self._run_store)
            return await self._require(run_id)

    async def _attempts_for(self, node_runs: list[NodeRun]) -> tuple[Attempt, ...]:
        attempts: list[Attempt] = []
        for node_run in node_runs:
            attempts.extend(await self._run_store.list_attempts(node_run.node_run_id))
        return tuple(attempts)

    async def _assemble_all(self, run_ids: list[str]) -> list[DurableRunRecord]:
        records = [await self.get(run_id) for run_id in run_ids]
        return [record for record in records if record is not None]

    async def _require(self, run_id: str) -> DurableRunRecord:
        record = await self.get(run_id)
        if record is None:
            raise KeyError(f"no such run: {run_id!r}")
        return record


__all__ = ["CanonicalDurableRunStore"]
