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

from collections.abc import Callable
from typing import Any

from maistro.container import build_node_resolver
from maistro.graph.dag_registry import DagRegistry
from maistro.graph.definitions import Graph
from maistro.graph.durable_runs import InMemoryDurableRunStore, run_durable_graph
from maistro.graph.seeds import daily_status_seed
from maistro.graph.template_adapter import descriptor_to_template

# Module-level registry so a per-process boot registers the seeds once.
_registry: DagRegistry | None = None

# Resolved lazily rather than at import: `agent.delegate_remote` needs the
# Container's delegator and child-Run admitter (#147), and the Container does
# not exist yet at import time. Built once and cached — the resolver closes over
# the dependencies it was given, so rebuilding it per call would hand different
# nodes different wiring within one process.
_node_resolver: Callable[[str, Any], Any] | None = None


def get_node_resolver() -> Callable[[str, Any], Any]:
    """The process-wide node resolver, wired to the Container when there is one.

    Without a Container the delegation dependencies are None and
    `agent.delegate_remote` refuses loudly rather than returning a failed
    result — which is the honest answer for a process that cannot delegate.
    """
    global _node_resolver
    if _node_resolver is not None:
        return _node_resolver
    container = None
    try:
        from services.engine import get_engine

        container = getattr(getattr(get_engine(), "_agent_port", None), "container", None)
    except Exception:
        container = None
    _node_resolver = build_node_resolver(
        a2a_delegator=getattr(container, "a2a_delegator", None),
        delegation_admitter=getattr(container, "delegation_admitter", None),
    )
    return _node_resolver


# One store for the process, not one per invocation. A fresh store per call
# discarded the whole Run/NodeRun history the moment the call returned, so the
# run_id written to the audit trail named something that could not be fetched,
# resumed, or inspected — and child-run parentage vanished with it. Sharing it
# makes those records retrievable for the life of the process; a durable
# implementation behind the same protocol is what outlives a restart.
_run_store = InMemoryDurableRunStore()


def get_run_store() -> InMemoryDurableRunStore:
    """The shared durable-run store backing every registered-DAG execution."""
    return _run_store


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
    together with the durable run record.
    """
    descriptor = get_registry().get(dag_id)
    if descriptor is None:
        raise KeyError(f"No DAG registered for {dag_id!r}")
    template = descriptor_to_template(descriptor, workspace_id=workspace_id)
    graph = template.instantiate(project_id=project_id)
    if configure is not None:
        configure(graph)
    record = await run_durable_graph(
        graph,
        store=_run_store,
        node_resolver=get_node_resolver(),
        actor_principal_id=user_id,
        parent_run_id=parent_run_id,
        parent_node_run_id=parent_node_run_id,
    )
    return graph, record
