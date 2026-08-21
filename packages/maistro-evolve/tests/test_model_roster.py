"""Model-roster constraint: with `models` given, no operator can assign a model
outside the run's routable set — an unroutable model is a guaranteed-0 eval whose
dead gene spreads through breeding (observed live via a drifted gemini alias)."""

from __future__ import annotations

from maistro_evolve.crossover import crossover_and_mutate
from maistro_evolve.diversity import _random_genome, emergency_spawn
from maistro_evolve.mutate import mutate_all, mutate_node, mutate_topology

ROSTER = ["code", "devstral-medium"]


def _all_models(genome) -> set[str]:
    return {n.model for n in genome.topology.nodes}


def test_random_genome_pins_every_node_to_the_roster() -> None:
    for _ in range(10):
        assert _all_models(_random_genome(ROSTER)) <= set(ROSTER)


def test_mutation_never_leaves_the_roster() -> None:
    g = _random_genome(ROSTER)
    for _ in range(10):
        g = mutate_node(g, rate=1.0, models=ROSTER)
        g = mutate_topology(g, rate=1.0, models=ROSTER)  # new nodes too
        assert _all_models(g) <= set(ROSTER)


def test_breeding_keeps_children_on_the_roster() -> None:
    a, b = _random_genome(ROSTER), _random_genome(ROSTER)
    for _ in range(10):
        child = crossover_and_mutate(a, b, mutation_rate=1.0, models=ROSTER)
        assert _all_models(child) <= set(ROSTER)


def test_emergency_spawn_respects_the_roster() -> None:
    for g in emergency_spawn([], 5, models=ROSTER):
        assert _all_models(g) <= set(ROSTER)


def test_default_pool_still_works_without_a_roster() -> None:
    g = mutate_all(_random_genome(), rate=0.5)  # no models → generic registry
    assert len(g.topology.nodes) >= 1
