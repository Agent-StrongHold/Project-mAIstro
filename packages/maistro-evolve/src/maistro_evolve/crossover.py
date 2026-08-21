from __future__ import annotations

import uuid
from copy import deepcopy
from datetime import UTC, datetime

from .mutate import mutate_all
from .types import (
    DAGEdgeGenome,
    DAGTopology,
    NodeGenome,
    PipelineGenome,
)


def _new_id() -> str:
    """Generate a 12-character hexadecimal UUID."""
    return uuid.uuid4().hex[:12]


def _fresh_timestamp() -> str:
    return datetime.now(UTC).isoformat()


def crossover(parent_a: PipelineGenome, parent_b: PipelineGenome) -> PipelineGenome:
    entry_node = None
    for n in parent_a.topology.nodes:
        if n.id == parent_a.topology.entry_node:
            entry_node = deepcopy(n)
            break
    if entry_node is None:
        entry_node = deepcopy(parent_a.topology.nodes[0])

    other_a = [deepcopy(n) for n in parent_a.topology.nodes if n.id != parent_a.topology.entry_node]
    other_b = [deepcopy(n) for n in parent_b.topology.nodes if n.id != parent_b.topology.entry_node]

    child_nodes: list[NodeGenome] = [entry_node]
    node_id_map: dict[str, str] = {entry_node.id: entry_node.id}
    # parent_b's entry node isn't carried into the child as a distinct node
    # (the child keeps parent_a's entry), so edges originating there must be
    # rewired onto the child's single entry node instead of being dropped.
    node_id_map[parent_b.topology.entry_node] = entry_node.id

    for nodes in (other_a, other_b):
        for n in nodes:
            new_id = _new_id()
            node_id_map[n.id] = new_id
            n.id = new_id
            child_nodes.append(n)

    child_edges: list[DAGEdgeGenome] = []
    for edge in parent_a.topology.edges + parent_b.topology.edges:
        from_mapped = node_id_map.get(edge.from_node)
        to_mapped = node_id_map.get(edge.to_node) if edge.to_node else None
        if from_mapped is None:
            continue
        child_edges.append(
            DAGEdgeGenome(
                id=_new_id(),
                from_node=from_mapped,
                to_node=to_mapped,
                condition=edge.condition,
            )
        )

    child_weights = {}
    for field_name in parent_a.eval_weights.model_fields:
        va = getattr(parent_a.eval_weights, field_name)
        vb = getattr(parent_b.eval_weights, field_name)
        child_weights[field_name] = round((va + vb) / 2.0, 4)

    child_topo = DAGTopology(
        nodes=child_nodes,
        edges=child_edges,
        entry_node=entry_node.id,
        max_cycles=max(parent_a.topology.max_cycles, parent_b.topology.max_cycles),
        beam_width=max(parent_a.topology.beam_width, parent_b.topology.beam_width),
        use_scout=parent_a.topology.use_scout or parent_b.topology.use_scout,
    )

    return PipelineGenome(
        id=_new_id(),
        name=f"cross-{parent_a.id[:6]}-{parent_b.id[:6]}",
        topology=child_topo,
        eval_weights=parent_a.eval_weights.__class__(**child_weights),
        harness_params=deepcopy(parent_a.harness_params),
        fitness_score=None,
        eval_scores={},
        generation=max(parent_a.generation, parent_b.generation) + 1,
        parent_a_id=parent_a.id,
        parent_b_id=parent_b.id,
        created_at=_fresh_timestamp(),
        updated_at=_fresh_timestamp(),
    )


def crossover_and_mutate(
    parent_a: PipelineGenome,
    parent_b: PipelineGenome,
    mutation_rate: float = 0.3,
    models: list[str] | None = None,
) -> PipelineGenome:
    """``models`` constrains the child's model mutation to the run's routable
    roster (see ``mutate_all``) — without it, breeding can drift a lineage onto
    models the gateway can't serve."""
    child = crossover(parent_a, parent_b)
    return mutate_all(child, mutation_rate, models)
