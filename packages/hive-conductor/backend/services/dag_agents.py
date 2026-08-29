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

from collections.abc import Callable, Mapping
from typing import Any

from maistro.container import build_node_resolver
from maistro.graph.dag_registry import DagRegistry
from maistro.graph.definitions import Graph
from maistro.graph.durable_runs import (
    DurableRunStore,
    InMemoryDurableRunStore,
    RunStatus,
    run_durable_graph,
)
from maistro.graph.seeds import daily_status_seed
from maistro.graph.template_adapter import descriptor_to_template

# Module-level registry so a per-process boot registers the seeds once.
_registry: DagRegistry | None = None

# Resolved per execution, not once at import. The old module-level
# `build_node_resolver()` was built before any Container existed, so
# AgentDelegateRemoteNode was constructed with a2a_delegator=None,
# guest_peers=None and run_store=None — every delegation on this path refused
# for want of a delegator, and delegated work could not be filed as a child Run
# (#147).
#
# The reason it was built at import is real and only half the picture: at import
# time there is no Container to ask. By the time a DAG runs, Hive has one,
# reached the way services/engine.py already reaches run_store and
# task_admitter (ADR-082526-3ca6).
_fallback_node_resolver = build_node_resolver()


def _container() -> Any:
    """The Container this process was booted with, or None when standalone."""
    try:
        from services.engine import get_engine

        engine = get_engine()
        return getattr(getattr(engine, "_agent_port", None), "container", None)
    except Exception:  # pragma: no cover - engine unavailable in isolation
        return None


def _resolve_nodes_with() -> Callable[[str, Any], Any]:
    """The node resolver for this execution, wired from the Container if there is one.

    Without the bridge there is no Container, and the no-arg resolver is
    returned unchanged — a Conductor running standalone behaves exactly as it
    did rather than failing to start.

    `run_store` is deliberately the container's **canonical** RunStore. This
    module also holds an `InMemoryDurableRunStore`, whose name is one word away
    and whose methods share nothing; build_node_resolver's own docstring records
    that passing the wrong one type-checks and then raises AttributeError after
    the delegation has already been dispatched.
    """
    container = _container()
    if container is None:
        return _fallback_node_resolver
    # Read as attributes rather than through getattr(): the Container dataclass
    # always defines all three, and check-wiring-reads.py (#236) walks attribute
    # loads, so a getattr("name") read is invisible to it and the fields would
    # report as wired-but-unread. Naming them here is what makes the gate able
    # to hold this wiring in place.
    return build_node_resolver(
        a2a_delegator=container.a2a_delegator,
        guest_peers=container.guest_peers,
        run_store=container.run_store,
    )


# The last-resort store, for a Conductor booted without a Container. It is
# process-local and that is the defect, not the design: a restart empties the
# HITL queue and two workers disagree about what is paused. It survives only
# because a standalone Conductor has no canonical spine to project onto, and
# it is reached only when `_container()` returns nothing.
_fallback_run_store = InMemoryDurableRunStore()


def get_run_store() -> DurableRunStore:
    """The durable store backing registered-DAG execution.

    The Container's `graph_run_store` when there is one -- a `DurableRunStore`
    in interface only, whose Run, NodeRuns and Attempts are rows on the
    canonical spine (#44). That is what makes a DAG this process ran findable
    through `GET /v1/runs/{id}`, sweepable by retention, and resumable by
    another replica; the module-level in-memory store this replaces could do
    none of those, and its records did not outlive the process that made them.
    """
    container = _container()
    if container is None:
        return _fallback_run_store
    # An attribute load, not getattr(): check-wiring-reads.py (#236) walks
    # attribute loads, so a getattr("graph_run_store") read is invisible to it
    # and the Container field would report as wired-but-unread. Naming it here
    # is what holds this wiring in place.
    store = container.graph_run_store
    if store is None:
        return _fallback_run_store
    return store  # type: ignore[no-any-return]


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
    container = _container()
    run_store = container.run_store if container is not None else None
    # Admission first, then execution. Traversal consumes an admitted Run
    # rather than creating one (#44): the create and the first traversal
    # checkpoint are writes to two stores, so a crash between them would leave
    # a canonical Run RUNNING with nothing to resume it. Admitting here leaves
    # a QUEUED Run instead, which #251's consumer tick can pick up. Without a
    # Container there is no spine, and execution takes the pre-convergence
    # path rather than failing to start.
    admitted_run_id = None
    if run_store is not None:
        admitted = await run_store.create_run(
            graph,
            initial_status=RunStatus.QUEUED,
            actor_principal_id=user_id,
            parent_run_id=parent_run_id,
            parent_node_run_id=parent_node_run_id,
            provenance={**dict(provenance or {}), "executor": "durable_graph"},
        )
        admitted_run_id = admitted.run_id
    record = await run_durable_graph(
        graph,
        store=get_run_store(),
        node_resolver=_resolve_nodes_with(),
        actor_principal_id=user_id,
        run_id=admitted_run_id,
        run_store=run_store,
        parent_run_id=parent_run_id,
        parent_node_run_id=parent_node_run_id,
        provenance=provenance,
    )
    return graph, record
