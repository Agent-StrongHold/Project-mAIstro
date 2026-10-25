"""Stage 3 (ADR-070126-6386): drive an evolving genome population with code_rsi.

This is the "improve the improver" wiring. The tournament's competitors are no
longer a fixed roster — they are a `maistro_evolve` genome population, scored by
the code fix each genome's config produces (the `code_rsi` benchmark), and bred
by `EvolutionCycle` toward the prompt/model/config that fixes code best.

The heavy part — actually running an agent to fix a file and scoring it with the
RSI Scorecard — is injected as `fix_and_score`, so this module stays testable and
`maistro_evolve` stays free of any `maistro_rsi` dependency (the benchmark is
*registered into* the harness, not imported by it).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from maistro_evolve.code_rsi import evaluate_code_rsi
from maistro_evolve.fixer_genome import render_system_prompt
from maistro_evolve.harness import BenchmarkRunner, EvalHarness
from maistro_evolve.population import PopulationStore
from maistro_evolve.types import EvalResult, PipelineGenome
from maistro_rsi.competitors import Competitor
from maistro_rsi.free_router import FreeSelector, expand_free_router

# Runs a genome's fixer config against a target file and returns the RSI
# scorecard outcome: (gates_passed, composite, is_stub).
FixAndScore = Callable[[Competitor, str], Awaitable[tuple[bool, float, bool]]]


def genome_to_competitor(genome: PipelineGenome) -> Competitor:
    """Project a genome's entry (fixer) node onto a `Competitor` config.

    The entry node is the one the pipeline runs first — its model and strategy
    are what actually author the fix, so that's the competitor the tournament
    runs and the population evolves. When the entry node carries a `FixerGenome`
    (ADR-070126-6386 v2 — the typed, evolvable strategy layer), it supplies the
    competitor's rendered system prompt and sampling knobs; otherwise the node's
    own temperature is used and the competitor gets no system prompt override
    (falls back to the builders default), matching the pre-genome behaviour.
    """
    nodes = genome.topology.nodes
    entry = next((n for n in nodes if n.id == genome.topology.entry_node), nodes[0])
    fixer = entry.fixer
    if fixer is None:
        return Competitor(
            model=entry.model,
            temperature=entry.temperature,
            label=f"{genome.name}:{entry.model}",
        )
    return Competitor(
        model=entry.model,
        temperature=fixer.temperature if fixer.reasoning_effort is None else None,
        reasoning_effort=fixer.reasoning_effort.value if fixer.reasoning_effort else None,
        prompt=render_system_prompt(fixer),
        label=f"{genome.name}:{entry.model}",
    )


def make_code_rsi_runner(fix_and_score: FixAndScore, target: str) -> BenchmarkRunner:
    """Build the `code_rsi` benchmark runner: score a genome by the fix its
    config produces, mapped through the evolve hard-gate/stub-honesty rules."""

    async def runner(genome: PipelineGenome, _llm_call: Any) -> EvalResult:
        competitor = genome_to_competitor(genome)
        accepted, composite, is_stub = await fix_and_score(competitor, target)
        return evaluate_code_rsi(genome.id, target, lambda _g, _t: (accepted, composite, is_stub))

    return runner


def seed_population(
    store: PopulationStore,
    n: int,
    models: list[str] | None = None,
    *,
    free_selector: FreeSelector | None = None,
) -> set[str]:
    """Top the store up to `n` genomes with random fixer seeds (model/temp/prompt).
    Returns the set of concrete free aliases resolved (empty when none).

    TOP-UP, not blind seeding: a persisted population.db is the lineage — its
    genomes carry evolved slots and the hyper-mutator's written learnings
    (learned_successes/learned_failures) — so resuming a run must NOT bury it
    under fresh randoms. An existing population of >= n genomes is left alone;
    a partial one is topped up; only an empty store gets the full n.

    Pass ``models`` (gateway aliases like the `code` group) to pin EVERY node to a
    real, routable alias — evolve's own MODEL_REGISTRY names aren't LiteLLM
    aliases, so a live run must seed with servable models. The same roster must
    also reach EvolutionConfig.allowed_models so breeding/mutation can't drift a
    lineage back off it (an unroutable model is a guaranteed-0 evaluation).

    A ``free-router`` sentinel in ``models`` (see `free_router`) is not seeded
    literally — it re-randomises every call. Each genome that draws it gets its
    OWN concrete free model resolved-and-pinned via ``free_selector``, so the
    population seeds onto a spread of distinct, stable, $0 models.
    """
    from maistro_evolve.diversity import _random_genome

    resolved: set[str] = set()
    existing = len(store.list_all())
    for i in range(max(0, n - existing)):
        seed_models = expand_free_router(models, free_selector, resolved=resolved)
        # Round-robin across the roster (NOT a random draw per node): pin genome i
        # to one model so EVERY roster model fields a lineage from cycle one —
        # evolution can only learn per-model differences from models that actually
        # seed genomes, and a random draw can leave a model unseeded entirely.
        # OFFSET by `existing` so a top-up CONTINUES the rotation past the models
        # already seeded instead of re-covering models 0..k and starving the rest.
        pinned = [seed_models[(existing + i) % len(seed_models)]] if seed_models else None
        store.add(_random_genome(pinned))
    return resolved


async def run_evolution(
    store: PopulationStore,
    harness: EvalHarness,
    cycles: int,
    config: Any = None,
    llm_call: Any = None,
) -> PopulationStore:
    """Run `EvolutionCycle` for `cycles` iterations, evolving the fixer population
    against whatever benchmarks `config.target_benchmarks` names (``code_rsi``)."""
    from maistro_evolve.cycle import EvolutionCycle

    cycle = EvolutionCycle(harness=harness)
    for _ in range(cycles):
        await cycle.run_cycle(store, llm_call=llm_call, config=config)
    return store


def open_population(db_path: str | Path | None = None) -> PopulationStore:
    """Open (or create) the persisted fixer population — lineage survives runs."""
    return PopulationStore(db_path=db_path)
