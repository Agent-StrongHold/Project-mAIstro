"""Write the aggregate's lifecycle back to the store that owns the entities.

Split out of the traversal executor because two boundaries need the same rule
and must not answer it differently: the executor, which walks a graph while
holding a `DurableRunStore` that is not itself canonical, and
`CanonicalDurableRunStore`, whose `update` is the only place a record reaches
persistence at all. One rule, two callers, rather than two reconcilers that
drift apart the first time either is fixed.
"""

from __future__ import annotations

from maistro.runs.lifecycle import transition_path
from maistro.runs.model import AcceptedNodeOutcome, AttemptResult, NodeRun
from maistro.runs.store import RunStore

from .types import DurableRunRecord


async def canonical_outcome(
    outcome: AcceptedNodeOutcome | None,
    *,
    run_store: RunStore,
) -> AcceptedNodeOutcome | None:
    """Restate accepted evidence in terms of the Attempt the store actually holds.

    An `AcceptedNodeOutcome` binds a logical outcome to exactly one physical
    Attempt, and the canonical store refuses one whose evidence does not match
    its own row. The record's copy of that Attempt has been through the durable
    store's JSON envelope, which the canonical row has not, so the two describe
    the same Attempt in different shapes and the guard -- rightly -- rejects the
    difference (#566). The binding is the `attempt_id`; restating the evidence
    from the store's own row keeps that binding while letting the store validate
    against itself.
    """
    if outcome is None:
        return None
    attempt = await run_store.get_attempt(outcome.attempt_result.attempt_id)
    if attempt is None:
        return outcome
    return outcome.model_copy(update={"attempt_result": AttemptResult.from_attempt(attempt)})


async def mirror_node_run(node_run: NodeRun, *, run_store: RunStore) -> None:
    """Walk one canonical NodeRun up to the status the record already gave it."""
    canonical = await run_store.get_node_run(node_run.node_run_id)
    if canonical is None or canonical.status is node_run.status:
        return
    outcome = await canonical_outcome(node_run.accepted_outcome, run_store=run_store)
    for step in transition_path(canonical.status, node_run.status):
        final = step is node_run.status
        await run_store.transition_node_run(
            node_run.node_run_id,
            step,
            result=node_run.result if final else None,
            error=node_run.error if final else None,
            accepted_outcome=outcome if final else None,
        )


async def mirror_run(record: DurableRunRecord, *, run_store: RunStore) -> None:
    """Walk the canonical Run up to the status the record already gave it."""
    run = await run_store.get_run(record.run_id)
    if run is None or run.status is record.run.status:
        return
    for step in transition_path(run.status, record.run.status):
        final = step is record.run.status
        await run_store.transition_run(
            record.run_id,
            step,
            result=record.run.result if final else None,
            error=record.run.error if final else None,
        )


async def mirror_lifecycle(
    record: DurableRunRecord,
    *,
    run_store: RunStore | None,
) -> None:
    """Carry the record's own lifecycle moves into the store that owns them.

    Identity alone would be worse than neither: a canonical NodeRun frozen at
    the status it was minted with, while the record calls the same node
    finished, is a row that lies to every canonical consumer and that a global
    lease sweep would then act on. The traversal fold is synchronous and
    applies its transitions in the aggregate, so the write-back happens here,
    against what the store currently holds rather than against what this
    process last saw -- another writer may have moved the row in between.

    The gap is walked, not jumped: `transition_path` finds the shortest legal
    sequence, so a node the record answered out of a HITL pause reaches
    COMPLETED via QUEUED and RUNNING instead of demanding an edge the lifecycle
    table does not have. Only the final hop carries the payload; the
    intermediate ones are the ladder, not the outcome.

    Idempotent by construction: it compares against the store and does nothing
    where the two already agree, which is what lets both callers run it without
    either having to know whether the other did.
    """
    if run_store is None:
        return
    for node_run in record.node_runs:
        await mirror_node_run(node_run, run_store=run_store)
    await mirror_run(record, run_store=run_store)


__all__ = ["canonical_outcome", "mirror_lifecycle", "mirror_node_run", "mirror_run"]
