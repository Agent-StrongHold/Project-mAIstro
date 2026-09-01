"""Bounded production wakeup for persisted durable Graph continuations (#837).

This module does not own a queue, timer, Run lifecycle, or execution policy. It
is one operator-schedulable tick over the canonical durable-Graph store, in the
same style as the Container's other recovery ticks. Candidate discovery comes
from the indexed continuation projection; physical work still crosses the
canonical Attempt/lease/fence boundary in :mod:`attempt_executor`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from maistro.runs.model import RunStatus
from maistro.runs.store import RunStore
from maistro.runtime import ExecutionRuntime

from .attempt_executor import NodeResolver, resume_durable_graph
from .protocol import DurableRunStore


async def resume_due_graph_runs(
    *,
    store: DurableRunStore,
    run_store: RunStore,
    node_resolver: NodeResolver,
    runtime: ExecutionRuntime | None = None,
    now: datetime | None = None,
    limit: int = 100,
) -> int:
    """Resume at most ``limit`` elapsed durable Graph waits.

    ``list_due`` may also surface overdue ``PAUSED`` records because the same
    persisted deadline is useful to HITL timeout/cancel reconciliation. A clock
    must never manufacture a human answer, so this executor only consumes
    ``WAITING`` records. ``resume_durable_graph`` then reconciles orphaned
    Attempts and refuses work protected by a live execution lease before any
    redispatch.

    Across replicas, the resume seam's first write is the continuation's
    optimistic ``version + 1`` checkpoint. If another worker wins between this
    indexed read and that checkpoint, re-read canonical state: an ineligible
    record means the other worker legitimately moved it, while a still-eligible
    record means the error was real and must remain visible.
    """
    if limit <= 0:
        return 0

    moment = now if now is not None else datetime.now(UTC)
    candidates = await store.list_due(now=moment, limit=limit)
    resumed = 0

    for candidate in candidates:
        if candidate.run.status is not RunStatus.WAITING:
            continue
        if candidate.resume_at is None or candidate.resume_at > moment:
            continue
        try:
            await resume_durable_graph(
                candidate.run_id,
                store=store,
                node_resolver=node_resolver,
                runtime=runtime,
                run_store=run_store,
            )
        except (KeyError, ValueError):
            current = await store.get(candidate.run_id)
            if current is None:
                continue
            if (
                current.run.status is not RunStatus.WAITING
                or current.resume_at is None
                or current.resume_at > moment
            ):
                continue
            raise
        resumed += 1

    return resumed


__all__ = ["resume_due_graph_runs"]
