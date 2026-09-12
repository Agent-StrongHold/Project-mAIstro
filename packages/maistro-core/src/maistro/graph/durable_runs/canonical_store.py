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
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from maistro.runs.lifecycle import settle_open_node_run, transition_node_run, transition_run
from maistro.runs.model import TERMINAL_RUN_STATUSES, Attempt, NodeRun, Run, RunStatus
from maistro.runs.store import RunIntegrityError, RunStore

from .continuation import GraphContinuation, GraphContinuationStore
from .hitl import earliest_hitl_deadline, settlement_time
from .spine import mirror_lifecycle
from .stores import answer_record, settle_hitl_record
from .types import DurableRunRecord

_RECOVERY_VISIBLE_STATUSES = frozenset({RunStatus.WAITING, RunStatus.PAUSED, RunStatus.RUNNING})

logger = logging.getLogger(__name__)


def _terminal_hitl_evidence(
    continuation: GraphContinuation,
    target: RunStatus,
) -> tuple[str, str, datetime, str] | None:
    metadata = continuation.graph_state.metadata
    settlements_raw = metadata.get("hitl_settlements", {})
    settlements = settlements_raw if isinstance(settlements_raw, Mapping) else {}
    matching = [
        (str(node_id), settlement)
        for node_id, settlement in settlements.items()
        if isinstance(settlement, Mapping) and settlement.get("outcome") == target.value
    ]
    if len(matching) != 1:
        return None
    node_id, settlement = matching[0]
    node_run_id = settlement.get("node_run_id")
    decided_at = settlement.get("decided_at")
    if not isinstance(node_run_id, str) or not isinstance(decided_at, str):
        return None
    try:
        moment = settlement_time(datetime.fromisoformat(decided_at))
    except (TypeError, ValueError):
        logger.warning(
            "cannot reconcile terminal HITL continuation %s: invalid decided_at",
            continuation.run_id,
        )
        return None

    pause = settlement.get("pause")
    if target is RunStatus.TIMED_OUT and isinstance(pause, Mapping):
        deadline = pause.get("resume_at")
        detail = f" at {deadline}" if isinstance(deadline, str) else ""
        reason = f"human input for node {node_id!r} timed out{detail}"
    elif target is RunStatus.TIMED_OUT:
        reason = f"human input for node {node_id!r} timed out"
    else:
        reason = f"human input for node {node_id!r} was cancelled"
    return node_id, node_run_id, moment, reason


def _terminal_hitl_node_runs(
    node_runs: tuple[NodeRun, ...],
    *,
    node_run_id: str,
    target: RunStatus,
    moment: datetime,
    reason: str,
) -> tuple[NodeRun, ...] | None:
    repaired = list(node_runs)
    for index, node_run in enumerate(repaired):
        if node_run.status in TERMINAL_RUN_STATUSES:
            if node_run.node_run_id == node_run_id and node_run.status is not target:
                return None
            continue
        if node_run.node_run_id == node_run_id:
            repaired[index] = transition_node_run(
                node_run,
                target,
                at=moment,
                error=reason,
            )
        else:
            repaired[index] = settle_open_node_run(node_run, target, at=moment)
    return tuple(repaired)


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
        if await self._reconcile_terminal_hitl(continuation, canonical):
            return True
        if canonical.status is RunStatus.RUNNING and continuation.status in {
            RunStatus.WAITING,
            RunStatus.PAUSED,
        }:
            await self._run_store.transition_run(run_id, continuation.status)
            return True
        return False

    async def _reconcile_terminal_hitl(
        self,
        continuation: GraphContinuation,
        canonical: Run,
    ) -> bool:
        """Finish a HITL lifecycle mirror interrupted after graph persistence.

        The continuation is written before the canonical spine so a crash
        leaves durable settlement evidence rather than an answerable pause.
        Rebuild the intended NodeRun projection from that evidence and let the
        normal lifecycle mirror walk the remaining canonical transitions.
        """
        target = continuation.status
        if target not in {RunStatus.CANCELLED, RunStatus.TIMED_OUT}:
            return False
        if canonical.status in TERMINAL_RUN_STATUSES:
            return False
        evidence = _terminal_hitl_evidence(continuation, target)
        if evidence is None:
            return False
        node_id, node_run_id, moment, reason = evidence

        record = await self.get(continuation.run_id)
        if record is None:
            return False
        if not any(
            node.node_run_id == node_run_id and node.node_id == node_id for node in record.node_runs
        ):
            logger.warning(
                "cannot reconcile terminal HITL continuation %s: node run %s is missing",
                continuation.run_id,
                node_run_id,
            )
            return False
        node_runs = _terminal_hitl_node_runs(
            record.node_runs,
            node_run_id=node_run_id,
            target=target,
            moment=moment,
            reason=reason,
        )
        if node_runs is None:
            logger.warning(
                "cannot reconcile terminal HITL continuation %s: node run %s disagrees",
                continuation.run_id,
                node_run_id,
            )
            return False

        desired_run = transition_run(record.run, target, at=moment, error=reason)
        desired = record.model_copy(update={"run": desired_run, "node_runs": node_runs})
        await mirror_lifecycle(desired, run_store=self._run_store)
        return True

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

    async def list_hitl_due(
        self,
        *,
        now: datetime,
        limit: int = 100,
    ) -> list[DurableRunRecord]:
        run_ids = await self._continuations.list_hitl_due_run_ids(now=now, limit=limit)
        records = await self._assemble_all(run_ids)
        return [
            record
            for record in records
            if record.run.status is RunStatus.PAUSED
            and (deadline := earliest_hitl_deadline(record)) is not None
            and deadline <= now
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
