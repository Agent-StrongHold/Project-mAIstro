from __future__ import annotations

import logging
import random
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from .crossover import crossover_and_mutate
from .fitness import compute_fitness
from .harness import EvalHarness
from .hyper_mutator import entry_node, hyper_mutate, slot_lineage
from .optimizer import extract_signal, optimize_topology
from .population import IslandPopulation, PopulationStore, migrate_islands
from .promotion import (
    BEST_OF_N_KEY,
    EVIDENCE_CYCLE_KEY,
    HISTORY_KEY,
    OBJECTIVE_VERSION_KEY,
    SAMPLES_KEY,
    objective_version,
)
from .reflect import reflective_improve
from .tournament import EloTournament
from .types import PipelineGenome

logger = logging.getLogger("maistro_evolve.cycle")

# Hard, non-overridable ceilings on per-cycle resource/compute consumption.
# These are RSI safety bounds (not tuning knobs): an evolution loop with no
# enforced upper limit on eval batch size, population size, or self-improve
# fan-out can be pointed at an unboundedly large config and consume
# unboundedly large compute/cost in a single run_cycle() call. Pydantic's
# Field(le=...) rejects out-of-range values at construction time — there is
# no way to build an EvolutionConfig that exceeds these caps.
MAX_EVAL_BATCH_SIZE = 50
MAX_POPULATION_SIZE = 200
MAX_TOURNAMENT_SIZE = 20
MAX_SELF_IMPROVE_TOP_N = 10
MAX_SELF_IMPROVE_CANDIDATES = 10
MAX_REFLECT_HISTORY_WINDOW = 20
MAX_ISLAND_COUNT = 20
MAX_MIGRATION_INTERVAL = 100


class EvolutionConfig(BaseModel):
    population_size: int = Field(default=20, gt=0, le=MAX_POPULATION_SIZE)
    mutation_rate: float = 0.3
    cull_pct: float = 0.3
    breed_pct: float = 0.2
    eval_batch_size: int = Field(default=5, ge=0, le=MAX_EVAL_BATCH_SIZE)
    target_benchmarks: list[str] = [
        "proxy_ifeval",
        "proxy_bfcl",
        "proxy_swebench",
        "proxy_tau_bench",
    ]
    tournament_size: int = Field(default=3, gt=0, le=MAX_TOURNAMENT_SIZE)
    self_improve: bool = True
    self_improve_top_n: int = Field(default=3, ge=0, le=MAX_SELF_IMPROVE_TOP_N)
    self_improve_candidates: int = Field(default=2, ge=0, le=MAX_SELF_IMPROVE_CANDIDATES)
    self_improve_accept_margin: float = 0.0
    reflect_history_window: int = Field(default=5, ge=0, le=MAX_REFLECT_HISTORY_WINDOW)
    node_attribution: bool = True
    # Island model (FunSearch-style structural diversity, SPEC-070226-5ce3).
    # island_count=1 degenerates to the pre-spec single-pool behavior.
    island_count: int = Field(default=1, ge=1, le=MAX_ISLAND_COUNT)
    migration_interval: int = Field(default=5, ge=1, le=MAX_MIGRATION_INTERVAL)
    # Hyper-mutation (ADR-070126-6386 v2): genomes whose entry node carries a
    # typed FixerGenome route their self-improve step through the LLM
    # hyper-mutator (guided slot proposals) INSTEAD of free-text reflection —
    # reflection rewrites node.system_prompt, which genome_to_competitor ignores
    # when a fixer is present, so reflecting those genomes would burn expensive
    # code_rsi evals mutating an inert string. Shares the self_improve_* budget
    # knobs above.
    hyper_mutate: bool = True
    # Operator context threaded into the hyper-mutator's meta-prompt.
    goal: str = ""
    user_preferences: str = ""
    # The run's routable model roster. When set, breeding/mutation only assigns
    # models from it — mutating a lineage onto a model the gateway can't serve is
    # a guaranteed-0 evaluation whose dead gene then spreads (observed live: a
    # drifted `gemini-2.5-flash` child burned evals on 429s two generations deep).
    # Empty ⇒ the generic MODEL_REGISTRY (unit-test/offline behavior).
    allowed_models: list[str] = []
    # Weight of the NEWEST benchmark sample when a genome is re-evaluated:
    # score = alpha*new + (1-alpha)*old (exponential moving average). 1.0
    # restores the raw-overwrite behavior; lower = stickier history. Damps
    # agent-nondeterminism noise on repeat sampling (a genome scored 0.76 then
    # 0.0 across two identical evals in a live run).
    eval_ema_alpha: float = Field(default=0.5, gt=0.0, le=1.0)
    # How many already-evaluated genomes get a FRESH independent sample per
    # cycle (#854). The cycle used to evaluate every genome exactly once —
    # a lucky first sample became permanent and the EMA never ran through the
    # real cycle. Each cycle now re-samples the genomes whose evidence is
    # weakest/oldest (best-of-N-pending confirmations first), producing the
    # repeated independent evidence the promotion policy requires.
    reconfirm_per_cycle: int = Field(default=2, ge=0, le=MAX_EVAL_BATCH_SIZE)


class EvolutionCycle:
    def __init__(
        self,
        harness: EvalHarness | None = None,
        tournament: EloTournament | None = None,
    ) -> None:
        self.harness = harness or EvalHarness()
        self.tournament = tournament or EloTournament()
        self._island_pop: IslandPopulation | None = None
        self._cycle_count: int = 0

    @staticmethod
    def _fold_score(
        genome: PipelineGenome, benchmark: str, score: float, stub: bool, alpha: float
    ) -> None:
        """Fold a new benchmark sample into the genome's score as an exponential
        moving average: ``alpha*new + (1-alpha)*old``.

        Agent-backed benchmarks (code_rsi) are nondeterministic — a genome scored
        0.76 at acceptance and 0.0 on re-evaluation in a live run — so a raw
        overwrite makes fitness a lottery over the LAST sample. The EMA damps
        that noise while still weighting recent behavior highest. Two rules:
        the first real sample stands alone (nothing to blend), and a STUB sample
        (transient gateway/agent failure — SPEC-202: noise, not evidence) never
        overwrites or dilutes real signal; it only stands in when there is no
        real score yet.
        """
        prior = genome.eval_scores.get(benchmark)
        if stub and prior is not None:
            return
        if prior is None:
            genome.eval_scores[benchmark] = score
        else:
            genome.eval_scores[benchmark] = round(alpha * score + (1 - alpha) * prior, 4)
        samples: dict[str, int] = genome.harness_params.setdefault("eval_samples", {})
        samples[benchmark] = samples.get(benchmark, 0) + 1
        # Full sample history per benchmark — the raw material for the
        # uncertainty bound (sample std) in the #854 governed-promotion policy.
        history: list[float] = genome.harness_params.setdefault(HISTORY_KEY, {}).setdefault(
            benchmark, []
        )
        history.append(score)

    def _stamp_evidence(self, genome: PipelineGenome, cfg: EvolutionConfig) -> None:
        """Stamp freshly-folded evidence with the objective it was measured
        under and the cycle that measured it (#854 evidence currency)."""
        genome.harness_params[OBJECTIVE_VERSION_KEY] = objective_version(cfg.target_benchmarks)
        genome.harness_params[EVIDENCE_CYCLE_KEY] = self._cycle_count

    async def _eval_and_fold(
        self,
        genome: PipelineGenome,
        cfg: EvolutionConfig,
        llm_call: Any,
    ) -> None:
        """Evaluate one genome across the config's benchmarks, EMA-folding each
        result into its evidence (shared by first-eval and reconfirmation)."""
        results = await self.harness.evaluate_genome(genome, cfg.target_benchmarks, llm_call)
        for r in results:
            self._fold_score(
                genome,
                r.benchmark,
                r.score,
                bool(r.metadata.get("stub")),
                cfg.eval_ema_alpha,
            )
            genome.harness_params["total_cost_usd"] = (
                genome.harness_params.get("total_cost_usd", 0.0) + r.cost_usd
            )
            genome.harness_params["avg_latency_seconds"] = (
                genome.harness_params.get("avg_latency_seconds", 0.0) + r.duration_seconds
            ) / max(len(genome.eval_scores), 1)
        self._stamp_evidence(genome, cfg)
        genome.updated_at = datetime.now(UTC).isoformat()

    async def _evaluate_unevaluated(
        self,
        population: PopulationStore,
        config: EvolutionConfig,
        llm_call: Any = None,
    ) -> None:
        all_genomes = population.list_all()
        unevaluated = [g for g in all_genomes if g.fitness_score is None or not g.eval_scores]
        batch = unevaluated[: config.eval_batch_size]
        for genome in batch:
            await self._eval_and_fold(genome, config, llm_call)
            population.add(genome)

    async def _reconfirm_candidates(
        self,
        population: PopulationStore,
        config: EvolutionConfig,
        llm_call: Any = None,
    ) -> None:
        """Take fresh independent samples of already-evaluated genomes (#854).

        Priority: genomes still pending fresh confirmation after a best-of-N
        acceptance (the winner's-curse guard needs post-acceptance evidence),
        then the fewest-sampled, then the stalest evidence. This is the
        production step that makes repeated evaluation/EMA actually run
        through the cycle instead of leaving every genome with one permanent
        lucky (or unlucky) sample.
        """
        if config.reconfirm_per_cycle <= 0:
            return
        candidates = [g for g in population.list_all() if g.eval_scores]
        if not candidates:
            return

        def _priority(g: PipelineGenome) -> tuple[int, int, int]:
            params = g.harness_params
            samples: dict[str, int] = params.get(SAMPLES_KEY, {})
            pending: dict[str, Any] | None = params.get(BEST_OF_N_KEY)
            confirmed = 1 if pending is None else 0
            min_samples = min(samples.values()) if samples else 0
            evidence_cycle = int(params.get(EVIDENCE_CYCLE_KEY, -1))
            return (confirmed, min_samples, evidence_cycle)

        candidates.sort(key=_priority)
        for genome in candidates[: config.reconfirm_per_cycle]:
            await self._eval_and_fold(genome, config, llm_call)
            population.add(genome)

    async def _run_tournament_battles(
        self,
        population: PopulationStore,
        config: EvolutionConfig,
    ) -> None:
        all_genomes = population.list_all()
        if len(all_genomes) < 2:
            return

        scored = [g for g in all_genomes if g.eval_scores]
        if len(scored) < 2:
            return

        pairs_to_battle: list[tuple[PipelineGenome, PipelineGenome]] = []
        shuffled = list(scored)
        random.shuffle(shuffled)
        for i in range(0, len(shuffled) - 1, 2):
            pairs_to_battle.append((shuffled[i], shuffled[i + 1]))

        for a, b in pairs_to_battle:
            common_benchmarks = set(a.eval_scores.keys()) & set(b.eval_scores.keys())
            for bench in common_benchmarks:
                self.tournament.record_battle(
                    benchmark=bench,
                    genome_a_id=a.id,
                    genome_b_id=b.id,
                    score_a=a.eval_scores[bench],
                    score_b=b.eval_scores[bench],
                )

        for g in scored:
            avg_elo = self.tournament.get_avg_elo(g.id)
            if avg_elo > 0:
                g.harness_params["avg_elo"] = avg_elo

    def _compute_all_fitness(self, population: PopulationStore) -> list[PipelineGenome]:
        all_genomes = population.list_all()
        for g in all_genomes:
            components = compute_fitness(g, all_genomes)
            g.fitness_score = components.total
            g.updated_at = datetime.now(UTC).isoformat()
            population.add(g)
        return population.list_all()

    def _breed_island(
        self,
        island_pop: IslandPopulation,
        island_id: int,
        population: PopulationStore,
        config: EvolutionConfig,
        cap: int,
    ) -> None:
        """Breed within a single island until it reaches `cap` members."""
        members = island_pop.get_members(island_id)
        needed = max(0, cap - len(members))
        if needed == 0:
            return

        genome_map = {g.id: g for g in population.list_all()}

        if self.tournament.get_stats()["total_genomes_rated"] >= 2:
            parent_ids: list[str] = []
            for _ in range(needed * 2):
                selected = self.tournament.tournament_select(
                    members, tournament_size=config.tournament_size
                )
                if selected:
                    parent_ids.append(selected)
            for i in range(0, min(needed, len(parent_ids) - 1), 2):
                a = genome_map.get(parent_ids[i])
                b = genome_map.get(parent_ids[i + 1] if i + 1 < len(parent_ids) else parent_ids[0])
                if a and b:
                    child = crossover_and_mutate(
                        a, b, config.mutation_rate, models=config.allowed_models or None
                    )
                    population.add(child)
                    # Use force_assign: mutation chains rewrite parent_a_id, so
                    # assign() would fall back to round-robin and place the child
                    # on the wrong island.
                    island_pop.force_assign(child.id, island_id)
        else:
            island_scored = [
                g
                for mid in members
                if (g := genome_map.get(mid)) is not None and g.fitness_score is not None
            ]
            island_scored.sort(key=lambda g: g.fitness_score or 0.0, reverse=True)
            pool_size = max(2, int(config.population_size * config.breed_pct))
            breeding_pool = island_scored[:pool_size]
            for _ in range(needed):
                pa: PipelineGenome | None
                pb: PipelineGenome | None
                if len(breeding_pool) >= 2:
                    pa, pb = random.sample(breeding_pool, 2)
                else:
                    pa = breeding_pool[0] if breeding_pool else None
                    pb = None
                if pa and pb:
                    child = crossover_and_mutate(
                        pa, pb, config.mutation_rate, models=config.allowed_models or None
                    )
                    population.add(child)
                    island_pop.force_assign(child.id, island_id)

    async def _hyper_mutate_one(
        self,
        genome: PipelineGenome,
        population: PopulationStore,
        config: EvolutionConfig,
        llm_call: Any,
        all_genomes: list[PipelineGenome],
    ) -> None:
        """Guided slot mutation for one typed-fixer genome (propose→verify; an
        accepted challenger joins as a child). Keeps a bounded proposal history in
        harness_params so future rounds see the OPRO-style trajectory."""
        window = config.reflect_history_window
        stored: list[tuple[str, float]] = genome.harness_params.get("hyper_history", [])
        outcome = await hyper_mutate(
            genome,
            self.harness,
            llm_call,
            benchmarks=config.target_benchmarks,
            num_candidates=config.self_improve_candidates,
            accept_margin=config.self_improve_accept_margin,
            lineage=slot_lineage(genome, all_genomes),
            goal=config.goal,
            preferences=config.user_preferences,
            history=[(exc, sc) for exc, sc in stored][-window:] if window > 0 else [],
        )
        if outcome is None:
            return
        if outcome.accepted and outcome.challenger is not None:
            # Winner's-curse provenance (#854): this challenger was selected as
            # the max of N siblings — exactly the genome most likely to be a
            # lucky sample. It stays promotion-ineligible (best-of-N guard in
            # promotion.selection_eligibility) until it gathers fresh samples
            # beyond the round that selected it.
            outcome.challenger.harness_params[BEST_OF_N_KEY] = {
                "benchmark": outcome.benchmark,
                "claimed_score": outcome.best_candidate_score,
                "candidates": outcome.candidate_count,
                "samples_at_acceptance": dict(
                    outcome.challenger.harness_params.get(SAMPLES_KEY, {})
                ),
            }
            population.add(outcome.challenger)
        if window > 0 and outcome.best_candidate_slots and outcome.best_candidate_score is not None:
            import json as _json

            entry: tuple[str, float] = (
                _json.dumps(outcome.best_candidate_slots)[:160],
                outcome.best_candidate_score,
            )
            updated = [*stored, entry][-window:]
            genome.harness_params["hyper_history"] = updated
            if outcome.accepted and outcome.challenger is not None:
                outcome.challenger.harness_params["hyper_history"] = updated
        genome.harness_params["last_hyper_mutation"] = outcome.summary()
        genome.updated_at = datetime.now(UTC).isoformat()
        population.add(genome)

    async def _self_improve_top(
        self,
        population: PopulationStore,
        config: EvolutionConfig,
        llm_call: Any = None,
    ) -> None:
        if not config.self_improve or llm_call is None:
            return

        all_genomes = population.list_all()
        scored = [g for g in all_genomes if g.fitness_score is not None and g.fitness_score > 0]
        if not scored:
            return

        scored.sort(key=lambda g: g.fitness_score or 0.0, reverse=True)
        top = scored[: config.self_improve_top_n]

        for genome in top:
            # Typed-fixer genomes route through the hyper-mutator (see the
            # hyper_mutate config comment): free-text reflection would rewrite a
            # system_prompt that genome_to_competitor ignores for these genomes.
            node = entry_node(genome)
            if config.hyper_mutate and node is not None and node.fixer is not None:
                await self._hyper_mutate_one(genome, population, config, llm_call, all_genomes)
                continue

            from .types import EvalResult

            eval_results = [EvalResult(benchmark=k, score=v) for k, v in genome.eval_scores.items()]
            signal = extract_signal(genome, eval_results)

            window = config.reflect_history_window
            # History entries are (benchmark, excerpt, score); filter to the genome's
            # current weakest benchmark so OPRO trajectory stays coherent across cycles
            # where the target benchmark shifts (benchmark-specific, SPEC-070226-83bd).
            stored_history: list[tuple[str, str, float]] = genome.harness_params.get(
                "reflection_history", []
            )
            target_set = set(config.target_benchmarks)
            relevant = {b: s for b, s in genome.eval_scores.items() if b in target_set}
            expected_bench = min(relevant, key=lambda b: relevant[b]) if relevant else None
            if window > 0 and expected_bench is not None:
                bench_entries = [
                    (exc, sc) for bm, exc, sc in stored_history if bm == expected_bench
                ]
                prompt_history = bench_entries[-window:]
            else:
                prompt_history = []

            # Propose-then-verify (GEPA-style): the parent is never mutated in
            # place; an accepted challenger joins the pool as its child.
            outcome = await reflective_improve(
                genome,
                self.harness,
                llm_call,
                benchmarks=config.target_benchmarks,
                num_candidates=config.self_improve_candidates,
                accept_margin=config.self_improve_accept_margin,
                prompt_history=prompt_history,
                node_attribution=config.node_attribution,
            )
            if outcome is not None and outcome.accepted and outcome.challenger is not None:
                # Winner's-curse provenance (#854) — same guard as the
                # hyper-mutator path above.
                outcome.challenger.harness_params[BEST_OF_N_KEY] = {
                    "benchmark": outcome.benchmark,
                    "claimed_score": outcome.best_candidate_score,
                    "candidates": outcome.candidate_count,
                    "samples_at_acceptance": dict(
                        outcome.challenger.harness_params.get(SAMPLES_KEY, {})
                    ),
                }
                population.add(outcome.challenger)

            # Persist new (benchmark, excerpt, score) entry so future cycles have a
            # coherent per-benchmark trajectory (window=0 disables persistence entirely).
            if (
                window > 0
                and outcome is not None
                and outcome.best_candidate_prompt_excerpt is not None
                and outcome.best_candidate_score is not None
            ):
                new_entry: tuple[str, str, float] = (
                    outcome.benchmark,
                    outcome.best_candidate_prompt_excerpt,
                    outcome.best_candidate_score,
                )
                updated_history = [*stored_history, new_entry][-window:]
                genome.harness_params["reflection_history"] = updated_history
                # Propagate to accepted challenger so its next cycle sees the trajectory.
                if outcome.accepted and outcome.challenger is not None:
                    outcome.challenger.harness_params["reflection_history"] = updated_history

            topo_signal = await optimize_topology(genome, signal, llm_call)
            genome.harness_params["last_optimization"] = {
                "signal": signal,
                "reflection": outcome.summary() if outcome is not None else None,
                "topology_suggestion": topo_signal,
                "timestamp": datetime.now(UTC).isoformat(),
            }

            genome.updated_at = datetime.now(UTC).isoformat()
            population.add(genome)

    async def run_cycle(
        self,
        population: PopulationStore,
        llm_call: Any = None,
        config: EvolutionConfig | None = None,
    ) -> PopulationStore:
        cfg = config or EvolutionConfig()

        if self.harness.fidelity != "real":
            logger.warning(
                "evolve_cycle_fidelity: this run's fitness signal is '%s' — "
                "heuristic/lite scoring against handcrafted samples, not the "
                "official benchmarks. See SPEC-202.",
                self.harness.fidelity,
            )

        await self._evaluate_unevaluated(population, cfg, llm_call)

        # Fresh independent samples for already-evaluated genomes: this is what
        # turns the EMA estimator and the promotion policy's independent-
        # evidence floor into behavior the real cycle actually exercises (#854).
        await self._reconfirm_candidates(population, cfg, llm_call)

        await self._run_tournament_battles(population, cfg)

        self._compute_all_fitness(population)

        population.cull_bottom(cfg.cull_pct)

        # Initialize or reset island population when island_count changes.
        if self._island_pop is None or self._island_pop.island_count != cfg.island_count:
            self._island_pop = IslandPopulation(cfg.island_count)
        island_pop = self._island_pop

        # Assign all current genomes to islands (idempotent for known genomes).
        for genome in population.list_all():
            island_pop.assign(genome)

        # Per-island breeding: each island fills to its size cap independently.
        # With island_count=1, island 0 == the full population → identical to
        # the pre-island single-pool behavior (regression guard, SPEC-070226-5ce3).
        island_size_cap = max(1, cfg.population_size // cfg.island_count)
        for iid in island_pop.all_islands():
            self._breed_island(island_pop, iid, population, cfg, island_size_cap)

        # Assign any children produced by self-improve to their parent's island.
        await self._self_improve_top(population, cfg, llm_call)
        for genome in population.list_all():
            island_pop.assign(genome)

        # Migration: share the best genome from each island to all others.
        self._cycle_count += 1
        if self._cycle_count % cfg.migration_interval == 0:
            migrate_islands(island_pop, population)

        return population
