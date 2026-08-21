from __future__ import annotations

from datetime import UTC, datetime

from maistro_evolve.diversity import emergency_spawn, population_diversity, trait_vector
from maistro_evolve.types import DAGTopology, EvalWeights, NodeGenome, PipelineGenome


def _genome(name: str = "test", node_count: int = 1) -> PipelineGenome:
    nodes = [
        NodeGenome(
            id=f"n{i}",
            role="queen" if i == 0 else "worker",
            strategy="react",
            model="gpt-4",
            temperature=0.3,
            max_tokens=4096,
            system_prompt="test",
            max_tool_rounds=5,
        )
        for i in range(node_count)
    ]
    return PipelineGenome(
        id=f"g-{name}",
        name=name,
        topology=DAGTopology(
            nodes=nodes,
            edges=[],
            entry_node="n0",
            max_cycles=3,
            beam_width=1,
            use_scout=False,
        ),
        eval_weights=EvalWeights(),
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
    )


def test_trait_vector_returns_zero_vector_for_genome_with_no_nodes() -> None:
    genome = _genome()
    genome.topology.nodes = []
    assert trait_vector(genome) == [0.0] * 8


def test_trait_vector_returns_eleven_dimensions_for_nonempty_genome() -> None:
    genome = _genome(node_count=2)
    vector = trait_vector(genome)
    assert len(vector) == 11


def test_population_diversity_returns_zero_for_empty_population() -> None:
    assert population_diversity([]) == 0.0


def test_population_diversity_returns_zero_for_single_genome_population() -> None:
    assert population_diversity([_genome("solo")]) == 0.0


def test_population_diversity_returns_average_pairwise_distance() -> None:
    a = _genome("a", node_count=1)
    b = _genome("b", node_count=3)
    diversity = population_diversity([a, b])
    assert diversity > 0.0


def test_emergency_spawn_returns_requested_count_of_fresh_genomes() -> None:
    spawned = emergency_spawn([], count=3)
    assert len(spawned) == 3
    assert all(g.fitness_score is None for g in spawned)
    assert all(g.parent_a_id is None for g in spawned)
    assert len({g.id for g in spawned}) == 3
