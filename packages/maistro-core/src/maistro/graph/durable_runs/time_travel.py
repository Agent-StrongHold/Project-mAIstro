"""Load and fork durable Graph state at a canonical event sequence (#1612).

Time travel on the canonical spine has two operations, and neither one
executes anything:

``load(run_id, sequence_n)``
    Reconstruct the persisted :class:`GraphExecutionState` at position
    ``sequence_n`` of the Run's durable state timeline, plus the inclusive
    event slice ``1..sequence_n``. Pure observation: it reads the continuation
    and the canonical Run and writes nothing, claims no lease, dispatches no
    tool, and invokes no provider.

``fork(run_id, sequence_n, reason)``
    Persist a **child Run** whose launch state is the historical state, then
    stop. The fork itself starts no work; new effects begin only when a caller
    explicitly resumes the child through the ordinary durable executor, where
    every physical effect crosses the existing
    ``Attempt -> AttemptExecutionService -> ExecutionRuntime`` firewall and its
    governed Invocation/retry/authorization contract.

## The event sequence space

A Run's durable state timeline records one epoch each time the canonical
durable store (:class:`~maistro.graph.durable_runs.canonical_store.CanonicalDurableRunStore`)
persists a *new distinct* ``GraphExecutionState`` for that Run, ordered by a
per-Run ``sequence`` starting at 1 (the launch state recorded at ``create``).
``sequence_n`` names a position in that timeline **inclusively**: the state
returned is exactly the state persisted at that position, and the event slice
covers ``1..sequence_n`` including it. The supported range is
``1 <= sequence_n <= len(timeline)``; position zero does not exist because a
Run has no state before its first durable write.

Every epoch carries the content hash of its state and, when the state was a
traversal fact, the linked ``TraversalCommit.commit_sequence`` or
``TraversalCheckpoint.checkpoint_sequence``. ``load`` re-derives those hashes
and cross-checks the links, so pruned or tampered evidence fails closed
instead of reconstructing a state nobody persisted.

## Fork shape: child Run, never a new Attempt on the source

Which lifecycle states create a new Attempt on an existing Run, and which
require a child Run, is decided per case:

* A **new Attempt on the existing Run** is reserved for the paths that
  continue the same logical execution: crash recovery
  (``CancellationCause.RECOVERED``) and HITL resume. Those are the only
  writers that may append physical work under an existing Run identity.
* **Fork always requires a child Run.** A terminal source Run cannot be
  reopened or rewritten merely to reuse its id, and its settled NodeRuns and
  Attempts cannot gain physical work without rewriting history. A live source
  Run (QUEUED/RUNNING/WAITING/PAUSED) holds its execution authority under the
  canonical Attempt lease/fence; a forked Attempt would have to take that
  fence from the live owner. So a fork branches identity instead: a child Run
  with ``parent_run_id`` naming the source, the source's admitted Graph
  snapshot, and the historical traversal state as its launch state.

The source Run is never written by a fork. Inherited Graph state is data:
completed visits contribute their recorded decisions and blackboard content,
and are not re-executed by inspection or by the fork. Only the child's own
frontier execution produces new effects.

Fork provenance records the parent Run, the source event position, the
reason, the Graph revision, the Goal named by the parent's admission when one
exists, and the latest Goal/Rubric revisions applied to the parent's eval
evidence when any exists -- before any new work can start, because the child
Run, its continuation and its first timeline epoch are one durable sequence
that completes before ``fork`` returns.

Recipe and code-registry versions follow the same rule recovery uses: which
node implementation may execute is resolved from the Run's own durable facts
at execution time and fails closed there (``UnknownNode``), not at admission.
A fork cannot drift versions by construction -- the child carries the
parent's immutable Graph snapshot, content-identical -- and a loaded state
recorded under a different Graph revision than the Run's admitted snapshot is
refused outright.

ADR-055 (replay research) remains Proposed and is not implemented here; the
shapes above are the accepted ADR-062 / ADR-082826-d9f5 contracts only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from maistro.graph.execution_state import GraphExecutionState
from maistro.graph.traversal_commit import (
    TraversalCheckpoint,
    TraversalCommit,
    graph_state_hash,
)
from maistro.runs.model import Run
from maistro.runs.store import RunIntegrityError, RunStore

from .continuation import GraphContinuation, GraphContinuationStore, GraphStateEpoch
from .types import DurableRunRecord

#: Provenance key on a forked child Run naming where the fork came from.
DURABLE_GRAPH_FORK_PROVENANCE = "durable_graph_fork"

#: Graph-state metadata keys that name the *source* Run's own visits. A forked
#: child has no NodeRuns yet, so pause/HITL/deferral entries pointing at the
#: parent's visit identities would be corrupting: the child's frontier must
#: re-enter as new work under the child's own NodeRuns.
_SOURCE_VISIT_METADATA_KEYS = (
    "pause",
    "pauses",
    "hitl_answers",
    "hitl_settlements",
    "deferred_frontier",
    "deferred_fanins",
)


class UnknownGraphRunError(KeyError):
    """A load or fork named a Run the canonical spine does not hold."""


class SequenceOutOfRangeError(ValueError):
    """A requested event position is outside the Run's recorded timeline."""


class StateHistoryIntegrityError(RunIntegrityError):
    """Recorded state history failed its content or linkage verification."""


@dataclass(frozen=True, slots=True)
class GraphStateLoad:
    """The durable Graph state at one event position, and the slice behind it.

    ``events`` is the inclusive timeline slice ``1..sequence``; the traversal
    facts linked to those epochs are the commits and checkpoints whose
    sequences fall within the slice's linked ranges.
    """

    run_id: str
    sequence: int
    graph_state: GraphExecutionState
    state_hash: str
    graph_snapshot_hash: str
    events: tuple[GraphStateEpoch, ...]
    traversal_commits: tuple[TraversalCommit, ...]
    traversal_checkpoints: tuple[TraversalCheckpoint, ...]


def _require_sequence_text(value: str, message: str) -> str:
    if not value.strip():
        raise ValueError(message)
    return value


def _existing_timeline(previous: GraphContinuation | None) -> tuple[GraphStateEpoch, ...]:
    """The recorded history a write extends; empty when there is no prior write."""
    return previous.state_timeline if previous is not None else ()


def _linked_fact_sequences(
    continuation: GraphContinuation,
    state_hash: str,
) -> tuple[int | None, int | None]:
    """Sequences of the newest traversal facts claiming ``state_hash``.

    Either side is ``None`` unless a commit or checkpoint exists whose content
    hash matches, which is what ties a timeline epoch to its evidence.
    """
    commit_sequence = None
    for commit in reversed(continuation.traversal_commits):
        if commit.resulting_state_hash == state_hash:
            commit_sequence = commit.commit_sequence
            break
    checkpoint_sequence = None
    for checkpoint in reversed(continuation.traversal_checkpoints):
        if checkpoint.state_hash == state_hash:
            checkpoint_sequence = checkpoint.checkpoint_sequence
            break
    return commit_sequence, checkpoint_sequence


def state_epoch_appended(
    continuation: GraphContinuation,
    *,
    previous: GraphContinuation | None,
    graph_snapshot_hash: str,
    now: datetime | None = None,
) -> GraphContinuation:
    """Return ``continuation`` with a timeline epoch appended when state changed.

    The canonical durable store calls this at its persistence boundary, so
    every distinct persisted ``GraphExecutionState`` becomes a loadable event
    position and no other writer has to remember to record one. A write whose
    state content is unchanged extends no epoch: positions stay stable once
    recorded, which is what makes a sequence name the same state forever.

    A continuation persisted by a writer that predates the timeline (legacy
    document stores) starts its history at its first post-convergence write.
    """
    timeline = _existing_timeline(previous)
    state_hash = graph_state_hash(continuation.graph_state)
    last = timeline[-1] if timeline else None
    if last is not None and last.state_hash == state_hash:
        # Unchanged content extends no epoch -- but the write must still carry
        # the recorded history, or every state-stable checkpoint would wipe
        # the timeline the next append is supposed to extend.
        if continuation.state_timeline == timeline:
            return continuation
        return continuation.model_copy(update={"state_timeline": timeline})
    commit_sequence, checkpoint_sequence = _linked_fact_sequences(continuation, state_hash)
    epoch = GraphStateEpoch(
        sequence=last.sequence + 1 if last is not None else 1,
        state=continuation.graph_state,
        state_hash=state_hash,
        graph_snapshot_hash=graph_snapshot_hash,
        recorded_at=now if now is not None else datetime.now(UTC),
        commit_sequence=commit_sequence,
        checkpoint_sequence=checkpoint_sequence,
    )
    return continuation.model_copy(update={"state_timeline": (*timeline, epoch)})


async def load_state(
    *,
    run_id: str,
    sequence: int,
    continuations: GraphContinuationStore,
    run_store: RunStore,
) -> GraphStateLoad:
    """Read the durable Graph state at ``sequence``; write nothing anywhere.

    Deterministic: the same persisted timeline yields the same result on every
    call, because every returned fact is read back from durable content and
    re-verified against it.
    """
    continuation = await continuations.get(run_id)
    if continuation is None:
        raise UnknownGraphRunError(f"no durable Graph continuation for run {run_id!r}")
    run = await run_store.get_run(run_id)
    if run is None:
        raise UnknownGraphRunError(f"run {run_id!r} is not on the canonical spine")
    timeline = continuation.state_timeline
    if sequence < 1 or sequence > len(timeline):
        raise SequenceOutOfRangeError(
            f"event sequence {sequence} is outside the recorded timeline of run "
            f"{run_id!r}: positions 1..{len(timeline)} exist"
        )
    epoch = timeline[sequence - 1]
    _verify_epoch(epoch, run=run, continuation=continuation)
    commits, checkpoints = _slice_linked_facts(
        continuation,
        commit_limit=epoch.commit_sequence,
        checkpoint_limit=epoch.checkpoint_sequence,
    )
    return GraphStateLoad(
        run_id=run_id,
        sequence=sequence,
        graph_state=epoch.state,
        state_hash=epoch.state_hash,
        graph_snapshot_hash=epoch.graph_snapshot_hash,
        events=tuple(timeline[:sequence]),
        traversal_commits=commits,
        traversal_checkpoints=checkpoints,
    )


def _slice_linked_facts(
    continuation: GraphContinuation,
    *,
    commit_limit: int | None,
    checkpoint_limit: int | None,
) -> tuple[tuple[TraversalCommit, ...], tuple[TraversalCheckpoint, ...]]:
    """The traversal facts whose sequences fall within the inclusive slice."""
    commits = tuple(
        commit
        for commit in continuation.traversal_commits
        if commit_limit is not None and commit.commit_sequence <= commit_limit
    )
    checkpoints = tuple(
        item
        for item in continuation.traversal_checkpoints
        if checkpoint_limit is not None and item.checkpoint_sequence <= checkpoint_limit
    )
    return commits, checkpoints


def _verify_epoch(
    epoch: GraphStateEpoch,
    *,
    run: Run,
    continuation: GraphContinuation,
) -> None:
    """Fail closed unless the epoch's content and traversal links still hold."""
    if graph_state_hash(epoch.state) != epoch.state_hash:
        raise StateHistoryIntegrityError(
            f"timeline epoch {epoch.sequence} of run {run.run_id!r} does not match "
            "its recorded state hash"
        )
    if epoch.graph_snapshot_hash != run.graph.content_hash:
        raise StateHistoryIntegrityError(
            f"timeline epoch {epoch.sequence} of run {run.run_id!r} was recorded for "
            f"Graph revision {epoch.graph_snapshot_hash!r}, but the Run is admitted for "
            f"{run.graph.content_hash!r}; the revisions are incompatible"
        )
    if epoch.commit_sequence is not None:
        _verify_commit_link(epoch, continuation, run)
    elif epoch.checkpoint_sequence is not None:
        _verify_checkpoint_link(epoch, continuation, run)


def _verify_commit_link(
    epoch: GraphStateEpoch,
    continuation: GraphContinuation,
    run: Run,
) -> None:
    """Fail closed unless the linked TraversalCommit still carries this state."""
    commit = next(
        (
            item
            for item in continuation.traversal_commits
            if item.commit_sequence == epoch.commit_sequence
        ),
        None,
    )
    if commit is None or commit.resulting_state_hash != epoch.state_hash:
        raise StateHistoryIntegrityError(
            f"timeline epoch {epoch.sequence} of run {run.run_id!r} links "
            f"TraversalCommit {epoch.commit_sequence}, which no longer exists with "
            "the recorded resulting state; the traversal evidence was pruned or "
            "rewritten"
        )


def _verify_checkpoint_link(
    epoch: GraphStateEpoch,
    continuation: GraphContinuation,
    run: Run,
) -> None:
    """Fail closed unless the linked TraversalCheckpoint still carries this state."""
    checkpoint = next(
        (
            item
            for item in continuation.traversal_checkpoints
            if item.checkpoint_sequence == epoch.checkpoint_sequence
        ),
        None,
    )
    if checkpoint is None or checkpoint.state_hash != epoch.state_hash:
        raise StateHistoryIntegrityError(
            f"timeline epoch {epoch.sequence} of run {run.run_id!r} links "
            f"TraversalCheckpoint {epoch.checkpoint_sequence}, which no longer "
            "exists with the recorded state; the traversal evidence was pruned or "
            "rewritten"
        )


def fork_provenance(
    *,
    parent: Run,
    source_sequence: int,
    source_state_hash: str,
    reason: str,
    latest_eval: dict[str, Any] | None = None,
    forked_at: datetime,
) -> dict[str, Any]:
    """Return the durable fork fact recorded on the child Run before new work.

    The Graph revision is the parent's admitted snapshot hash -- the only
    Graph the timeline may reference. The Goal named by the parent's admission
    and the latest Goal/Rubric revisions scored against the parent travel with
    the fork when they exist; eval score rows themselves are Run-keyed
    evidence and stay on the parent, which the child names as its origin.
    """
    goal_id = parent.provenance.get("goal_id")
    fact: dict[str, Any] = {
        "parent_run_id": parent.run_id,
        "source_event_sequence": source_sequence,
        "source_state_hash": source_state_hash,
        "graph_snapshot_hash": parent.graph.content_hash,
        "reason": _require_sequence_text(reason, "a fork requires a non-blank reason"),
        "forked_at": forked_at.isoformat(),
    }
    if isinstance(goal_id, str) and goal_id.strip():
        fact["goal_id"] = goal_id
    if latest_eval is not None:
        for key in ("goal_id", "goal_revision", "rubric_id", "rubric_revision"):
            if latest_eval.get(key) is not None:
                fact[key] = latest_eval[key]
    return {DURABLE_GRAPH_FORK_PROVENANCE: fact}


def forked_child_state(
    state: GraphExecutionState,
    *,
    child_run_id: str,
) -> GraphExecutionState:
    """Retarget the source state to the child identity and drop parent visits.

    Everything the child inherits is durable data: frontier, cycle, visits,
    routing history and blackboard. What it does not inherit is the source's
    own visit bookkeeping -- pauses, HITL answers and deferrals name the
    parent's NodeRun identities, and carrying them would let the child read
    its parent's settlement as its own.
    """
    values = state.model_dump(mode="json")
    metadata = dict(values.get("metadata") or {})
    for key in _SOURCE_VISIT_METADATA_KEYS:
        metadata.pop(key, None)
    values["run_id"] = child_run_id
    values["metadata"] = metadata
    return GraphExecutionState.model_validate(values)


if TYPE_CHECKING:

    def _vulture_time_travel_contract_usage(
        store: Any,
        load: GraphStateLoad,
        epoch: GraphStateEpoch,
    ) -> None:
        _ = store.load_state
        _ = store.fork_from_state
        _ = load.run_id
        _ = load.sequence
        _ = load.graph_state
        _ = load.state_hash
        _ = load.graph_snapshot_hash
        _ = load.events
        _ = load.traversal_commits
        _ = load.traversal_checkpoints
        _ = epoch.sequence
        _ = epoch.state
        _ = epoch.state_hash
        _ = epoch.graph_snapshot_hash
        _ = epoch.recorded_at
        _ = epoch.commit_sequence
        _ = epoch.checkpoint_sequence
        _ = UnknownGraphRunError
        _ = SequenceOutOfRangeError
        _ = StateHistoryIntegrityError
        _ = DURABLE_GRAPH_FORK_PROVENANCE
        _ = DurableRunRecord

    _: object
    _ = _vulture_time_travel_contract_usage


__all__ = [
    "DURABLE_GRAPH_FORK_PROVENANCE",
    "GraphStateEpoch",
    "GraphStateLoad",
    "SequenceOutOfRangeError",
    "StateHistoryIntegrityError",
    "UnknownGraphRunError",
    "fork_provenance",
    "forked_child_state",
    "load_state",
    "state_epoch_appended",
]
