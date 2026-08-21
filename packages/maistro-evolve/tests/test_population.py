from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from maistro_evolve.cycle import EvolutionConfig, EvolutionCycle
from maistro_evolve.harness import EvalHarness
from maistro_evolve.population import IslandPopulation, PopulationStore, migrate_islands
from maistro_evolve.tournament import EloTournament
from maistro_evolve.types import DAGTopology, EvalWeights, NodeGenome, PipelineGenome


def _genome(
    genome_id: str,
    fitness_score: float | None = None,
    parent_a_id: str | None = None,
) -> PipelineGenome:
    return PipelineGenome(
        id=genome_id,
        name=genome_id,
        topology=DAGTopology(
            nodes=[
                NodeGenome(
                    id="q1",
                    role="queen",
                    strategy="react",
                    model="gpt-4",
                    temperature=0.3,
                    max_tokens=4096,
                    system_prompt="test",
                    max_tool_rounds=5,
                )
            ],
            edges=[],
            entry_node="q1",
            max_cycles=3,
            beam_width=1,
            use_scout=False,
        ),
        eval_weights=EvalWeights(),
        fitness_score=fitness_score,
        parent_a_id=parent_a_id,
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
    )


@pytest.fixture(params=["memory", "sqlite"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> PopulationStore:
    if request.param == "memory":
        return PopulationStore()
    return PopulationStore(tmp_path / "pop.db")


def test_add_and_get_roundtrip(store: PopulationStore) -> None:
    genome = _genome("g1", fitness_score=0.5)
    store.add(genome)
    assert store.get("g1") == genome


def test_get_missing_returns_none(store: PopulationStore) -> None:
    assert store.get("missing") is None


def test_list_all_returns_every_added_genome(store: PopulationStore) -> None:
    store.add(_genome("g1"))
    store.add(_genome("g2"))
    ids = {g.id for g in store.list_all()}
    assert ids == {"g1", "g2"}


def test_remove_deletes_genome(store: PopulationStore) -> None:
    store.add(_genome("g1"))
    store.remove("g1")
    assert store.get("g1") is None
    assert store.list_all() == []


def test_get_champion_returns_none_when_no_scored_genomes(store: PopulationStore) -> None:
    store.add(_genome("g1", fitness_score=None))
    assert store.get_champion() is None


def test_get_champion_returns_highest_scoring_genome(store: PopulationStore) -> None:
    store.add(_genome("low", fitness_score=0.2))
    store.add(_genome("high", fitness_score=0.9))
    store.add(_genome("unscored", fitness_score=None))
    champion = store.get_champion()
    assert champion is not None
    assert champion.id == "high"


def test_get_lineage_walks_parent_a_chain(store: PopulationStore) -> None:
    store.add(_genome("grandparent"))
    store.add(_genome("parent", parent_a_id="grandparent"))
    store.add(_genome("child", parent_a_id="parent"))

    lineage = store.get_lineage("child")

    assert [g.id for g in lineage] == ["child", "parent", "grandparent"]


def test_get_lineage_stops_when_parent_id_missing_from_store(store: PopulationStore) -> None:
    store.add(_genome("orphan", parent_a_id="never-added"))
    lineage = store.get_lineage("orphan")
    assert [g.id for g in lineage] == ["orphan"]


def test_get_lineage_for_unknown_genome_returns_empty(store: PopulationStore) -> None:
    assert store.get_lineage("nope") == []


def test_cull_bottom_returns_zero_when_no_scored_genomes(store: PopulationStore) -> None:
    store.add(_genome("g1", fitness_score=None))
    assert store.cull_bottom(0.5) == 0
    assert store.get("g1") is not None


def test_cull_bottom_removes_lowest_scoring_fraction(store: PopulationStore) -> None:
    for i, score in enumerate([0.1, 0.2, 0.3, 0.4, 0.9]):
        store.add(_genome(f"g{i}", fitness_score=score))

    removed = store.cull_bottom(0.4)

    assert removed == 2
    remaining_ids = {g.id for g in store.list_all()}
    assert "g0" not in remaining_ids
    assert "g1" not in remaining_ids
    assert "g4" in remaining_ids


def test_cull_bottom_always_removes_at_least_one(store: PopulationStore) -> None:
    store.add(_genome("only", fitness_score=0.5))
    removed = store.cull_bottom(0.01)
    assert removed == 1
    assert store.list_all() == []


def test_get_breeding_pool_returns_top_n_scored_descending(store: PopulationStore) -> None:
    store.add(_genome("low", fitness_score=0.1))
    store.add(_genome("mid", fitness_score=0.5))
    store.add(_genome("high", fitness_score=0.9))
    store.add(_genome("unscored", fitness_score=None))

    pool = store.get_breeding_pool(top_n=2)

    assert [g.id for g in pool] == ["high", "mid"]


def test_get_breeding_pool_empty_when_no_scored_genomes(store: PopulationStore) -> None:
    store.add(_genome("g1", fitness_score=None))
    assert store.get_breeding_pool(top_n=5) == []


def test_sqlite_store_persists_across_instances(tmp_path: Path) -> None:
    db_path = tmp_path / "pop.db"
    store1 = PopulationStore(db_path)
    store1.add(_genome("g1", fitness_score=0.7))

    store2 = PopulationStore(db_path)
    assert store2.get("g1") is not None
    assert store2.get("g1").fitness_score == 0.7  # type: ignore[union-attr]


def test_sqlite_store_get_caches_in_memory_after_first_load(tmp_path: Path) -> None:
    db_path = tmp_path / "pop.db"
    store1 = PopulationStore(db_path)
    store1.add(_genome("g1"))

    store2 = PopulationStore(db_path)
    first = store2.get("g1")
    assert first is not None
    # second get hits the in-memory cache populated by the first lookup.
    assert store2.get("g1") is first


# ---------------------------------------------------------------------------
# Island model tests (SPEC-070226-5ce3)
# ---------------------------------------------------------------------------


class TestIslandAssignment:
    def test_island_assignment_round_robin_for_seeds(self) -> None:
        """Genomes without parents are assigned round-robin across islands."""
        ip = IslandPopulation(island_count=3)
        g0 = _genome("g0")
        g1 = _genome("g1")
        g2 = _genome("g2")
        g3 = _genome("g3")
        islands = [ip.assign(g) for g in [g0, g1, g2, g3]]
        assert islands == [0, 1, 2, 0]

    def test_child_inherits_parent_island(self) -> None:
        """A child genome is assigned to the same island as its parent_a."""
        ip = IslandPopulation(island_count=3)
        parent = _genome("p0")
        ip.assign(parent)  # round-robin → island 0
        child = _genome("c0", parent_a_id="p0")
        assert ip.assign(child) == 0

    def test_assign_is_idempotent(self) -> None:
        """Calling assign twice on the same genome returns the same island."""
        ip = IslandPopulation(island_count=2)
        g = _genome("g0")
        first = ip.assign(g)
        second = ip.assign(g)
        assert first == second
        assert ip.get_members(first).count("g0") == 1

    def test_remove_clears_membership(self) -> None:
        """After remove(), genome is no longer in any island."""
        ip = IslandPopulation(island_count=2)
        g = _genome("g0")
        iid = ip.assign(g)
        ip.remove("g0")
        assert "g0" not in ip.get_members(iid)
        assert ip.home_island("g0") is None


class TestTournamentDrawsFromIsland:
    def test_tournament_select_draws_from_island_only(self) -> None:
        """With island_count=3, _breed_island uses only island members as candidates."""
        store = PopulationStore()
        for i in range(9):
            g = _genome(f"g{i}", fitness_score=float(i))
            store.add(g)

        ip = IslandPopulation(island_count=3)
        for g in store.list_all():
            ip.assign(g)

        # Record ELO so tournament path fires in _breed_island.
        tournament = EloTournament()
        tournament.record_battle("proxy_ifeval", "g0", "g1", 0.5, 0.6)
        tournament.record_battle("proxy_ifeval", "g1", "g2", 0.6, 0.7)

        cycle = EvolutionCycle(harness=EvalHarness(), tournament=tournament)
        island_0_members_before = set(ip.get_members(0))

        cycle._breed_island(ip, 0, store, EvolutionConfig(population_size=9, island_count=3), cap=5)

        # Any new genomes in island 0 must have parents from island 0.
        # Note: mutation rewrites parent_a_id to the intermediate mutated genome's
        # id, so we verify via the crossover name (cross-{pa[:6]}-{pb[:6]}-all-mut)
        # which preserves the original parent prefixes.
        new_ids = set(ip.get_members(0)) - island_0_members_before
        island_prefixes = {mid[:6] for mid in island_0_members_before}
        for new_id in new_ids:
            child = store.get(new_id)
            assert child is not None
            if child.name.startswith("cross-") and child.name.endswith("-all-mut"):
                inner = child.name[len("cross-") : -len("-all-mut")]
                pa_prefix, _, pb_prefix = inner.partition("-")
                assert pa_prefix in island_prefixes, f"parent {pa_prefix!r} not from island 0"
                assert pb_prefix in island_prefixes, f"parent {pb_prefix!r} not from island 0"


class TestMigration:
    def test_migration_shares_best_genome_across_islands(self) -> None:
        """After migrate_islands, each island's pool contains the best from every other."""
        store = PopulationStore()
        ip = IslandPopulation(island_count=3)

        # Seed: g0→island0 (best), g1→island1 (mid), g2→island2 (low)
        genomes = [
            _genome("g0", fitness_score=0.9),
            _genome("g1", fitness_score=0.5),
            _genome("g2", fitness_score=0.1),
        ]
        for g in genomes:
            store.add(g)
            ip.assign(g)

        migrate_islands(ip, store)

        # Each island should now contain the best from every other island.
        assert "g0" in ip.get_members(1)  # island1 got best of island0
        assert "g0" in ip.get_members(2)  # island2 got best of island0
        assert "g1" in ip.get_members(0)  # island0 got best of island1
        assert "g2" in ip.get_members(0)  # island0 got best of island2

    def test_migration_does_not_duplicate_existing_members(self) -> None:
        """A genome already in its home island is not added twice after migration."""
        store = PopulationStore()
        ip = IslandPopulation(island_count=2)

        g0 = _genome("g0", fitness_score=0.9)
        store.add(g0)
        ip.assign(g0)

        g1 = _genome("g1", fitness_score=0.5)
        store.add(g1)
        ip.assign(g1)

        migrate_islands(ip, store)

        assert ip.get_members(0).count("g0") == 1
        assert ip.get_members(1).count("g1") == 1

    def test_high_fitness_genome_not_in_other_island_before_migration(self) -> None:
        """A genome dominates one island but is absent from others until migration fires."""
        ip = IslandPopulation(island_count=2)
        store = PopulationStore()

        champion = _genome("champ", fitness_score=99.0)
        rival = _genome("rival", fitness_score=1.0)
        store.add(champion)
        store.add(rival)
        ip.assign(champion)  # → island 0
        ip.assign(rival)  # → island 1

        # Before migration: champion is NOT in island 1's pool.
        assert "champ" not in ip.get_members(1)

        migrate_islands(ip, store)

        # After migration: champion IS in island 1's pool.
        assert "champ" in ip.get_members(1)


class TestIslandCountOneDegeneracy:
    @pytest.mark.asyncio
    async def test_island_count_1_degenerates_to_single_pool(self) -> None:
        """With island_count=1 all genomes land in one island — same as single-pool."""
        store = PopulationStore()
        for i in range(4):
            g = _genome(f"g{i}", fitness_score=float(i))
            store.add(g)

        config = EvolutionConfig(
            population_size=8,
            island_count=1,
            eval_batch_size=0,
            self_improve=False,
        )
        cycle = EvolutionCycle(harness=EvalHarness(), tournament=EloTournament())
        await cycle.run_cycle(store, llm_call=None, config=config)

        assert len(store.list_all()) > 4


class TestIslandCulling:
    def test_culling_respects_island_size_cap(self) -> None:
        """Genomes exceeding island_size_cap in _breed_island are not bred past the cap."""
        ip = IslandPopulation(island_count=2)
        store = PopulationStore()

        # Island 0 is already at cap=2; island 1 is empty.
        for gid in ("a", "b"):
            g = _genome(gid, fitness_score=1.0)
            store.add(g)
            ip.assign(g)  # round-robin: a→0, b→1

        cycle = EvolutionCycle(harness=EvalHarness(), tournament=EloTournament())
        # Cap = 1: island 0 already has 1 member (a) → no breeding needed.
        cycle._breed_island(ip, 0, store, EvolutionConfig(population_size=2, island_count=2), cap=1)

        assert len(ip.get_members(0)) == 1
