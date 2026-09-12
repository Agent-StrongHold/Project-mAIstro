"""Bounded production recovery for persisted canonical Graph work (#837).

This module does not own a queue, timer, Run lifecycle, or execution policy. It
provides recovery ticks over the canonical Run spine and durable Graph
continuations. Physical work still crosses the canonical Attempt/lease/fence
boundary in :mod:`attempt_executor`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from maistro.graph.execution_state import GraphExecutionState
from maistro.runs.model import Run, RunStatus
from maistro.runs.recovery_events import RecoveryEventSink
from maistro.runs.store import RunStore, run_cursor_key
from maistro.runtime import ExecutionRuntime

from . import executor as traversal
from .attempt_executor import LiveAttemptOwned, NodeResolver, resume_durable_graph
from .fair_scan import DEFAULT_MAX_INSPECTED, ScanContinuation, ScanPage, fair_page_scan
from .launch import launch_state_from_run
from .protocol import DurableRunStore
from .types import DurableRunRecord

logger = logging.getLogger(__name__)

QueuedRunPredicate = Callable[[Run], bool]
QueuedNodeResolverFactory = Callable[[Run], NodeResolver]


@runtime_checkable
class PersistenceReconciler(Protocol):
    async def reconcile_persistence(self, *, limit: int = 100) -> int: ...


async def _reconcile_if_supported(store: DurableRunStore, *, limit: int) -> None:
    if isinstance(store, PersistenceReconciler):
        await store.reconcile_persistence(limit=limit)


@runtime_checkable
class DuePageScanner(Protocol):
    """A store that can page its due index without conflating two answers."""

    async def scan_due_page(
        self,
        *,
        now: datetime,
        limit: int = 100,
        after: tuple[str, str] | None = None,
        max_inspected: int = DEFAULT_MAX_INSPECTED,
    ) -> ScanPage[DurableRunRecord, tuple[str, str]]: ...


def _due_page_fetcher(
    store: DurableRunStore, moment: datetime
) -> Callable[
    [tuple[str, str] | None, int],
    Awaitable[list[DurableRunRecord] | ScanPage[DurableRunRecord, tuple[str, str]]],
]:
    """Fetch due candidates the most honest way this store supports.

    A store that filters its own due page -- the canonical one drops ids whose
    Run has since gone terminal -- returns an empty list both when nothing on
    the page is due and when the index has ended. Where the store can tell the
    two apart, take that answer, so a stale prefix is paged past rather than
    re-read from the top on every tick.
    """
    if isinstance(store, DuePageScanner):
        scanner = store

        async def scan(
            cursor: tuple[str, str] | None, page_size: int
        ) -> ScanPage[DurableRunRecord, tuple[str, str]]:
            return await scanner.scan_due_page(now=moment, limit=page_size, after=cursor)

        return scan

    async def listing(cursor: tuple[str, str] | None, page_size: int) -> list[DurableRunRecord]:
        return await store.list_due(now=moment, limit=page_size, after=cursor)

    return listing


_RESUME_ELIGIBLE_STATUSES = frozenset({RunStatus.WAITING, RunStatus.RUNNING})


def _is_resume_due(record: DurableRunRecord, moment: datetime) -> bool:
    """Report whether `record` is in a resumable status with an elapsed wait."""
    if record.run.status not in _RESUME_ELIGIBLE_STATUSES:
        return False
    return record.resume_at is not None and record.resume_at <= moment


async def _is_still_resume_due(
    store: DurableRunStore,
    run_id: str,
    moment: datetime,
) -> bool:
    """Re-read `run_id` and report whether it is still due for a resume."""
    current = await store.get(run_id)
    return current is not None and _is_resume_due(current, moment)


async def resume_due_graph_runs(
    *,
    store: DurableRunStore,
    run_store: RunStore,
    node_resolver: NodeResolver | None = None,
    node_resolver_factory: QueuedNodeResolverFactory | None = None,
    runtime: ExecutionRuntime | None = None,
    now: datetime | None = None,
    limit: int = 100,
    eligible: QueuedRunPredicate | None = None,
    events: RecoveryEventSink | None = None,
    scan: ScanContinuation[tuple[str, str]] | None = None,
) -> int:
    """Resume elapsed durable Graph waits or expired recovery claims.

    Exactly one of ``node_resolver`` (one resolver answers every candidate) or
    ``node_resolver_factory`` (the resolver is rebuilt from each candidate's
    own durable Run facts) must be supplied. The factory is the shape a
    production wakeup consumer needs: which node implementation may execute a
    resumed Graph is recorded on the Run itself, not in the waking process's
    memory (#62, #837).

    ``eligible`` is the same ownership guard ``recover_queued_graph_runs``
    takes: a tick that wakes due continuations without it would execute
    another consumer's paused work with this process's resolvers. The guard
    reads the Run, and the optimistic continuation version plus the canonical
    Attempt lease/fence still decide admission regardless of what it says.

    ``limit`` bounds *eligible, due* continuations resumed by this call, not a
    fixed prefix of the ``PAUSED``/``WAITING``/``RUNNING`` rows in the store
    (#1098). Candidates are discovered by paging the store's due index with an
    advancing keyset cursor and filtering eligibility as each page is read, so
    an arbitrarily large run of continuations owned by another consumer ahead
    of an eligible one cannot hide it forever behind a fixed-size query.

    ``scan`` is the continuation a repeated tick must hold across calls: the
    walk is bounded per call, so without one a prefix longer than the bound
    is never crossed, however many ticks run. With one, each tick resumes
    where the last stopped and restarts from the top only after walking off
    the end, so every due continuation is reached within a bounded number of
    ticks. One per (this seam, this store).

    A candidate whose resume raises an unexpected, candidate-local failure
    (anything but ``LiveAttemptOwned`` or a settled-race ``KeyError``/
    ``ValueError``) is isolated rather than allowed to abort the whole tick:
    the failure is logged, the candidate's durable state is left untouched for
    a later retry, and later independent candidates in this same batch are
    still attempted (#1143). A failure raised while *listing* candidates —
    the store/session itself, not one candidate's resume — is never caught
    here and aborts the tick, because that failure invalidates the whole scan
    rather than one Run.

    ``events`` carries the resume's crash dispositions onto the canonical
    Event stream when the caller provides a sink.
    """
    if limit <= 0:
        return 0
    _require_resolver_choice(node_resolver, node_resolver_factory)
    resolver_for = _per_run_resolver(node_resolver, node_resolver_factory)

    await _reconcile_if_supported(store, limit=limit)
    moment = now if now is not None else datetime.now(UTC)

    def _combined_eligible(candidate: DurableRunRecord) -> bool:
        if not _is_resume_due(candidate, moment):
            return False
        return eligible is None or eligible(candidate.run)

    candidates = await fair_page_scan(
        fetch_page=_due_page_fetcher(store, moment),
        cursor_of=_due_cursor_key,
        eligible=_combined_eligible,
        limit=limit,
        continuation=scan,
    )
    resumed = 0

    for candidate in candidates:
        try:
            await resume_durable_graph(
                candidate.run_id,
                store=store,
                node_resolver=resolver_for(candidate.run),
                runtime=runtime,
                run_store=run_store,
                events=events,
            )
        except LiveAttemptOwned:
            continue
        except asyncio.CancelledError:
            raise
        except (KeyError, ValueError) as exc:
            # Only a record still due after the failure is a real error; a
            # record another actor already moved on is settled, not resumed.
            if not await _is_still_resume_due(store, candidate.run_id, moment):
                continue
            _record_candidate_failure(candidate.run_id, seam="resume_due_graph_runs", error=exc)
            continue
        except Exception as exc:
            _record_candidate_failure(candidate.run_id, seam="resume_due_graph_runs", error=exc)
            continue
        resumed += 1

    return resumed


def _due_cursor_key(record: DurableRunRecord) -> tuple[str, str]:
    """The ``(resume_at_iso, run_id)`` keyset position of one due candidate.

    ``store.list_due`` only ever returns records with a non-None ``resume_at``
    (it filters to exactly that before returning), so this never sees the
    unset case in practice; the guard exists so a future relaxation of that
    contract fails loudly here rather than silently mis-paginating.
    """
    if record.resume_at is None:
        raise ValueError(f"due candidate {record.run_id!r} has no resume_at to page by")
    return (record.resume_at.isoformat(), record.run_id)


def _record_candidate_failure(run_id: str, *, seam: str, error: BaseException) -> None:
    """Log one candidate-local recovery failure without aborting the batch (#1143).

    The failing candidate's durable state is left exactly as the store already
    has it: not silently dropped, not falsely marked succeeded. It remains
    eligible and is retried on a later tick. This call is the observability
    half of that guarantee — the failure must be inspectable, not merely
    survived.
    """
    logger.error(
        "recovery candidate failed and was isolated: seam=%s run_id=%s error=%s: %s",
        seam,
        run_id,
        type(error).__name__,
        error,
    )


def _initial_queued_record(run: Run) -> DurableRunRecord:
    """Reconstruct checkpoint 1 from the immutable admission snapshot."""
    graph = run.graph.materialize()
    initial_inputs, blackboard_metadata = launch_state_from_run(run)
    state = GraphExecutionState(
        run_id=run.run_id,
        active_node_ids=(traversal._entry_node(graph),),
        blackboard_snapshot={
            "task_objective": graph.name,
            "metadata": blackboard_metadata,
            "node_annotations": {},
        },
        metadata={"initial_inputs": initial_inputs, "hitl_answers": {}},
    )
    return DurableRunRecord(run=run, graph_state=state, version=1)


async def _claim_initial_continuation(
    store: DurableRunStore,
    run: Run,
) -> DurableRunRecord | None:
    current = await store.get(run.run_id)
    if current is not None:
        return current

    try:
        await store.create(_initial_queued_record(run))
    except Exception:
        current = await store.get(run.run_id)
        if current is None:
            raise
        return None

    current = await store.get(run.run_id)
    if current is None:  # pragma: no cover - persistence contract breach
        raise RuntimeError(f"initial continuation for Run {run.run_id!r} disappeared after create")
    return current


async def _resume_queued_candidate(
    run: Run,
    *,
    store: DurableRunStore,
    run_store: RunStore,
    node_resolver_factory: QueuedNodeResolverFactory,
    runtime: ExecutionRuntime | None,
    events: RecoveryEventSink | None,
) -> bool:
    current = await _claim_initial_continuation(store, run)
    if current is None or current.run.status is not RunStatus.QUEUED:
        return False

    try:
        await resume_durable_graph(
            run.run_id,
            store=store,
            node_resolver=node_resolver_factory(run),
            runtime=runtime,
            run_store=run_store,
            events=events,
        )
    except LiveAttemptOwned:
        return False
    except asyncio.CancelledError:
        raise
    except (KeyError, ValueError) as exc:
        latest = await store.get(run.run_id)
        if latest is None:
            # Not "someone else moved it on" -- the record is gone entirely,
            # which the initial claim above just proved existed. That is a
            # persistence-integrity failure, not a candidate-local resolver
            # bug, and stays raise-worthy rather than isolated.
            raise
        if latest.run.status is not RunStatus.QUEUED:
            # Another actor already moved this Run on; its committed
            # disposition is the real outcome, not a failure to isolate.
            return False
        _record_candidate_failure(run.run_id, seam="recover_queued_graph_runs", error=exc)
        return False
    except Exception as exc:
        _record_candidate_failure(run.run_id, seam="recover_queued_graph_runs", error=exc)
        return False
    return True


async def recover_queued_graph_runs(
    *,
    store: DurableRunStore,
    run_store: RunStore,
    node_resolver_factory: QueuedNodeResolverFactory,
    eligible: QueuedRunPredicate,
    runtime: ExecutionRuntime | None = None,
    limit: int = 100,
    events: RecoveryEventSink | None = None,
    scan: ScanContinuation[tuple[str, str]] | None = None,
) -> int:
    """Recover admitted durable Graph Runs around checkpoint 1.

    Checkpoint 1 is reconstructed exclusively from durable Run facts. New
    non-empty launch state is required to be snapshotted in Run provenance by
    the public admission helper before physical execution can start, so this
    recovery path never substitutes empty inputs for work the caller actually
    admitted.

    ``limit`` bounds *eligible* QUEUED Runs recovered by this call, not a
    fixed prefix of every QUEUED Run in the store (#1127, #1098). Candidates
    are discovered by paging `RunStore.list_by_status` with an advancing
    keyset cursor and applying ``eligible`` as each page is read, so an
    arbitrarily large run of foreign-owned QUEUED Runs ahead of an eligible
    one cannot hide it forever behind a fixed-size query.

    ``scan`` is the continuation a repeated tick must hold across calls, for
    the reason ``resume_due_graph_runs`` gives: the per-call walk is bounded,
    and a foreign-owned prefix longer than the bound is crossed only by a
    tick that resumes where the last one stopped. One per (this seam, this
    Run store).

    A candidate whose resume raises an unexpected, candidate-local failure is
    isolated rather than allowed to abort the whole tick: the failure is
    logged and later independent candidates in this same batch are still
    attempted (#1143). A failure raised while *listing* candidates aborts the
    tick, because that failure invalidates the whole scan rather than one Run.

    ``events`` carries each recovery's crash dispositions onto the canonical
    Event stream when the caller provides a sink.
    """
    if limit <= 0:
        return 0

    await _reconcile_if_supported(store, limit=limit)
    candidates = await fair_page_scan(
        fetch_page=lambda cursor, page_size: run_store.list_by_status(
            RunStatus.QUEUED, limit=page_size, after=cursor
        ),
        cursor_of=run_cursor_key,
        eligible=eligible,
        limit=limit,
        continuation=scan,
    )
    recovered = 0
    for run in candidates:
        if await _resume_queued_candidate(
            run,
            store=store,
            run_store=run_store,
            node_resolver_factory=node_resolver_factory,
            runtime=runtime,
            events=events,
        ):
            recovered += 1
    return recovered


def _require_resolver_choice(
    node_resolver: NodeResolver | None,
    node_resolver_factory: QueuedNodeResolverFactory | None,
) -> None:
    """Enforce the exactly-one resolver contract the wakeup tick documents."""
    if (node_resolver is None) == (node_resolver_factory is None):
        raise ValueError(
            "resume_due_graph_runs requires exactly one of node_resolver or node_resolver_factory"
        )


def _per_run_resolver(
    node_resolver: NodeResolver | None,
    node_resolver_factory: QueuedNodeResolverFactory | None,
) -> Callable[[Run], NodeResolver]:
    """Fold the two resolver shapes into one per-Run lookup.

    A single resolver answers every Run; a factory answers each from its own
    durable facts. The tick should not have to care which shape its caller chose.
    """
    if node_resolver is not None:
        return lambda _run: node_resolver
    if node_resolver_factory is not None:
        return node_resolver_factory
    raise ValueError(  # pragma: no cover - _require_resolver_choice ran first
        "resume_due_graph_runs requires exactly one of node_resolver or node_resolver_factory"
    )


__all__ = ["recover_queued_graph_runs", "resume_due_graph_runs"]
