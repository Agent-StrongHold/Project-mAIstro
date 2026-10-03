from __future__ import annotations

import uuid
from collections.abc import Sequence
from copy import deepcopy
from datetime import UTC, datetime

from .attribution import CandidateOrigin, EvalContext, ProducerKind, producer_identity, stamp_origin
from .mutate import MUTATION_OPERATOR_NAMES, mutate_all, mutate_selected
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


def _crossover_baseline(parent_a: PipelineGenome, parent_b: PipelineGenome) -> dict[str, float]:
    """Per-benchmark credit baseline for a crossover child: the better parent's
    stored score. A child must beat the best parent to earn its producer
    positive credit — the honest measure of whether crossover adds value."""
    baseline: dict[str, float] = {}
    for bench, score_a in parent_a.eval_scores.items():
        score_b = parent_b.eval_scores.get(bench)
        baseline[bench] = score_a if score_b is None else max(score_a, score_b)
    for bench, score_b in parent_b.eval_scores.items():
        if bench not in baseline:
            baseline[bench] = score_b
    return baseline


def crossover(
    parent_a: PipelineGenome,
    parent_b: PipelineGenome,
    *,
    origin_context: EvalContext | None = None,
    _stamp: bool = True,
) -> PipelineGenome:
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

    # eval_weights is an inert legacy field since #853 (scoring reads the
    # population-owned objective). Inherit parent_a's verbatim — it is
    # deliberately NOT averaged/mixed with parent_b's: the field cannot affect
    # any score, and mixing it would falsely advertise it as meaningful.
    child_topo = DAGTopology(
        nodes=child_nodes,
        edges=child_edges,
        entry_node=entry_node.id,
        max_cycles=max(parent_a.topology.max_cycles, parent_b.topology.max_cycles),
        beam_width=max(parent_a.topology.beam_width, parent_b.topology.beam_width),
        use_scout=parent_a.topology.use_scout or parent_b.topology.use_scout,
    )

    child = PipelineGenome(
        id=_new_id(),
        name=f"cross-{parent_a.id[:6]}-{parent_b.id[:6]}",
        topology=child_topo,
        eval_weights=deepcopy(parent_a.eval_weights),
        harness_params=deepcopy(parent_a.harness_params),
        fitness_score=None,
        eval_scores={},
        generation=max(parent_a.generation, parent_b.generation) + 1,
        parent_a_id=parent_a.id,
        parent_b_id=parent_b.id,
        created_at=_fresh_timestamp(),
        updated_at=_fresh_timestamp(),
    )
    if not _stamp:
        return child
    producer = producer_identity("crossover", ProducerKind.GENERATOR)
    return stamp_origin(
        child,
        CandidateOrigin(
            producer=producer,
            parents=(parent_a.id, parent_b.id),
            chain=(producer.key(),),
            baseline_scores=_crossover_baseline(parent_a, parent_b),
            context=origin_context or EvalContext(),
        ),
    )


def crossover_and_mutate(
    parent_a: PipelineGenome,
    parent_b: PipelineGenome,
    mutation_rate: float = 0.3,
    models: list[str] | None = None,
    *,
    operators: Sequence[str] | None = None,
    origin_context: EvalContext | None = None,
) -> PipelineGenome:
    """``models`` constrains the child's model mutation to the run's routable
    roster (see ``mutate_all``) — without it, breeding can drift a lineage onto
    models the gateway can't serve.

    M4-A8 producer attribution: the produced child carries a CandidateOrigin
    whose direct producer is the mutation composite that last shaped it
    (``mutate_all``/``mutate_selected``), with ``upstream`` recording the two
    crossover parents (the intermediate crossover child itself is transient,
    so the parent_a_id chain alone would dead-end at an unstorred id) and
    ``chain`` preserving the full crossover→mutation pipeline for audit.
    ``operators=None`` applies every mutation operator (legacy behavior);
    a ledger-driven subset is how the cycle favors productive operators.
    """
    cross_child = crossover(parent_a, parent_b, origin_context=origin_context, _stamp=False)
    cross_baseline = _crossover_baseline(parent_a, parent_b)
    if operators is None:
        final = mutate_all(
            cross_child, mutation_rate, models, origin_context=origin_context, _stamp=False
        )
        applied: list[str] = list(MUTATION_OPERATOR_NAMES)
        composite = "mutate_all"
    else:
        final = mutate_selected(
            cross_child,
            mutation_rate,
            models,
            operators=operators,
            origin_context=origin_context,
            _stamp=False,
        )
        applied = list(operators)
        composite = "mutate_selected"
    producer = producer_identity(composite, ProducerKind.MUTATION_OPERATOR)
    return stamp_origin(
        final,
        CandidateOrigin(
            producer=producer,
            parents=(cross_child.id,),
            upstream=(parent_a.id, parent_b.id),
            chain=(producer_identity("crossover", ProducerKind.GENERATOR).key(), producer.key()),
            baseline_scores=cross_baseline,
            context=origin_context or EvalContext(),
            note="crossover then " + composite + " (" + ", ".join(applied) + ")",
        ),
    )
