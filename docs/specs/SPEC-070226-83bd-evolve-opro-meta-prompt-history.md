---
id: SPEC-070226-83bd
title: "Evolve reflect — OPRO-style meta-prompt history for the reflection loop"
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

# SPEC-070226-83bd: Evolve Reflect — OPRO-Style Meta-Prompt History

## Context

OPRO (Optimization by PROmpting, DeepMind 2023) shows that LLM-based optimizers
perform substantially better when the meta-prompt includes a *history* of
previously tried solutions and their scores, sorted ascending so the model sees
what directions already failed. The optimizer can then extrapolate rather than
re-explore dead ends.

`reflect.py`'s current meta-prompt (`_build_reflection_prompt`) contains only the
current prompt, its baseline score, failure traces, topology summary, benchmark
summary, and a randomized tip. It carries no memory of what challenger prompts
have been tried in prior self-improve cycles, nor their scores. Across generations
the reflective optimizer can re-generate the same direction multiple times, wasting
LLM budget on already-ruled-out edits.

`ReflectionOutcome` is already persisted in
`harness_params["last_optimization"].reflection` (SPEC-207 §6), so the raw
material for a history window is available — it is just not fed back into
subsequent cycles.

## Goals

- Inject a ranked history of recent reflection outcomes (prompt excerpt + score)
  into the meta-prompt so the LLM optimizer can avoid reversions and extrapolate
  beyond what has already been tried.
- Keep the history window bounded so meta-prompt length stays predictable.
- Preserve all existing acceptance, stub-guard, budget, and margin-floor invariants
  unchanged.

## Non-goals

- Storing the full prompt text of every prior challenger (only an excerpt + score
  pair per entry; full text would bloat context).
- Changing the proposal, verify, or acceptance logic in any other way.
- Adding any new persistence store — the history is assembled at call time from
  already-persisted `ReflectionOutcome` records.

## Decision

1. **History assembly.** `reflect_on_genome()` assembles a
   `prompt_history: list[tuple[str, float]]` — (truncated prompt, score) pairs —
   from the genome's `harness_params["last_optimization"].reflection` chain,
   walking back up to `EvolutionConfig.reflect_history_window` entries (new field,
   default 5). Pairs are sorted ascending by score (worst first, best last) so the
   meta-prompt reads as a trajectory toward improvement.

2. **Meta-prompt injection.** `_build_reflection_prompt` gains a
   `prompt_history` parameter. When non-empty, a `## Prior attempts (worst →
   best)` section is appended before the current prompt section, with one line per
   entry: `score=<x>  "<first 120 chars of prompt>"`. When empty (first cycle,
   or genome with no prior reflection), the section is omitted.

3. **No other changes.** Budget enforcement (SPEC-062926-8ec5), margin floor
   (SPEC-062926-8ec5), stub guard, and proposal diversification tips are
   unchanged.

## Acceptance criteria

- When `reflect_history_window > 0` and prior `ReflectionOutcome` records exist,
  the built meta-prompt contains a `## Prior attempts` section with entries sorted
  ascending by score.
- When no prior outcomes exist the section is absent and the prompt is identical
  to the pre-spec baseline.
- The history window is capped at `reflect_history_window` entries regardless of
  how many outcomes are stored.
- All pre-existing `test_reflect.py` tests continue passing unmodified.

## Testing

New unit tests in `packages/maistro-evolve/tests/test_reflect.py`:
`test_history_section_present_when_outcomes_exist`,
`test_history_absent_on_first_cycle`,
`test_history_capped_at_window_size`,
`test_history_sorted_ascending_by_score`. Unseeded-randomness rule applies.

## Open questions

- Should entries include the full challenger prompt (for maximum optimizer
  context) or just an excerpt (for token economy)? Defaulting to excerpt (120
  chars) pending real token-budget data from SPEC-202 real-fidelity runs.
- Should the history include *all* prior attempts across all benchmarks or only
  attempts on the same benchmark as the current cycle? Defaulting to same-
  benchmark for signal coherence.

## References

- Yang et al., "Large Language Models as Optimizers" (OPRO, DeepMind 2023) —
  meta-prompt history as the key driver of LLM optimizer quality.
- maistro-engine#SPEC-207 — reflective prompt evolution; defines
  `ReflectionOutcome`, `_build_reflection_prompt`, and the persistence contract
  this spec extends.
- maistro-engine#SPEC-062926-8ec5 — edit budget and margin floor; acceptance
  invariants this spec inherits unchanged.
- Implementation surfaces: `packages/maistro-evolve/src/maistro_evolve/reflect.py`,
  `types.py` (`EvolutionConfig`).
