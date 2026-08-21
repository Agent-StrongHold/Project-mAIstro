---
id: SPEC-070226-bfa3
title: "Evolve reflect — Reflexion-style verbal episodic memory via maistro.memory"
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
  - maistro-engine#SPEC-070226-83bd
  - maistro-engine#ADR-057
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
  - cross-service
tests: []
layer: Evolve
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-070226-bfa3: Evolve Reflect — Reflexion-Style Verbal Episodic Memory

## Context

Reflexion (Shinn et al., 2023) introduces a complementary axis to prompt
mutation: instead of distilling failure insights *into* the agent's system prompt,
failure reflections are stored as **verbal episodic memory** and retrieved at
inference time. The agent at each new trial retrieves its most relevant prior
failure reflections and prepends them to its context window. This sidesteps the
edit-budget problem (the system prompt is never mutated) and accumulates failure
knowledge faster than prompt tuning alone, since no benchmark re-evaluation is
needed before a reflection can take effect.

`maistro-core` already ships `maistro.memory` with scoped episodic stores, decay,
and retrieval. The 7-tier memory model includes episodic memory at the agent
scope. This makes Reflexion a *small extension* to an existing subsystem rather
than a new module: the reflection text generated during `reflect.py`'s rollout is
already available; it just needs to be written to the episodic store and retrieved
at genome evaluation time.

The two mechanisms are complementary and non-exclusive:
- `reflect.py`'s prompt-mutation path improves the genome's *default* behavior
  (persisted in the system prompt, applied on every inference, no memory lookup
  cost).
- The Reflexion episodic path improves behavior *immediately* (no re-evaluation
  needed, no edit-budget consumed) and decays naturally under the existing memory
  decay model if the failure pattern doesn't recur.

## Goals

- Write each reflection's failure summary to the genome's episodic memory store
  (scoped to the genome's agent identity) after a reflection cycle completes,
  regardless of whether the challenger was accepted.
- At benchmark evaluation time, retrieve the top-K most relevant episodic entries
  and prepend them to the evaluated prompt's context (not to the system prompt —
  the system prompt remains governed by `mutate_prompt()` and the edit budget).
- Use the existing `maistro.memory` episodic API; no new memory primitives.

## Non-goals

- Replacing the prompt-mutation path — both run, independently.
- Long-term retention of every reflection forever (existing episodic decay applies;
  reflections that don't recur fade naturally).
- Changing the acceptance gate, stub guard, edit budget, or margin floor.
- New memory tiers or changes to the 7-tier model.

## Decision

1. **Write path.** After `reflect_on_genome()` completes (accepted *or* rejected
   challenger), write a `ReflexionEntry` to the genome's episodic store:
   `{"benchmark": name, "score": baseline_score, "summary": failure_summary,
   "genome_id": genome.id}`. `failure_summary` is a 1–3 sentence natural-language
   description of what failed, extracted from `failure_traces` by a lightweight
   LLM call (or, when traces are absent, from the raw score delta).

2. **Retrieve path.** `EvalHarness.run_benchmark()` gains an optional
   `episodic_store` parameter. When provided, it retrieves the top
   `EvolutionConfig.reflexion_memory_k` entries (default 3) most relevant to the
   current benchmark (by benchmark name match + recency), formats them as a
   `## Past failures` block, and prepends this block to the prompt sent to the
   LLM at evaluation time. The *system prompt field of the genome is not
   modified*.

3. **Scope and decay.** Episodic entries are scoped to `genome.id` (agent scope
   in `maistro.memory`). They decay under the standard episodic decay schedule —
   no special retention policy. Entries survive genome culling (the store is not
   coupled to `PopulationStore` lifecycle); this is intentional: a revived genome
   or a child that inherits parent identity should benefit from its parent's
   failure history.

4. **Config.** New `EvolutionConfig` fields: `reflexion_enabled` (bool, default
   `False` — opt-in, since it requires `maistro.memory` to be wired), `reflexion_memory_k`
   (int, default 3).

5. **Integration point.** `EvolutionCycle` passes the episodic store to
   `EvalHarness` when `reflexion_enabled=True` and an episodic store is available
   in the DI container. When `reflexion_enabled=False` or no store is wired,
   both the write and retrieve paths are no-ops — maistro-evolve remains usable
   standalone without maistro-core memory.

## Acceptance criteria

- After a reflection cycle, a `ReflexionEntry` is written to the genome's
  episodic store (whether or not the challenger was accepted).
- At the next evaluation of that genome, the `## Past failures` block appears in
  the evaluation prompt and contains the written entry.
- With `reflexion_enabled=False` or no episodic store wired, neither the write
  nor the retrieve path executes and no error is raised.
- The genome's system prompt field is unchanged by the retrieve path.
- All pre-existing `test_reflect.py` and `test_cycle.py` tests continue passing
  (reflexion defaults to off, so they're unaffected).

## Testing

New unit tests in `packages/maistro-evolve/tests/test_reflect.py`:
`test_reflexion_entry_written_after_cycle`,
`test_reflexion_block_prepended_at_eval`,
`test_reflexion_disabled_is_noop`,
`test_system_prompt_unchanged_by_reflexion_retrieve`.
Uses an in-memory episodic store stub; no maistro-core dependency in the test
environment. Full-suite regression via `/verify-evolve`.

## Open questions

- Should `ReflexionEntry` reuse `maistro.memory`'s existing `EpisodicRecord`
  schema or define its own type in `maistro_evolve.types`? Reusing avoids a new
  schema but couples evolve's test suite to maistro-core's type definitions.
  Defaulting to a thin adapter (evolve defines `ReflexionEntry`, `EpisodicRecord`
  is an implementation detail behind the store interface).
- Should child genomes inherit the parent's episodic history (copy on spawn), or
  start with an empty store and only inherit through memory scope? Starting empty
  but with access to the parent's store via scope lookup is the simpler path and
  matches how `maistro.memory` already handles agent-scope inheritance.

## References

- Shinn et al., "Reflexion: Language Agents with Verbal Reinforcement Learning"
  (2023) — verbal episodic memory as a complement to weight/prompt updates;
  key insight that reflection can take effect without re-evaluation.
- maistro-engine#SPEC-207 — reflective prompt evolution; defines
  `reflect_on_genome()`, `ReflectionOutcome`, and the failure-trace contract
  this spec extends.
- maistro-engine#ADR-057 — memory exposure mode; the episodic store access
  pattern this spec follows.
- maistro-engine#SPEC-062926-8ec5 — edit budget and margin floor; the write path
  is explicitly outside the edit-budget scope (episodic writes don't touch the
  system prompt).
- Implementation surfaces: `packages/maistro-evolve/src/maistro_evolve/reflect.py`,
  `harness.py` (`EvalHarness`), `cycle.py`, `types.py` (`EvolutionConfig`);
  reads from `maistro.memory` episodic API.
