---
id: SPEC-070226-5ce3
title: "Evolve population — FunSearch-inspired island model for structured diversity"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-07-02
substrate:
  - maistro-engine#ADR-088
  - maistro-engine#SPEC-207
implements: []
related:
  - maistro-engine#SPEC-062926-8ec5
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: Evolve
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-070226-5ce3: Evolve Population — FunSearch-Inspired Island Model

## Context

`diversity.py`'s current mechanism for preventing population collapse is
**reactive**: `population_diversity()` monitors a trait-vector distance metric,
and `EvolutionCycle` emergency-spawns fresh random genomes only after diversity
falls below a threshold (`diversity_floor`). This means collapse has already
occurred before countermeasures fire, and the injected genomes carry no
inheritance from the fit individuals that survived.

FunSearch (Romera-Paredes et al., DeepMind 2023) uses a structurally different
approach: the population is partitioned into `k` semi-isolated **islands** that
each run a local evolutionary loop. The best individual from each island is
periodically shared with all other islands ("migration"). Islands diverge along
different search directions, and migration imports proven solutions without
forcing premature convergence on a single direction.

The key difference from the current mechanism: diversity is maintained
*structurally* (separate selection pools) rather than *reactively* (monitoring +
emergency spawn). A genome that dominates one island cannot immediately crowd out
the others, so exploration of multiple directions continues even after a strong
individual emerges.

## Goals

- Partition the population into `k` islands, each running independent tournament
  selection and mutation/crossover within its own member set.
- Migrate the best genome from each island to all other islands on a configurable
  epoch schedule, preserving inter-island gene flow.
- Replace the reactive emergency-spawn path with this structural mechanism (the
  `diversity_floor` threshold and `emergency_spawn` logic become redundant and
  are removed).
- Preserve the Elo tournament, fail-closed promotion gate, crossover, and
  mutation operators unchanged.

## Non-goals

- Parallel or async island execution (islands run sequentially within
  `run_cycle`; async execution is a future scaling concern).
- Per-island fitness functions or benchmark assignments.
- Changing how individual genomes are evaluated or how `PopulationStore.promote()`
  works.

## Decision

1. **`IslandPopulation`** (new class, `population.py`). Wraps `PopulationStore`
   and maintains a `dict[int, list[str]]` mapping island_id → genome_id list.
   Initial assignment: round-robin by insertion order. New genomes (from mutation,
   crossover, or reflection) are assigned to the same island as their primary
   parent (`parent_a_id`); genomes with no parent (seeds) are round-robined.

2. **Intra-island selection.** `tournament_select()` is called with the island's
   member list as the candidate pool rather than the full population. This is a
   call-site change in `EvolutionCycle`; `tournament_select()` itself is
   unchanged.

3. **Migration.** New `migrate_islands(island_pop, store)` function: for each
   island, finds the highest-fitness member and adds it to every *other* island's
   member list (not a copy — the genome is shared by id). Called at the end of
   every `migration_interval` cycles (`EvolutionConfig.migration_interval`,
   default 5).

4. **Culling.** When an island exceeds `island_size_cap` members (default:
   `population_size // k`), the lowest-fitness members are culled first within
   the island, then globally if the whole population is over cap.

5. **Config.** New `EvolutionConfig` fields: `island_count` (default 3),
   `migration_interval` (default 5). Both are optional; `island_count=1`
   degenerates to the current single-pool behavior (a clean escape hatch for
   small populations).

6. **Remove `diversity_floor` / `emergency_spawn`.** The reactive path in
   `EvolutionCycle` that checks `population_diversity()` and spawns emergency
   genomes is removed. `diversity.py`'s `population_diversity()` and
   `trait_vector()` are retained as diagnostic/observability utilities but no
   longer gate evolution.

## Acceptance criteria

- With `island_count=3`, tournament selection draws candidates only from within
  the same island as the current generation's parent.
- After `migration_interval` cycles, each island's member list contains the best
  genome from every other island.
- A genome that achieves high fitness on one island does not immediately appear
  as a tournament candidate on other islands until migration fires.
- With `island_count=1`, behavior is identical to the pre-spec single-pool
  evolution (regression guard).
- No emergency-spawn path exists after this spec lands; `diversity_floor` is
  removed from `EvolutionConfig`.
- All pre-existing `test_cycle.py`, `test_mutate.py`, and `test_rsi_safety.py`
  tests continue passing.

## Testing

New unit tests in `packages/maistro-evolve/tests/test_population.py` (or
`test_cycle.py` if that file already covers population integration):
`test_island_assignment_round_robin_for_seeds`,
`test_tournament_select_draws_from_island_only`,
`test_migration_shares_best_genome_across_islands`,
`test_island_count_1_degenerates_to_single_pool`,
`test_culling_respects_island_size_cap`.
Full-suite regression via `/verify-evolve`.

## Open questions

- Should migration be bidirectional (best of each island → all others, as
  specified) or unidirectional (best of best island → all others)? Bidirectional
  is richer but imports potentially weaker candidates into the best island.
  Defaulting to bidirectional for now.
- What is the right `island_count` default for a typical 20-genome population?
  `k=3` with `population_size=20` gives ~7 genomes per island, which is enough
  for a meaningful 3-way tournament. Needs empirical validation once real-fidelity
  benchmarks (SPEC-202) land.
- Should `population_diversity()` be re-wired as an island-level metric
  (intra-island diversity) rather than deprecated entirely? Keeping it as an
  observability util leaves the option open.

## References

- Romera-Paredes et al., "Mathematical discoveries from program search with large
  language models" (FunSearch, DeepMind 2023) — island-model population structure
  as the key mechanism enabling sustained exploration after strong solutions emerge.
- maistro-engine#SPEC-207 — reflective prompt evolution; defines the
  `PopulationStore`, tournament selection, and diversity mechanism this spec
  restructures.
- maistro-engine#ADR-088 — evolve experimental posture; basis for removing the
  `diversity_floor` / emergency-spawn path without a deprecation cycle.
- Implementation surfaces: `packages/maistro-evolve/src/maistro_evolve/diversity.py`,
  `cycle.py`, `tournament.py`, `types.py` (`EvolutionConfig`), new
  `population.py`.
