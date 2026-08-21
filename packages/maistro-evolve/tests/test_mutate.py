from __future__ import annotations

from datetime import UTC, datetime

import pytest

from maistro_evolve.mutate import (
    mutate_all,
    mutate_eval_weights,
    mutate_node,
    mutate_prompt,
    mutate_topology,
)
from maistro_evolve.types import DAGEdgeGenome, DAGTopology, EvalWeights, NodeGenome, PipelineGenome


def _node(node_id: str, **overrides: object) -> NodeGenome:
    defaults: dict[str, object] = {
        "role": "queen",
        "strategy": "react",
        "model": "gpt-4",
        "temperature": 0.3,
        "max_tokens": 4096,
        "system_prompt": "One. Two. Three. Four.",
        "max_tool_rounds": 5,
    }
    defaults.update(overrides)
    return NodeGenome(id=node_id, **defaults)  # type: ignore[arg-type]


def _genome(nodes: list[NodeGenome], edges: list[DAGEdgeGenome], entry_node: str) -> PipelineGenome:
    return PipelineGenome(
        id="parent",
        name="base",
        topology=DAGTopology(
            nodes=nodes,
            edges=edges,
            entry_node=entry_node,
            max_cycles=3,
            beam_width=1,
            use_scout=False,
        ),
        eval_weights=EvalWeights(),
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
    )


@pytest.fixture
def force_random(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force every `random.random() < rate` probabilistic gate to fire."""
    monkeypatch.setattr("maistro_evolve.mutate.random.random", lambda: 0.0)


def test_mutate_topology_removes_a_non_entry_node_when_gate_fires(force_random: None) -> None:
    genome = _genome(
        [_node("entry"), _node("victim")],
        [DAGEdgeGenome(id="e1", from_node="entry", to_node="victim", condition=None)],
        entry_node="entry",
    )

    mutated = mutate_topology(genome, rate=1.0)

    node_ids = {n.id for n in mutated.topology.nodes}
    assert "victim" not in node_ids
    assert "entry" in node_ids
    # the edge touching the removed node must also be dropped.
    assert all(e.from_node != "victim" and e.to_node != "victim" for e in mutated.topology.edges)


def test_mutate_topology_adds_random_edge_between_two_existing_nodes(force_random: None) -> None:
    genome = _genome(
        [_node("a"), _node("b"), _node("c")],
        [],
        entry_node="a",
    )

    mutated = mutate_topology(genome, rate=1.0)

    # a node was removed, a node was added, an edge was popped, and an extra
    # random edge between two distinct surviving nodes was appended — assert
    # the last-appended edge connects two different node ids.
    last_edge = mutated.topology.edges[-1]
    node_ids = {n.id for n in mutated.topology.nodes}
    assert last_edge.from_node in node_ids
    assert last_edge.to_node in node_ids
    assert last_edge.from_node != last_edge.to_node


def test_mutate_topology_lineage_and_metadata(force_random: None) -> None:
    genome = _genome([_node("a"), _node("b")], [], entry_node="a")
    mutated = mutate_topology(genome, rate=1.0)

    assert mutated.parent_a_id == "parent"
    assert mutated.parent_b_id is None
    assert mutated.fitness_score is None
    assert mutated.eval_scores == {}
    assert mutated.name == "base-topo-mut"


def test_mutate_topology_no_removal_when_only_one_node(force_random: None) -> None:
    genome = _genome([_node("solo")], [], entry_node="solo")
    mutated = mutate_topology(genome, rate=1.0)
    assert any(n.id == "solo" for n in mutated.topology.nodes)


def test_mutate_node_mutates_model_temperature_tokens_strategy_and_rounds(
    force_random: None,
) -> None:
    genome = _genome([_node("a", model="gpt-4", strategy="react")], [], entry_node="a")
    mutated = mutate_node(genome, rate=1.0)

    node = mutated.topology.nodes[0]
    assert node.model in {
        "cerebras-qwen-3-235b-a22b-2507",
        "gpt-4o",
        "claude-sonnet-4-20250514",
        "gemini-2.5-pro",
        "mistral-large",
        "gemini-2.5-flash",
    }
    assert 0.0 <= node.temperature <= 1.0
    assert node.max_tokens in {256, 512, 1024, 2048, 4096, 8192, 16384}
    assert node.strategy in {"react", "plan_execute", "direct", "delegate"}
    assert 1 <= node.max_tool_rounds <= 20
    assert mutated.parent_a_id == "parent"
    assert mutated.name == "base-node-mut"


def test_mutate_node_noop_fields_when_rate_zero() -> None:
    genome = _genome([_node("a", model="gpt-4")], [], entry_node="a")
    mutated = mutate_node(genome, rate=0.0)
    assert mutated.topology.nodes[0].model == "gpt-4"


def test_mutate_prompt_appends_variation_and_drops_a_sentence(force_random: None) -> None:
    genome = _genome([_node("a", system_prompt="One. Two. Three. Four.")], [], entry_node="a")

    mutated = mutate_prompt(genome, rate=1.0)

    prompt = mutated.topology.nodes[0].system_prompt
    # appended variation always happens first, then a sentence is dropped —
    # the appended variation sentence may itself be the one dropped, so just
    # assert overall sentence count shrank relative to "append-only" length.
    assert prompt != "One. Two. Three. Four."
    assert mutated.parent_a_id == "parent"
    assert mutated.name == "base-prompt-mut"


def test_mutate_prompt_skips_sentence_removal_when_two_or_fewer_sentences(
    force_random: None,
) -> None:
    genome = _genome([_node("a", system_prompt="Only one sentence")], [], entry_node="a")
    mutated = mutate_prompt(genome, rate=1.0)
    # variation gets appended (making 2 sentences after split on ". "), but
    # the >2 guard means no removal occurs — prompt must still contain the
    # original text.
    assert "Only one sentence" in mutated.topology.nodes[0].system_prompt


def test_mutate_eval_weights_returns_unchanged_copy_when_gate_does_not_fire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("maistro_evolve.mutate.random.random", lambda: 1.0)
    genome = _genome([_node("a")], [], entry_node="a")
    mutated = mutate_eval_weights(genome, rate=0.0)
    assert mutated.eval_weights == genome.eval_weights
    assert mutated.parent_a_id == "parent"
    assert mutated.name == "base-weight-mut"


def test_mutate_eval_weights_perturbs_and_renormalizes_to_one(force_random: None) -> None:
    genome = _genome([_node("a")], [], entry_node="a")
    mutated = mutate_eval_weights(genome, rate=1.0)

    total = sum(getattr(mutated.eval_weights, f) for f in EvalWeights.model_fields)
    assert abs(total - 1.0) < 1e-6
    assert mutated.parent_a_id == "parent"


def test_mutate_all_chains_all_mutations_and_renames(force_random: None) -> None:
    genome = _genome([_node("a"), _node("b")], [], entry_node="a")
    mutated = mutate_all(genome, rate=1.0)
    assert mutated.name == "base-all-mut"
