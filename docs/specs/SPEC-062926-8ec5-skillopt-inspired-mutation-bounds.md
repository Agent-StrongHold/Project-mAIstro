---
id: SPEC-062926-8ec5
title: "Evolve mutation bounds — SkillOpt-inspired edit budget and strict validation gate"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-06-29
substrate:
  - maistro-engine#ADR-088
  - maistro-engine#SPEC-207
implements: []
related:
  - maistro-engine#SPEC-202
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

# SPEC-062926-8ec5: Evolve Mutation Bounds — SkillOpt-Inspired Edit Budget and Strict Validation Gate

## Context

A changelog/architecture review of Microsoft's SkillOpt (a text-space optimizer
that refines a single `SKILL.md` document against a frozen target agent via a
rollout → reflect → edit → gate → update loop) found that `maistro-evolve`
already has a structurally similar mechanism — `reflect.py`'s propose-then-verify
self-improve step (maistro-engine#SPEC-207) — but two disciplines SkillOpt
enforces on every accepted edit are missing from evolve's prompt-mutation paths:

1. **An edit budget.** SkillOpt bounds each accepted change with a "textual
   learning rate" so one update cannot overwrite rules that already work.
   `mutate.py`'s blind operator, `mutate_prompt()`, has no equivalent: it
   appends random variation strings or excises random sentences from
   `system_prompt` with no cap on how much of the prompt can change in a
   single call. Across generations this can silently rewrite the bulk of a
   working prompt; the existing diversity-injection mechanism (`diversity.py`)
   masks population collapse but does not prevent any single prompt from
   drifting unboundedly.
2. **A strict-improvement gate.** SkillOpt accepts an edit only if it
   *strictly* improves the held-out validation score. `reflect.py`'s
   acceptance check (`SPEC-207`) requires `score > baseline +
   self_improve_accept_margin`, with `self_improve_accept_margin` defaulting
   to `0.0`. That default is mathematically already strict (`>`, not `>=`),
   but the margin is configurable down to a value that would admit a tie or a
   noise-level "improvement" — there is no floor preventing a future config
   change (or benchmark-variance tuning, flagged as an open question in
   SPEC-207) from weakening admission below strict-improvement.

This spec hardens the existing prompt-mutation paths to match SkillOpt's two
disciplines. It does not change topology mutation, crossover, the Elo
tournament, or the fail-closed promotion gate — none of which have an
analogue in SkillOpt and none of which this review found wanting.

## Goals

- Cap the magnitude of any single accepted prompt mutation — blind
  (`mutate_prompt()`) or reflective (`reflect.py`'s challenger prompts) — via
  an explicit, configurable edit budget.
- Make the strict-improvement requirement for reflective acceptance a floor
  that cannot be configured away to a tie-admitting value.
- Preserve every existing safety invariant unchanged: fail-closed promotion
  gate, lineage preservation, no in-place champion mutation, unseeded
  randomness as an explicit non-determinism allowance.

## Non-goals

- Adopting SkillOpt or any external optimizer dependency.
- A standalone single-skill (`SKILL.md`) refinement loop for
  `maistro.skills`/Forge analogous to SkillOpt itself. That is a materially
  larger feature (new module, new Ability-layer ↔ Evolve-layer interaction,
  its own frozen-target/optimizer-model split) and belongs in a separate spec
  if pursued — see Open questions.
- Changes to `mutate_topology()`, `crossover()`, tournament selection, or the
  `PopulationStore.promote()` approval gate.

## Decision

1. **`EvolutionConfig.prompt_edit_budget`** (new field, default chosen to
   match `mutate_prompt()`'s current typical change size so this is a
   tightening, not a behavior change at default settings): a fraction-of-
   prompt-length (or absolute sentence/token-delta) ceiling. `mutate_prompt()`
   enforces it by capping how many sentences may be appended/excised per call;
   any proposed change exceeding the budget is truncated to the largest
   in-budget subset rather than rejected outright (mutation must still
   produce a valid, non-empty prompt).
2. **`reflect.py` challenger prompts** are subject to the same
   `prompt_edit_budget` relative to the parent prompt, measured before
   spawning the challenger for evaluation — a proposal that exceeds budget is
   not spent on an eval call (avoids wasting LLM/benchmark budget on a
   guaranteed-out-of-policy candidate).
3. **`EvolutionConfig.self_improve_accept_margin`** gains a documented,
   enforced floor: the field's validator rejects values `< self_improve_min_margin`
   (new constant, small positive epsilon), so the strict-improvement gate
   cannot be configured down to tie-admission. The existing default of `0.0`
   is raised to match the floor.
4. No changes to `mutate_topology()`, `mutate_node()`, `mutate_eval_weights()`,
   `crossover()`, tournament math, diversity injection, or promotion gating.

## Acceptance criteria

- `mutate_prompt()` never changes more than `prompt_edit_budget` of a prompt
  in one call, for both the append and excise paths (tested).
- A reflective challenger whose proposed prompt exceeds `prompt_edit_budget`
  relative to its parent is dropped before evaluation, with zero eval/LLM
  calls spent on it (tested).
- Constructing `EvolutionConfig` with `self_improve_accept_margin` below the
  floor raises a validation error; the default config satisfies the floor
  (tested).
- All pre-existing `test_mutate.py`, `test_reflect.py`, `test_cycle.py`, and
  `test_rsi_safety.py` tests continue passing unmodified.

## Testing

New/extended unit tests in `packages/maistro-evolve/tests/test_mutate.py`
(edit-budget enforcement on both mutation directions) and
`packages/maistro-evolve/tests/test_reflect.py` (budget-exceeding challenger
rejection; margin-floor validation). Full-suite regression via the
`/verify-evolve` skill. Unseeded-randomness rule applies: tests assert
budget invariants, not exact mutated text.

## Open questions

- Should `prompt_edit_budget` itself be allowed to vary per-genome (subject to
  meta-mutation) or stay a single global `EvolutionConfig` value? Defaulting
  to global for this spec; per-genome budgets would need their own fitness
  justification.
- Is there appetite for the larger follow-on this review surfaced — a
  SkillOpt-style standalone optimizer for `maistro.skills` Forge skills
  (frozen target agent, separate optimizer model, single-artifact
  `best_skill.md`-equivalent output)? Deliberately out of scope here; would
  warrant its own spec under a layer interaction between `Evolve` and
  `Ability`.
- Does raising the `self_improve_accept_margin` floor above `0.0` risk
  rejecting genuinely-better candidates under benchmark variance, the same
  concern SPEC-207 flagged for the opposite direction? Proposing a small
  epsilon (not yet numerically pinned) rather than zero specifically to leave
  room for that resolution once SPEC-202's real-fidelity adapters land.

## References

- Microsoft SkillOpt — `github.com/microsoft/SkillOpt`: text-space skill
  optimizer (rollout → reflect → edit → gate → update; "textual learning
  rate" edit budget; strict held-out-validation gate; single frozen-target
  artifact, separate optimizer model).
- maistro-engine#SPEC-207 — Evolve reflective prompt evolution (the
  propose-then-verify loop this spec hardens).
- maistro-engine#SPEC-202 — Evolve fitness fidelity (the signal-honesty
  context the margin-floor open question depends on).
- maistro-engine#ADR-088 — maistro-evolve experimental posture (no stability
  contract; basis for editing `reflect.py`/`mutate.py` behavior directly
  rather than through a deprecation cycle).
- Implementation surfaces: `packages/maistro-evolve/src/maistro_evolve/mutate.py`,
  `reflect.py`, `types.py` (`EvolutionConfig`).
