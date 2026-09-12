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
from datetime import datetime
from typing import Any

from maistro.runs.model import Attempt, NodeRun, RunStatus
from maistro.runs.store import RunIntegrityError, RunStore

from .continuation import GraphContinuation, GraphContinuationStore
from .fair_scan import DEFAULT_MAX_INSPECTED, ScanPage
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
        """Boundedly repair cross-store crash residue and purge true orphans."""
        if limit <= 0:
            return 0

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
        return changed

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
        if canonical.status is RunStatus.RUNNING and continuation.status in {
            RunStatus.WAITING,
            RunStatus.PAUSED,
        }:
            await self._run_store.transition_run(run_id, continuation.status)
            return True
        return False

    async def list_by_status(
        self,
        status: RunStatus,
        *,
        limit: int = 100,
        project_id: str | None = None,
        after: tuple[str, str] | None = None,
    ) -> list[DurableRunRecord]:
        run_ids = await self._continuations.list_run_ids_by_status(
            status,
            limit=limit,
            project_id=project_id,
            after=after,
        )
        return await self._assemble_all(run_ids)

    async def list_due(
        self,
        *,
        now: datetime,
        limit: int = 100,
        after: tuple[str, str] | None = None,
    ) -> list[DurableRunRecord]:
        run_ids = await self._continuations.list_due_run_ids(now=now, limit=limit, after=after)
        records = await self._assemble_all(run_ids)
        return [
            record
            for record in records
            if record.run.status in _RECOVERY_VISIBLE_STATUSES
            and record.resume_at is not None
            and record.resume_at <= now
        ][:limit]

    async def scan_due_page(
        self,
        *,
        now: datetime,
        limit: int = 100,
        after: tuple[str, str] | None = None,
        max_inspected: int = DEFAULT_MAX_INSPECTED,
    ) -> ScanPage[DurableRunRecord, tuple[str, str]]:
        """Page the due index, reporting progress apart from what is due.

        ``list_due`` cannot answer a fair scan honestly. It reads a page of
        due-index ids, assembles them, and drops the ones whose canonical Run
        has since gone terminal -- so a page of stale ids comes back empty
        while having moved through the index, and an empty list is also what
        the end of the index looks like. A scan that reads the two as the same
        thing resets to the top on every tick and never gets past a stale
        prefix longer than one page (the starvation #1098/#1127 describe,
        one layer down from where they describe it).

        This returns both facts. It keeps walking index pages past ids that
        assemble into Runs no longer due, up to ``max_inspected`` rows, and
        reports where it got to whether or not anything was eligible.
        ``exhausted`` is set only when the index itself ran out, which is the
        one case where restarting from the top is right.
        """
        if limit <= 0 or max_inspected <= 0:
            return ScanPage(items=[], resume_after=after, inspected=0)

        due: list[DurableRunRecord] = []
        cursor = after
        inspected = 0
        while len(due) < limit and inspected < max_inspected:
            run_ids = await self._continuations.list_due_run_ids(
                now=now, limit=min(limit, max_inspected - inspected), after=cursor
            )
            if not run_ids:
                return ScanPage(items=due, resume_after=cursor, inspected=inspected, exhausted=True)
            for run_id in run_ids:
                inspected += 1
                candidate = await self._due_candidate(run_id, now)
                if candidate is None:
                    continue
                cursor, record = candidate
                if record is not None:
                    due.append(record)
                    if len(due) >= limit:
                        break
        return ScanPage(items=due, resume_after=cursor, inspected=inspected)

    async def _due_candidate(
        self, run_id: str, now: datetime
    ) -> tuple[tuple[str, str], DurableRunRecord | None] | None:
        """One index row's keyset position, and its record if it is still due.

        ``None`` means the row contributes no position: its continuation was
        deleted between the index read and this read, so there is no row left
        to page past. The rows after it in the same page still place the walk,
        so this costs position only when such a row is last in its page, and
        only until the next tick re-reads it.
        """
        record = await self.get(run_id)
        if record is None or record.resume_at is None:
            return None
        position = (record.resume_at.isoformat(), record.run_id)
        if record.run.status in _RECOVERY_VISIBLE_STATUSES and record.resume_at <= now:
            return position, record
        return position, None

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
