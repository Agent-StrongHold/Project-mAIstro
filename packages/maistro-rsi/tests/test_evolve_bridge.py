"""Stage 3 (ADR-070126-6386): code_rsi drives EvolutionCycle.

The tournament's competitors stop being a fixed roster and become an evolving
genome population: a genome is scored by the code fix its config produces
(the code_rsi benchmark), and EvolutionCycle culls/breeds toward the configs
that fix code best. These tests pin the bridge + the evolution wiring with a
fast injected fix-and-score (no real agents/network).
"""

from __future__ import annotations

import pytest

from maistro_evolve.diversity import _random_genome
from maistro_evolve.types import EvalResult
from maistro_rsi.evolve_bridge import (
    genome_to_competitor,
    make_code_rsi_runner,
    run_evolution,
    seed_population,
)


@pytest.mark.ac("ADR-070126-6386/stage3")
def test_genome_to_competitor_uses_entry_node() -> None:
    g = _random_genome()
    entry = next(n for n in g.topology.nodes if n.id == g.topology.entry_node)
    comp = genome_to_competitor(g)
    assert comp.model == entry.model
    # _random_genome() seeds a FixerGenome (ADR-070126-6386 v2) on every node, so
    # the competitor's sampling knobs come from the fixer's own dials, not the
    # bare node field — see test_genome_to_competitor_without_fixer_falls_back_to_node
    # for the pre-genome legacy path. reasoning_effort and temperature are mutually
    # exclusive at the LLM callable (reasoning_effort wins), so the random fixer
    # projects onto exactly one of them.
    if entry.fixer.reasoning_effort is None:
        assert comp.temperature == entry.fixer.temperature
        assert comp.reasoning_effort is None
    else:
        assert comp.temperature is None
        assert comp.reasoning_effort == entry.fixer.reasoning_effort.value
    assert comp.prompt is not None  # the fixer's slots are rendered into it


@pytest.mark.ac("ADR-070126-6386/stage3")
def test_genome_to_competitor_without_fixer_falls_back_to_node() -> None:
    g = _random_genome()
    entry = next(n for n in g.topology.nodes if n.id == g.topology.entry_node)
    entry.fixer = None  # legacy genome, predates the typed strategy layer
    comp = genome_to_competitor(g)
    assert comp.model == entry.model
    assert comp.temperature == entry.temperature
    assert comp.prompt is None


@pytest.mark.ac("ADR-070126-6386/stage3")
def test_seed_population_tops_up_never_buries_a_lineage() -> None:
    # A persisted population is the lineage (evolved slots + written learnings):
    # resuming a run must top up to n, not add n fresh randoms on top.
    from maistro_evolve.population import PopulationStore

    store = PopulationStore()
    seed_population(store, 4)
    lineage_ids = {g.id for g in store.list_all()}
    assert len(lineage_ids) == 4
    seed_population(store, 4)  # resume with a full population: no-op
    assert {g.id for g in store.list_all()} == lineage_ids
    for gid in list(lineage_ids)[:2]:
        store.remove(gid)  # a cull shrank the population
    seed_population(store, 4)  # resume: top up the 2 missing, keep the 2 evolved
    survivors = {g.id for g in store.list_all()}
    assert len(survivors) == 4
    assert len(survivors & lineage_ids) == 2


@pytest.mark.ac("ADR-070126-6386/stage3")
async def test_code_rsi_runner_scores_genome_by_its_fix() -> None:
    async def fake_fix_and_score(comp, target):  # type: ignore[no-untyped-def]
        return (True, 0.7, False)  # accepted, composite, is_stub

    runner = make_code_rsi_runner(fake_fix_and_score, "pkg/x.py")
    res = await runner(_random_genome(), None)
    assert isinstance(res, EvalResult)
    assert res.benchmark == "code_rsi"
    assert res.score == 0.7


@pytest.mark.ac("ADR-070126-6386/stage3")
async def test_runner_honours_gate_veto_and_stub() -> None:
    async def vetoed(comp, target):  # type: ignore[no-untyped-def]
        return (False, 0.9, False)

    async def stubbed(comp, target):  # type: ignore[no-untyped-def]
        return (True, 0.9, True)

    assert (await make_code_rsi_runner(vetoed, "x.py")(_random_genome(), None)).score == 0.0
    assert (await make_code_rsi_runner(stubbed, "x.py")(_random_genome(), None)).score == 0.0


@pytest.mark.ac("ADR-070126-6386/stage3")
async def test_population_evolves_under_code_rsi(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import random

    from maistro_evolve.cycle import EvolutionConfig
    from maistro_evolve.harness import EvalHarness
    from maistro_evolve.population import PopulationStore

    # Evolve's randomness is unseeded (module gotcha) and this test asserts an
    # emergent outcome (offspring survive 3 cycles of culling) — flaky ~1-in-6
    # unpinned. Fix the seed so the trajectory is deterministic.
    random.seed(20260703)

    store = PopulationStore(db_path=tmp_path / "pop.db")
    seed_population(store, 6)

    async def fix_and_score(comp, target):  # type: ignore[no-untyped-def]
        # A fake preference: genomes whose fixer model name contains a digit
        # score higher, so evolution has a gradient to climb.
        strong = any(c.isdigit() for c in comp.model)
        return (True, 0.9 if strong else 0.3, False)

    harness = EvalHarness()
    harness.register_benchmark("code_rsi", make_code_rsi_runner(fix_and_score, "x.py"))
    cfg = EvolutionConfig(
        target_benchmarks=["code_rsi"], population_size=6, eval_batch_size=6, tournament_size=2
    )
    await run_evolution(store, harness, cycles=3, config=cfg)

    genomes = store.list_all()
    # The population was actually evaluated on code_rsi and bred (a real cycle ran).
    assert any(g.eval_scores.get("code_rsi") is not None for g in genomes)
    assert any(g.generation > 0 for g in genomes)  # offspring were created
    assert store.get_champion() is not None


@pytest.mark.ac("ADR-070126-6386/stage3")
def test_seed_population_topup_continues_rotation(tmp_path) -> None:  # type: ignore[no-untyped-def]
    # Codex P2 (#250): a top-up must CONTINUE the round-robin past already-seeded
    # models, not restart at 0 (which re-covers m-a/m-b and starves m-c).
    from maistro_evolve.population import PopulationStore

    store = PopulationStore(db_path=tmp_path / "pop.db")
    seed_population(store, 1, models=["m-a", "m-b", "m-c"])  # existing seed -> m-a
    seed_population(store, 3, models=["m-a", "m-b", "m-c"])  # top-up must add m-b, m-c
    models = {genome_to_competitor(g).model for g in store.list_all()}
    assert models == {"m-a", "m-b", "m-c"}
