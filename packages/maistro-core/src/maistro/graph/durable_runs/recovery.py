"""Bounded production recovery for persisted canonical Graph work (#837).

This module does not own a queue, timer, Run lifecycle, or execution policy. It
provides recovery ticks over the canonical Run spine and durable Graph
continuations. Physical work still crosses the canonical Attempt/lease/fence
boundary in :mod:`attempt_executor`.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from maistro.graph.execution_state import GraphExecutionState
from maistro.runs.model import Run, RunStatus
from maistro.runs.recovery_events import RecoveryEventSink
from maistro.runs.store import RunStore
from maistro.runtime import ExecutionRuntime

from . import executor as traversal
from .attempt_executor import LiveAttemptOwned, NodeResolver, resume_durable_graph
from .launch import launch_state_from_run
from .protocol import DurableRunStore, RecoveryInfrastructureError
from .types import DurableRunRecord

QueuedRunPredicate = Callable[[Run], bool]
QueuedNodeResolverFactory = Callable[[Run], NodeResolver]

logger = logging.getLogger(__name__)


class _CandidateStore:
    """Turn unclassified store failures into an explicit tick-wide failure.

    Optimistic races are already represented by ``KeyError``/``ValueError``
    and remain candidate-local. Other store exceptions mean the recovery
    boundary cannot know whether the next candidate can be read or claimed.
    """

    def __init__(self, store: DurableRunStore) -> None:
        self._store = store

    def __getattr__(self, name: str) -> Any:
        operation = getattr(self._store, name)

        async def call(*args: Any, **kwargs: Any) -> Any:
            try:
                return await operation(*args, **kwargs)
            except (KeyError, ValueError, RecoveryInfrastructureError):
                raise
            except Exception as exc:
                raise RecoveryInfrastructureError(
                    f"durable recovery store operation {name!r} failed"
                ) from exc

        return call


class _CandidateRunStore:
    """Apply the same boundary to canonical Run/NodeRun/Attempt persistence.

    The durable continuation store is only half of the recovery path. Once a
    canonical Run is present, execution reads and writes the separate
    ``RunStore`` too. A raw database/session exception there is infrastructure
    wide; lifecycle races and integrity errors remain candidate-local through
    their ``KeyError``/``ValueError`` base classes.
    """

    def __init__(self, store: RunStore) -> None:
        self._store = store

    def __getattr__(self, name: str) -> Any:
        operation = getattr(self._store, name)

        async def call(*args: Any, **kwargs: Any) -> Any:
            try:
                return await operation(*args, **kwargs)
            except (KeyError, ValueError, RecoveryInfrastructureError):
                raise
            except Exception as exc:
                raise RecoveryInfrastructureError(
                    f"canonical recovery RunStore operation {name!r} failed"
                ) from exc

        return call


class NodeResolverUnavailable(RuntimeError):
    """A candidate's node resolver could not be built from its Run.

    The message is deliberately stable: it names the Run and the failure type
    only, so the executor's failure boundary can persist it on the failed Run
    without copying provider or credential text from the underlying error.
    The original exception stays attached as ``__cause__`` for in-process
    diagnosis.
    """


# ``key=value`` / ``key: value`` / ``'key': 'value'`` / ``Authorization: Bearer x``
_SAFE_DETAIL = re.compile(
    r"""(?ix)
    ["']?\b(?P<key>password|passwd|token|secret|api[_-]?key|authorization)\b["']?
    \s*[=:]\s*["']?
    (?:bearer\s+)?
    [^\s,;"'}\])]+["']?
    """
)
# Bare ``Bearer <token>`` fragments that carry no header name.
_SAFE_BEARER = re.compile(r"(?i)\bbearer\s+[^\s,;\"'}\])]+")
# Provider-style key literals that identify themselves by prefix.
_SAFE_KEY_LITERAL = re.compile(
    r"\b(?:sk|pk|rk)-[A-Za-z0-9_\-]{6,}"
    r"|\bgh[pousr]_[A-Za-z0-9]{16,}"
    r"|\bxox[abprs]-[A-Za-z0-9\-]{8,}"
    r"|\bAKIA[0-9A-Z]{16}\b"
)


def _redacted(detail: str) -> str:
    detail = _SAFE_DETAIL.sub(lambda match: f"{match.group('key')}=<redacted>", detail)
    detail = _SAFE_BEARER.sub("Bearer <redacted>", detail)
    return _SAFE_KEY_LITERAL.sub("<redacted-key>", detail)


def _sanitized_cause(exc: BaseException) -> str:
    """Return bounded log evidence without copying provider/credential text."""
    detail = str(exc).splitlines()[0].strip() if str(exc) else ""
    detail = _redacted(detail)[:240]
    return f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__


def _lazy_resolver(
    run: Run,
    resolver_for: Callable[[Run], NodeResolver],
) -> NodeResolver:
    """Resolve a candidate only inside the executor's failure boundary.

    A factory failure surfaces as :class:`NodeResolverUnavailable`, whose
    stable message is what the boundary persists on the failed Run; the raw
    factory error is never written to durable state.
    """
    resolved: NodeResolver | None = None

    def resolve(node_id: str, graph: Any) -> Any:
        nonlocal resolved
        if resolved is None:
            try:
                resolved = resolver_for(run)
            except Exception as exc:
                raise NodeResolverUnavailable(
                    f"node resolver could not be built for Run {run.run_id!r}: {type(exc).__name__}"
                ) from exc
        return resolved(node_id, graph)

    return resolve


@runtime_checkable
class PersistenceReconciler(Protocol):
    async def reconcile_persistence(self, *, limit: int = 100) -> int: ...


async def _reconcile_if_supported(store: DurableRunStore, *, limit: int) -> None:
    if isinstance(store, PersistenceReconciler):
        await store.reconcile_persistence(limit=limit)


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


def _log_candidate_failure(run_id: str, cause: str) -> None:
    """Make one bounded candidate failure observable without a traceback."""
    logger.warning(
        "due_graph_recovery_candidate_failed run_id=%s continuation_id=%s cause=%s",
        run_id,
        run_id,
        cause,
    )


async def _resume_due_candidate(
    candidate: DurableRunRecord,
    *,
    store: DurableRunStore,
    run_store: RunStore | None,
    resolver_for: Callable[[Run], NodeResolver],
    runtime: ExecutionRuntime | None,
    moment: datetime,
    events: RecoveryEventSink | None,
) -> bool:
    """Attempt one candidate and isolate only failures that belong to it."""
    candidate_store = _CandidateStore(store)
    candidate_run_store = _CandidateRunStore(run_store) if run_store is not None else None
    try:
        result = await resume_durable_graph(
            candidate.run_id,
            store=candidate_store,
            node_resolver=_lazy_resolver(candidate.run, resolver_for),
            runtime=runtime,
            run_store=candidate_run_store,
            events=events,
        )
    except RecoveryInfrastructureError:
        # A store/session failure invalidates the scan; claiming success for
        # later candidates would make recovery evidence untruthful.
        raise
    except LiveAttemptOwned:
        return False
    except (KeyError, ValueError):
        # Only a record still due after the failure is a real error; a record
        # another actor already moved on is settled, not resumed.
        if not await _is_still_resume_due(candidate_store, candidate.run_id, moment):
            return False
        raise
    except Exception as exc:
        # Resolver/event failures that escape the executor are local to this
        # Run. Keep the candidate eligible for a later tick, but do not let it
        # starve the rest of this bounded batch.
        _log_candidate_failure(candidate.run_id, _sanitized_cause(exc))
        return False

    if result is not None and result.run.status is RunStatus.FAILED:
        _log_candidate_failure(
            candidate.run_id,
            _sanitized_cause(ValueError(result.run.error or "failed")),
        )
    return True


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

    ``events`` carries the resume's crash dispositions onto the canonical
    Event stream when the caller provides a sink.

    Failure classification is explicit: ``LiveAttemptOwned`` and optimistic
    ``KeyError``/``ValueError`` races are candidate-local; resolver and node
    failures are terminalized by the executor (or logged and retried if they
    escape it); ``RecoveryInfrastructureError`` aborts the tick because the
    store/session may invalidate every candidate.
    """
    if limit <= 0:
        return 0
    _require_resolver_choice(node_resolver, node_resolver_factory)
    resolver_for = _per_run_resolver(node_resolver, node_resolver_factory)

    try:
        await _reconcile_if_supported(store, limit=limit)
        moment = now if now is not None else datetime.now(UTC)
        candidates = await store.list_due(now=moment, limit=limit)
    except RecoveryInfrastructureError:
        raise
    except Exception as exc:
        raise RecoveryInfrastructureError("durable recovery scan failed") from exc
    resumed = 0

    for candidate in candidates:
        if not _is_resume_due(candidate, moment):
            continue
        if eligible is not None and not eligible(candidate.run):
            continue
        if await _resume_due_candidate(
            candidate,
            store=store,
            run_store=run_store,
            resolver_for=resolver_for,
            runtime=runtime,
            moment=moment,
            events=events,
        ):
            resumed += 1

    return resumed


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
    except (KeyError, ValueError):
        latest = await store.get(run.run_id)
        if latest is None:
            raise
        if latest.run.status is not RunStatus.QUEUED:
            return False
        raise
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
) -> int:
    """Recover admitted durable Graph Runs around checkpoint 1.

    Checkpoint 1 is reconstructed exclusively from durable Run facts. New
    non-empty launch state is required to be snapshotted in Run provenance by
    the public admission helper before physical execution can start, so this
    recovery path never substitutes empty inputs for work the caller actually
    admitted.

    ``events`` carries each recovery's crash dispositions onto the canonical
    Event stream when the caller provides a sink.
    """
    if limit <= 0:
        return 0

    await _reconcile_if_supported(store, limit=limit)
    candidates = await run_store.list_by_status(RunStatus.QUEUED, limit=limit)
    recovered = 0
    for run in candidates:
        if eligible(run) and await _resume_queued_candidate(
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
