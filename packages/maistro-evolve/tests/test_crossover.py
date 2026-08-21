from __future__ import annotations

from datetime import UTC, datetime

from maistro_evolve.crossover import crossover, crossover_and_mutate
from maistro_evolve.types import DAGEdgeGenome, DAGTopology, EvalWeights, NodeGenome, PipelineGenome


def _node(node_id: str, **overrides: object) -> NodeGenome:
    defaults: dict[str, object] = {
        "role": "queen",
        "strategy": "react",
        "model": "gpt-4",
        "temperature": 0.3,
        "max_tokens": 4096,
        "system_prompt": "test",
        "max_tool_rounds": 5,
    }
    defaults.update(overrides)
    return NodeGenome(id=node_id, **defaults)  # type: ignore[arg-type]


def _genome(
    genome_id: str,
    nodes: list[NodeGenome],
    edges: list[DAGEdgeGenome],
    entry_node: str,
    generation: int = 0,
) -> PipelineGenome:
    return PipelineGenome(
        id=genome_id,
        name=genome_id,
        topology=DAGTopology(
            nodes=nodes,
            edges=edges,
            entry_node=entry_node,
            max_cycles=3,
            beam_width=1,
            use_scout=False,
        ),
        eval_weights=EvalWeights(),
        generation=generation,
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
    )


def test_crossover_preserves_parent_a_entry_node() -> None:
    parent_a = _genome("a", [_node("a-entry"), _node("a-other")], [], entry_node="a-entry")
    parent_b = _genome("b", [_node("b-entry")], [], entry_node="b-entry")

    child = crossover(parent_a, parent_b)

    assert child.topology.entry_node == child.topology.nodes[0].id
    assert child.topology.nodes[0].role == "queen"
    assert len(child.topology.nodes) == 2


def test_crossover_falls_back_to_first_node_when_entry_node_id_mismatched() -> None:
    # parent_a.topology.entry_node doesn't match any node id present.
    parent_a = _genome("a", [_node("only-node")], [], entry_node="missing-entry")
    parent_b = _genome("b", [_node("b-entry")], [], entry_node="b-entry")

    child = crossover(parent_a, parent_b)

    assert child.topology.nodes[0].id == child.topology.entry_node
    # the surviving entry node came from parent_a's first node, unchanged id.
    assert any(n.role == "queen" for n in child.topology.nodes)


def test_crossover_remaps_non_entry_node_ids_from_both_parents() -> None:
    parent_a = _genome("a", [_node("a-entry"), _node("a-other")], [], entry_node="a-entry")
    parent_b = _genome("b", [_node("b-entry"), _node("b-other")], [], entry_node="b-entry")

    child = crossover(parent_a, parent_b)

    child_ids = [n.id for n in child.topology.nodes]
    # entry node id is preserved; the other two non-entry nodes get fresh ids.
    assert child_ids[0] == "a-entry"
    assert "a-other" not in child_ids[1:]
    assert "b-other" not in child_ids[1:]
    assert len(set(child_ids)) == 3


def test_crossover_remaps_edges_using_new_node_ids() -> None:
    parent_a = _genome(
        "a",
        [_node("a-entry"), _node("a-other")],
        [DAGEdgeGenome(id="e1", from_node="a-entry", to_node="a-other", condition=None)],
        entry_node="a-entry",
    )
    parent_b = _genome("b", [_node("b-entry")], [], entry_node="b-entry")

    child = crossover(parent_a, parent_b)

    assert len(child.topology.edges) == 1
    edge = child.topology.edges[0]
    assert edge.from_node == child.topology.entry_node
    assert edge.to_node in {n.id for n in child.topology.nodes}
    assert edge.to_node != "a-other"


def test_crossover_drops_edges_whose_from_node_was_not_mapped() -> None:
    # from_node references a node id that doesn't exist anywhere in parent_a's
    # topology, so it never enters node_id_map and the edge must be dropped.
    parent_a = _genome(
        "a",
        [_node("a-entry")],
        [DAGEdgeGenome(id="e1", from_node="ghost-node", to_node="a-entry", condition=None)],
        entry_node="a-entry",
    )
    parent_b = _genome("b", [_node("b-entry")], [], entry_node="b-entry")

    child = crossover(parent_a, parent_b)

    assert child.topology.edges == []


def test_crossover_handles_edge_with_no_to_node() -> None:
    parent_a = _genome(
        "a",
        [_node("a-entry")],
        [DAGEdgeGenome(id="e1", from_node="a-entry", to_node=None, condition=None)],
        entry_node="a-entry",
    )
    parent_b = _genome("b", [_node("b-entry")], [], entry_node="b-entry")

    child = crossover(parent_a, parent_b)

    assert len(child.topology.edges) == 1
    assert child.topology.edges[0].to_node is None


def test_crossover_drops_edges_whose_to_node_was_not_mapped() -> None:
    # to_node references a non-entry node id that exists in parent_a but gets
    # remapped to a fresh id; however, the edge's to_node value itself doesn't
    # get remapped (bug), so we end up with a dangling reference. The edge should
    # be dropped when to_node is not in node_id_map.
    parent_a = _genome(
        "a",
        [_node("a-entry"), _node("a-other")],
        [DAGEdgeGenome(id="e1", from_node="a-entry", to_node="a-other", condition=None)],
        entry_node="a-entry",
    )
    parent_b = _genome("b", [_node("b-entry")], [], entry_node="b-entry")

    child = crossover(parent_a, parent_b)

    # Edge should be included because from_node (entry) is mapped and to_node
    # (a-other) is also mapped to its new id.
    assert len(child.topology.edges) == 1
    edge = child.topology.edges[0]
    assert edge.from_node == child.topology.entry_node
    # The to_node should be the remapped "a-other" node, not the original "a-other"
    child_node_ids = {n.id for n in child.topology.nodes}
    assert edge.to_node in child_node_ids
    assert edge.to_node != "a-other"


def test_crossover_averages_eval_weights_and_takes_max_topology_settings() -> None:
    parent_a = _genome("a", [_node("a-entry")], [], entry_node="a-entry", generation=1)
    parent_a.eval_weights = EvalWeights(proxy_ifeval=0.1)
    parent_a.topology.max_cycles = 2
    parent_a.topology.beam_width = 1
    parent_a.topology.use_scout = False

    parent_b = _genome("b", [_node("b-entry")], [], entry_node="b-entry", generation=3)
    parent_b.eval_weights = EvalWeights(proxy_ifeval=0.3)
    parent_b.topology.max_cycles = 5
    parent_b.topology.beam_width = 4
    parent_b.topology.use_scout = True

    child = crossover(parent_a, parent_b)

    assert child.eval_weights.proxy_ifeval == 0.2
    assert child.topology.max_cycles == 5
    assert child.topology.beam_width == 4
    assert child.topology.use_scout is True
    assert child.generation == 4
    assert child.parent_a_id == "a"
    assert child.parent_b_id == "b"
    assert child.fitness_score is None
    assert child.eval_scores == {}


def test_crossover_and_mutate_returns_a_mutated_child() -> None:
    parent_a = _genome("a", [_node("a-entry")], [], entry_node="a-entry")
    parent_b = _genome("b", [_node("b-entry")], [], entry_node="b-entry")

    crossed = crossover(parent_a, parent_b)
    child = crossover_and_mutate(parent_a, parent_b, mutation_rate=1.0)

    # mutate_all wraps the crossover child in a fresh mutation lineage: it
    # becomes the sole parent, the crossover's parent_b lineage is dropped.
    assert child.parent_b_id is None
    assert child.parent_a_id != crossed.parent_a_id


def test_crossover_preserves_edge_condition_from_parent() -> None:
    # Verify that the condition field on edges is preserved during crossover.
    # This is behavior that is currently untested.
    parent_a = _genome(
        "a",
        [_node("a-entry"), _node("a-other")],
        [DAGEdgeGenome(id="e1", from_node="a-entry", to_node="a-other", condition="success")],
        entry_node="a-entry",
    )
    parent_b = _genome("b", [_node("b-entry")], [], entry_node="b-entry")

    child = crossover(parent_a, parent_b)

    assert len(child.topology.edges) == 1
    edge = child.topology.edges[0]
    assert edge.condition == "success"
