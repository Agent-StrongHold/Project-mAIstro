"""Recovery and timed wakeup for schedule-admitted registered-DAG Runs (#837).

``run_registered_dag`` admits a canonical Run QUEUED with
``executor=durable_graph`` and, when a schedule fires it, stamps
``admission_source=schedule``. The schedule consumer executes only
single-node QUEUED Runs and leaves multi-node ones to the durable Graph
traversal; its resume tick matches only YIELDED Attempts, never Graph pauses.
These two halves are that traversal's recovery owner: they hand the Runs to
the canonical recovery seams, which remain the sole authority (continuation
version, Attempt lease and fence) for whether physical work may start.
"""

from __future__ import annotations

from maistro.graph.durable_runs import (
    NodeResolver,
    recover_queued_graph_runs,
    resume_due_graph_runs,
)
from maistro.runs.model import Run
from services.dag_agents import _container, _resolve_nodes_with
from services.scan_continuations import scan_continuation

_SOURCES = frozenset({"schedule"})
_EXECUTOR = "durable_graph"


def _owned(run: Run) -> bool:
    return (
        run.provenance.get("admission_source") in _SOURCES
        and run.provenance.get("executor") == _EXECUTOR
    )


def _owned_traversal(run: Run) -> bool:
    # A single-node QUEUED schedule Run is the consumer's
    # (`executable_by_consumer`); claiming it here would race that tick.
    return _owned(run) and len(run.graph.materialize().nodes) > 1


def _resolver(run: Run) -> NodeResolver:
    # The resolver the admitting path used: which node kinds may execute is the
    # Run's graph snapshot, and their authorities are the Container's.
    del run
    return _resolve_nodes_with()


async def recover_stranded_registered_dag_runs(*, limit: int = 100) -> int:
    """Resume QUEUED multi-node schedule Runs no traversal is carrying."""
    container = _container()
    if container is None or container.graph_run_store is None:
        return 0
    return await recover_queued_graph_runs(
        store=container.graph_run_store,
        run_store=container.run_store,
        node_resolver_factory=_resolver,
        eligible=_owned_traversal,
        admission_source="schedule",
        events=container.event_bus,
        limit=limit,
        scan=scan_continuation("recover_queued_registered_dag_runs", container.run_store),
    )


async def wake_due_registered_dag_runs(*, limit: int = 100) -> int:
    """Resume schedule Runs whose persisted ``resume_at`` has elapsed."""
    container = _container()
    if container is None or container.graph_run_store is None:
        return 0
    return await resume_due_graph_runs(
        store=container.graph_run_store,
        run_store=container.run_store,
        node_resolver_factory=_resolver,
        eligible=_owned,
        events=container.event_bus,
        limit=limit,
        scan=scan_continuation("resume_due_registered_dag_runs", container.graph_run_store),
    )


__all__ = ["recover_stranded_registered_dag_runs", "wake_due_registered_dag_runs"]
