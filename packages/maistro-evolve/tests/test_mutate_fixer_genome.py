"""Typed mutation over FixerGenome slots — the baseline (random) operator that
mutate_all wires in; the hyper-mutator (W6) is the guided alternative."""

from __future__ import annotations

from maistro_evolve.diversity import _random_genome
from maistro_evolve.mutate import mutate_all, mutate_fixer_genome


def test_mutate_fixer_genome_stays_in_bounds() -> None:
    g = _random_genome()
    for _ in range(10):
        g = mutate_fixer_genome(g, rate=0.9)  # high rate to exercise every slot
        for n in g.topology.nodes:
            assert n.fixer is not None
            assert 0.0 <= n.fixer.minimalism <= 1.0
            assert 0.0 <= n.fixer.ambition <= 1.0
            assert 0.0 <= n.fixer.edge_focus <= 1.0
            assert 0.0 <= n.fixer.tdd_rigor <= 1.0
            if n.fixer.temperature is not None:
                assert 0.0 <= n.fixer.temperature <= 2.0


def test_mutate_fixer_genome_at_zero_rate_is_a_noop_on_slots() -> None:
    g = _random_genome()
    before = [n.fixer.model_dump() for n in g.topology.nodes]
    mutated = mutate_fixer_genome(g, rate=0.0)
    after = [n.fixer.model_dump() for n in mutated.topology.nodes]
    assert before == after


def test_mutate_fixer_genome_skips_nodes_without_a_fixer() -> None:
    g = _random_genome()
    for n in g.topology.nodes:
        n.fixer = None
    mutated = mutate_fixer_genome(g, rate=1.0)
    assert all(n.fixer is None for n in mutated.topology.nodes)


def test_mutate_fixer_genome_spawns_a_child_with_lineage() -> None:
    g = _random_genome()
    child = mutate_fixer_genome(g, rate=0.5)
    assert child.id != g.id
    assert child.parent_a_id == g.id
    assert child.generation == g.generation


def test_mutate_all_includes_fixer_mutation() -> None:
    # mutate_all composes every operator, including mutate_fixer_genome — a smoke
    # check that it runs end-to-end without error. Only the entry node's fixer is
    # a stable invariant: mutate_topology can add nodes with no fixer (fine — it's
    # only meaningful on a fixer role) or remove non-entry nodes, but the entry is
    # never removed and mutate_fixer_genome never nulls an existing fixer.
    g = _random_genome()
    child = mutate_all(g, rate=0.5)
    entry = next(n for n in child.topology.nodes if n.id == child.topology.entry_node)
    assert entry.fixer is not None
