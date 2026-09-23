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
from datetime import UTC, datetime
from typing import Any

from maistro.runs.aggregation import terminal_run_payload
from maistro.runs.lifecycle import (
    InvalidLifecycleTransition,
    settle_open_node_run,
    transition_node_run,
    transition_run,
)
from maistro.runs.model import TERMINAL_RUN_STATUSES, Attempt, NodeRun, Run, RunStatus
from maistro.runs.store import RunCursor, RunIntegrityError, RunStore, run_cursor_key

from .continuation import GraphContinuation, GraphContinuationStore
from .fair_scan import (
    DEFAULT_MAX_INSPECTED,
    ScanContinuation,
    ScanPage,
    cursor_time,
    fair_page_scan,
)
from .hitl import earliest_hitl_deadline, settlement_time
from .spine import mirror_lifecycle
from .stores import answer_record, settle_hitl_record
from .types import DurableRunRecord

_RECOVERY_VISIBLE_STATUSES = frozenset({RunStatus.WAITING, RunStatus.PAUSED, RunStatus.RUNNING})
_GRAPH_TERMINAL_STATUSES = frozenset({RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED})
#: How many times `list_hitl_due` widens its candidate page when the indexed
#: prefix is occupied by projections the canonical Run disqualifies. Six
#: doublings read at most 64x the requested work before giving up on a tick.
_CANDIDATE_PAGES = 6

logger = logging.getLogger(__name__)


def _matching_hitl_settlement(
    continuation: GraphContinuation,
    target: RunStatus,
) -> tuple[str, Mapping[str, Any]] | None:
    settlements_raw = continuation.graph_state.metadata.get("hitl_settlements", {})
    settlements = settlements_raw if isinstance(settlements_raw, Mapping) else {}
    matching = [
        (str(node_id), settlement)
        for node_id, settlement in settlements.items()
        if isinstance(settlement, Mapping) and settlement.get("outcome") == target.value
    ]
    return matching[0] if len(matching) == 1 else None


def _settlement_moment(
    continuation: GraphContinuation,
    decided_at: object,
) -> datetime | None:
    if not isinstance(decided_at, str):
        return None
    try:
        return settlement_time(datetime.fromisoformat(decided_at))
    except (TypeError, ValueError):
        logger.warning(
            "cannot reconcile terminal HITL continuation %s: invalid decided_at",
            continuation.run_id,
        )
        return None


def _settlement_reason(
    node_id: str,
    target: RunStatus,
    pause: object,
) -> str:
    if target is not RunStatus.TIMED_OUT:
        return f"human input for node {node_id!r} was cancelled"
    if not isinstance(pause, Mapping):
        return f"human input for node {node_id!r} timed out"
    deadline = pause.get("resume_at")
    detail = f" at {deadline}" if isinstance(deadline, str) else ""
    return f"human input for node {node_id!r} timed out{detail}"


def _terminal_hitl_evidence(
    continuation: GraphContinuation,
    target: RunStatus,
) -> tuple[str, str, datetime, str] | None:
    matching = _matching_hitl_settlement(continuation, target)
    if matching is None:
        return None
    node_id, settlement = matching
    node_run_id = settlement.get("node_run_id")
    if not isinstance(node_run_id, str):
        return None
    moment = _settlement_moment(continuation, settlement.get("decided_at"))
    if moment is None:
        return None
    reason = _settlement_reason(node_id, target, settlement.get("pause"))
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
        self._running_scan: ScanContinuation[RunCursor] = ScanContinuation()

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

        seen: set[str] = set()
        changed = await self._reconcile_running_page(limit, seen)
        swept = len(seen)
        # Terminal settlement residue first, and from the side that shrinks. A
        # crash between the continuation write and the spine mirror leaves the
        # canonical Run PAUSED while its continuation is already CANCELLED or
        # TIMED_OUT. The per-status scan below reads a bounded prefix, and the
        # COMPLETED bucket in front of those statuses only ever grows, so such
        # residue behind a full prefix would never be reached. PAUSED canonical
        # Runs are few and transient: a scan over them always reaches its end.
        for run in await self._run_store.list_by_status(RunStatus.PAUSED, limit=limit):
            if run.run_id in seen:
                continue
            seen.add(run.run_id)
            if await self._reconcile_run(run.run_id):
                changed += 1
        for status in RunStatus:
            remaining = limit - (len(seen) - swept)
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

    async def _reconcile_running_page(self, limit: int, seen: set[str]) -> int:
        """Reconcile one cursor-advancing page of canonical RUNNING Runs.

        A crash between the continuation write and the spine mirror strands a
        RUNNING Run under a terminal or QUEUED continuation, neither of which
        the due index sees. The continuation-status buckets the loop below
        reads only grow, so the canonical RUNNING set -- transient by
        construction -- is where such a Run is reliably found. The cursor
        outlives the call, so non-Graph RUNNING Runs ahead of it are paged
        past on later ticks rather than re-read forever.
        """

        async def page(cursor: RunCursor | None, size: int) -> list[Run]:
            return await self._run_store.list_by_status(RunStatus.RUNNING, limit=size, after=cursor)

        runs = await fair_page_scan(
            fetch_page=page,
            cursor_of=run_cursor_key,
            eligible=lambda _run: True,
            limit=limit,
            page_size=limit,
            max_inspected=limit,
            continuation=self._running_scan,
        )
        changed = 0
        for run in runs:
            seen.add(run.run_id)
            if await self._reconcile_run(run.run_id):
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
        if await self._reconcile_terminal_graph(continuation, canonical):
            return True
        if await self._reconcile_unstarted_claim(continuation, canonical):
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
        if not self._has_terminal_hitl_node(record, node_id, node_run_id):
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
        return await self._mirror_terminal_hitl(desired, continuation.run_id, target)

    async def _reconcile_terminal_graph(
        self,
        continuation: GraphContinuation,
        canonical: Run,
    ) -> bool:
        """Settle a Run whose Graph continuation was persisted terminal first.

        The terminal record itself was lost with the crash; what survives is
        its status and whatever NodeRun evidence was mirrored before it. The
        Run's payload is re-derived from that evidence, and where none carries
        the original error, the error says so rather than inventing one. Open
        NodeRuns are settled by the spine's own terminal cascade.
        """
        target = continuation.status
        if target not in _GRAPH_TERMINAL_STATUSES or canonical.status in TERMINAL_RUN_STATUSES:
            return False
        if target is RunStatus.CANCELLED and _matching_hitl_settlement(continuation, target):
            return False
        node_runs = tuple(await self._run_store.list_node_runs(canonical.run_id))
        result, error = terminal_run_payload(node_runs, target)
        if target is not RunStatus.COMPLETED and error is None:
            error = (
                f"Graph continuation settled {target.value} before canonical settlement; "
                "original error not persisted"
            )
        record = await self.get(canonical.run_id)
        if record is None:
            return False
        desired_run = transition_run(record.run, target, result=result, error=error)
        desired = record.model_copy(update={"run": desired_run})
        return await self._mirror_terminal_hitl(desired, canonical.run_id, target)

    async def _reconcile_unstarted_claim(
        self,
        continuation: GraphContinuation,
        canonical: Run,
    ) -> bool:
        """Make an expired resume claim visible to the due index again.

        The resume claim is checkpointed while the continuation still reads
        QUEUED, and only then is the spine stepped to RUNNING. A crash between
        the two leaves a claim the due index never lists, because it excludes
        QUEUED continuations. Once the claim has elapsed no walker holds it,
        so the continuation is rewritten to mirror RUNNING under the same
        claim, and the next due tick resumes it. A live claim is left alone.
        """
        if continuation.status is not RunStatus.QUEUED or canonical.status is not RunStatus.RUNNING:
            return False
        if continuation.resume_at is None or continuation.resume_at > datetime.now(UTC):
            return False
        visible = continuation.model_copy(
            update={"status": RunStatus.RUNNING, "version": continuation.version + 1}
        )
        try:
            await self._continuations.update(visible)
        except ValueError:
            # Another writer advanced the continuation first; it owns the Run.
            return False
        return True

    @staticmethod
    def _has_terminal_hitl_node(
        record: DurableRunRecord,
        node_id: str,
        node_run_id: str,
    ) -> bool:
        return any(
            node.node_run_id == node_run_id and node.node_id == node_id for node in record.node_runs
        )

    async def _mirror_terminal_hitl(
        self,
        desired: DurableRunRecord,
        run_id: str,
        target: RunStatus,
    ) -> bool:
        try:
            await mirror_lifecycle(desired, run_store=self._run_store)
        except InvalidLifecycleTransition:
            # Two ticks can both pass the non-terminal check above; the one
            # that mirrors second finds the Run already at `target` and its
            # terminal hop refused. That is the same repair, already done.
            current = await self._run_store.get_run(run_id)
            if current is not None and current.status is target:
                return False
            raise
        return True

    async def list_by_status(
        self,
        status: RunStatus,
        *,
        limit: int = 100,
        project_id: str | None = None,
        workspace_id: str | None = None,
        after: tuple[str, str] | None = None,
    ) -> list[DurableRunRecord]:
        if workspace_id is None:
            run_ids = await self._continuations.list_run_ids_by_status(
                status,
                limit=limit,
                project_id=project_id,
                after=after,
            )
        else:
            # Continuations carry project scope, while Workspace scope belongs
            # to the canonical Run. Query the spine first so the page limit is
            # applied after the caller's Workspace boundary, not before it.
            runs = await self._run_store.list_by_status(
                status,
                limit=limit,
                project_id=project_id,
                workspace_id=workspace_id,
                after=after,
            )
            run_ids = [run.run_id for run in runs]
        records = await self._assemble_all(run_ids)
        return [record for record in records if record.run.status is status]

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
        position = (cursor_time(record.resume_at), record.run_id)
        if record.run.status in _RECOVERY_VISIBLE_STATUSES and record.resume_at <= now:
            return position, record
        return position, None

    async def list_hitl_due(
        self,
        *,
        now: datetime,
        limit: int = 100,
    ) -> list[DurableRunRecord]:
        """Elapsed human pauses the canonical Run agrees are paused.

        The deadline index is a continuation projection; the canonical Run is
        the authority. A continuation parked PAUSED before its Run was mirrored
        (a crash between the two writes) sits at the head of the index with a
        due deadline and is disqualified here on every tick -- so it is
        repaired in place through the same reconciliation the startup sweep
        runs, and the page is widened past any candidate that still does not
        qualify, rather than re-reading one permanent prefix forever.
        """
        requested = limit
        due: list[DurableRunRecord] = []
        for _ in range(_CANDIDATE_PAGES):
            run_ids = await self._continuations.list_hitl_due_run_ids(now=now, limit=requested)
            due = []
            for record in await self._assemble_all(run_ids):
                candidate = await self._reconcile_hitl_due_candidate(record, now)
                if candidate is not None:
                    due.append(candidate)
            if len(due) >= limit or len(run_ids) < requested:
                break
            requested *= 2
        return due[:limit]

    async def _reconcile_hitl_due_candidate(
        self,
        record: DurableRunRecord,
        now: datetime,
    ) -> DurableRunRecord | None:
        if record.run.status is not RunStatus.PAUSED:
            repaired = await self._reconcile_run(record.run_id)
            if repaired:
                refreshed = await self.get(record.run_id)
                if refreshed is not None:
                    record = refreshed
        if record.run.status is not RunStatus.PAUSED:
            return None
        deadline = earliest_hitl_deadline(record)
        if deadline is None or deadline > now:
            return None
        return record

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
        """Persist an answer and queue only valid verdicts for resume.

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
