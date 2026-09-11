"""Shared DAG-as-agent registry + canonical durable execution for Hive.

One process-wide ``DagRegistry`` holds the bundled seeds. Every Hive surface
that executes a registered DAG — the Daily Report boundary, the schedule
runner — resolves the descriptor here and runs it the same way: projected
through the canonical definition layer (``descriptor_to_template`` →
``GraphTemplate.instantiate``) and executed on the durable Run/NodeRun path,
so each execution is a canonical Run carrying ``TemplateProvenance`` back to
the exact registered revision. There is deliberately no second way for a Hive
work producer to say "run this DAG".
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any

from maistro.container import build_node_resolver
from maistro.graph.dag_registry import DagRegistry
from maistro.graph.definitions import Graph
from maistro.graph.durable_runs import DurableRunStore, RunStatus, run_durable_graph
from maistro.graph.seeds import daily_status_seed
from maistro.graph.template_adapter import descriptor_to_template
from services.node_metrics_store import record_run_completion

logger = logging.getLogger(__name__)


def _run_status(record: Any) -> str:
    """The record's run status as a plain lowercase string, or "" if absent."""
    run = getattr(record, "run", None)
    status = getattr(run, "status", "")
    return str(getattr(status, "value", status) or "").lower()


#: Statuses that mean "not finished". Spelled as the complement of terminal so
#: an unrecognised one falls the safe way: a status this build does not know is
#: likelier a new terminal state than a new suspended one, and reading it as
#: suspended would silently stop recording metrics for it — the shape of defect
#: this whole change exists to remove.
_SUSPENDED_RUN_STATUSES = frozenset({"created", "queued", "running", "waiting", "paused"})


def _is_terminal(record: Any) -> bool:
    """Whether this record describes a run that has finished advancing."""
    status = _run_status(record)
    return not status or status not in _SUSPENDED_RUN_STATUSES


# Module-level registry so a per-process boot registers the seeds once.
_registry: DagRegistry | None = None


# Resolved per execution, not once at import. The old module-level
# `build_node_resolver()` was built before any Container existed, so
# AgentDelegateRemoteNode was constructed with a2a_delegator=None,
# guest_peers=None and no canonical delegation store — every delegation on
# this path refused for want of a delegator, and delegated work could not be
# filed as a child Run
# (#147).
#
# The reason it was built at import is real and only half the picture: at import
# time there is no Container to ask. By the time a DAG runs, Hive has one,
# reached the way services/engine.py already reaches run_store and
# task_admitter (ADR-082526-3ca6).
class GraphExecutionUnavailableError(RuntimeError):
    """A graph surface was called without the canonical execution spine."""

    def __init__(self, detail: str = "canonical Graph execution is unavailable") -> None:
        self.result = {
            "status": "unavailable",
            "run_id": None,
            "error": detail,
            "node_results": {},
        }
        super().__init__(detail)


def _container() -> Any:
    """The Container this process was booted with, or None when standalone."""
    try:
        from services.engine import get_engine

        engine = get_engine()
        return getattr(getattr(engine, "_agent_port", None), "container", None)
    except Exception:  # pragma: no cover - engine unavailable in isolation
        return None


def _canonical_execution_stores() -> tuple[Any, DurableRunStore]:
    """Return the Container-owned stores or fail before any Graph work starts."""
    container = _container()
    if container is None:
        raise GraphExecutionUnavailableError()
    # Keep these direct attribute reads visible to the wiring gate (#236). A
    # graph needs both halves: RunStore owns identity and the graph store owns
    # continuation state keyed by that identity.
    run_store = container.run_store
    graph_run_store = container.graph_run_store
    if run_store is None or graph_run_store is None:
        raise GraphExecutionUnavailableError(
            "canonical Graph execution requires RunStore and graph continuation storage"
        )
    return run_store, graph_run_store


def _resolve_nodes_with() -> Callable[[str, Any], Any]:
    """Build the node resolver from the canonical Container dependencies."""
    _run_store, _graph_run_store = _canonical_execution_stores()
    container = _container()
    if container is None:  # pragma: no cover - guarded by the helper
        raise GraphExecutionUnavailableError()
    return build_node_resolver(
        a2a_delegator=container.a2a_delegator,
        guest_peers=container.guest_peers,
        run_store=container.run_store,
    )


def get_run_store() -> DurableRunStore:
    """Return the Container-owned graph projection, never a private fallback."""
    _run_store, graph_run_store = _canonical_execution_stores()
    return graph_run_store


def get_registry() -> DagRegistry:
    """Lazily build the shared DagRegistry + register the bundled seeds."""
    global _registry
    if _registry is None:
        _registry = DagRegistry()
        _registry.register(daily_status_seed())
    return _registry


async def run_registered_dag(
    dag_id: str,
    *,
    workspace_id: str,
    project_id: str,
    user_id: str | None = None,
    configure: Callable[[Graph], None] | None = None,
    parent_run_id: str | None = None,
    parent_node_run_id: str | None = None,
    provenance: Mapping[str, Any] | None = None,
) -> tuple[Graph, Any]:
    """Execute a registered DAG through the canonical durable Run path.

    Raises ``KeyError`` when ``dag_id`` (either ``dag:<id>`` or bare form)
    is not registered. ``configure`` runs against the *instantiated* Graph —
    after provenance is stamped — which is where per-request runtime inputs
    such as credentials belong; the registered template stays secret-free.
    A caller that is itself executing canonical work passes its Run/NodeRun
    identity via ``parent_run_id``/``parent_node_run_id`` so the launched
    work is a child Run rather than a disconnected sibling. Returns the
    instantiated Graph (callers key node lookups on its stable node names)
    together with the durable run record. ``provenance`` lands on the Run, so
    a caller that fired this on someone's behalf -- a schedule, most of all --
    records that on the Run rather than only in an audit line beside it
    (#145).
    """
    descriptor = get_registry().get(dag_id)
    if descriptor is None:
        raise KeyError(f"No DAG registered for {dag_id!r}")
    template = descriptor_to_template(descriptor, workspace_id=workspace_id)
    graph = template.instantiate(project_id=project_id)
    if configure is not None:
        configure(graph)
    run_store, graph_run_store = _canonical_execution_stores()
    # Admission first, then execution. Traversal consumes an admitted Run
    # rather than creating one (#44): the create and the first traversal
    # checkpoint are writes to two stores, so a crash between them would leave
    # a canonical Run RUNNING with nothing to resume it. Admitting here leaves
    # a QUEUED Run instead, which #251's consumer tick can pick up.
    admitted = await run_store.create_run(
        graph,
        initial_status=RunStatus.QUEUED,
        actor_principal_id=user_id,
        parent_run_id=parent_run_id,
        parent_node_run_id=parent_node_run_id,
        provenance={**dict(provenance or {}), "executor": "durable_graph"},
    )
    record = await run_durable_graph(
        graph,
        store=graph_run_store,
        node_resolver=_resolve_nodes_with(),
        actor_principal_id=user_id,
        run_id=admitted.run_id,
        run_store=run_store,
        parent_run_id=parent_run_id,
        parent_node_run_id=parent_node_run_id,
        provenance=provenance,
    )
    # The metrics ingest's production caller. `record_run_completion` reads
    # the finished NodeRuns and the Run's own graph snapshot, and had no path
    # into it at all -- so the only observations the optimizer ever saw were
    # the ones the UI route hand-built (#698).
    #
    # Terminal runs only. `run_durable_graph` returns as soon as the graph
    # stops advancing, and a wait or HITL node stops it in `waiting` or
    # `paused` -- a run that is not over. Ingesting that record would put the
    # paused NodeRun in the aggregate's denominator, dragging the success rate
    # down, while every node after the pause is simply absent; and no resume
    # path calls back here to correct it (Codex, #698). A run that resumes to
    # completion is #53's convergence, along with the UI route.
    #
    # Named, not bare: a metrics write must not fail a run that already
    # succeeded, but "the observations for this run were not recorded" is a
    # thing an operator needs to be able to find.
    if _is_terminal(record):
        try:
            record_run_completion(record)
        except Exception:
            logger.warning(
                "node_metrics_not_recorded run_id=%s dag_id=%s",
                record.run_id,
                dag_id,
                exc_info=True,
            )
    else:
        logger.info(
            "node_metrics_deferred run_id=%s dag_id=%s status=%s",
            record.run_id,
            dag_id,
            _run_status(record),
        )
    return graph, record
