---
id: SPEC-282
title: "Self-generated curriculum with independent validity gates"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-10-01
substrate:
  - maistro-engine#SPEC-202
related: []
implements:
  - maistro-engine#ADR-088
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-evolve/tests/test_curriculum.py
  - packages/maistro-evolve/tests/test_fitness.py
  - packages/maistro-evolve/tests/test_harness.py
ac-modules:
  AC-1: maistro_evolve.curriculum
  AC-2: maistro_evolve.curriculum
  AC-3: maistro_evolve.curriculum
  AC-4: maistro_evolve.curriculum
  AC-5: maistro_evolve.curriculum
  AC-6: maistro_evolve.curriculum
  AC-7: maistro_evolve.fitness
  AC-8: maistro_evolve.harness
layer: Evolve
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-10-01
---

# SPEC-282: Self-generated curriculum with independent validity gates

Implements the M4-D intent (#24, initiative #450): proposer/solver-style
generated challenges are allowed only behind protected solvability/validity
checks, and the resulting practice signal never replaces external evaluation.

## Design

`maistro_evolve.curriculum` owns the whole gate set; a proposer only ever
produces a `ChallengeDraft` (statement, acceptance description, a mechanical
`verify` callable, optional reference solution). The gates are host-owned
functions — nothing in the draft can mark itself admitted, and no single gate
can admit on its own:

| Gate | Kills a challenge that is... |
|------|------------------------------|
| `well_formed` | empty, undescribed, or carries no callable verifier |
| `reference_solves` | unsatisfiable — its own reference solution fails its own verifier |
| `solver_solves` | unsolvable in practice — an independent solver (a separate seam from the proposer) cannot solve it |
| `baseline_fails` | vacuous — a trivial baseline answer passes the verifier |

Fail closed throughout: a gate with a missing input (no solver seam, no
baseline answer, no reference solution) or one whose probe raises is recorded
as *not executed and not passed*. Admission requires every gate executed **and**
passed. "Checked and failed" and "could not be checked" stay different facts
in the decision's per-gate outcomes; both are refusals.

Every admitted item carries the pinned `CURRICULUM_PROVENANCE`
(`"self-generated"`); constructing an item under any other label raises.

Never replaces external evaluation: curriculum practice scores live under the
reserved `self_generated/` benchmark namespace (`RESERVED_BENCHMARK_PREFIX`).
`fitness` refuses those keys at the hard gate and excludes them from the
weighted eval score (including the renormalisation denominator), and
`EvalHarness.register_benchmark` refuses the namespace outright — so a genome
must still earn fitness on external benchmarks, and a genome scored *only* on
its own challenges cannot breed.

This is the same posture as the quarantine gate's "#347 fails closed" rule and
SPEC-202's honesty rules: a signal that cannot be verified is not a low score,
it is no score — and a practice score is never quietly promoted into evidence.

## Acceptance criteria

- [ ] **AC-1** Admission is all-gates-passed and fail closed: a draft
  satisfying every gate is admitted; a missing solver, baseline answer, or
  reference solution is a recorded refusal (gate `executed=False`,
  `passed=False`); a decision with empty or partial gate outcomes never
  admits.
- [ ] **AC-2** The reference-solvability gate refuses a draft whose reference
  solution does not satisfy its own verifier.
- [ ] **AC-3** The independent-solver gate requires an answer from the
  separate solver seam that the verifier accepts; a wrong answer blocks
  admission; sync and async solver callables are both supported.
- [ ] **AC-4** The baseline-discrimination gate refuses a draft whose verifier
  passes a trivial baseline answer (vacuous verifier), while the other gates
  affirm — the discrimination gate alone rejects.
- [ ] **AC-5** Crash containment: an exception in the solver seam, the
  verifier, or the proposer never admits anything and never aborts a batch —
  the refusal (or skipped round, for the proposer) is recorded with the
  reason; malformed drafts (empty statement/acceptance, non-callable
  verifier) and non-`str` solver answers are refusals; `generate_curriculum`
  without a proposer raises rather than fabricating one.
- [ ] **AC-6** Provenance is pinned: admitted items always report
  `CURRICULUM_PROVENANCE`; constructing a `CurriculumItem` under another
  provenance label raises; `Curriculum.submit` admits only through the gate
  set and refuses non-draft values.
- [ ] **AC-7** Fitness refuses the reserved namespace: `self_generated/…`
  keys fail the hard gate (named in the failures) even alongside passing
  external evidence, are excluded from the weighted eval score and its
  renormalisation, and a genome scored only on curriculum items fails the
  gate ("no external benchmarks evaluated") with total fitness 0.
- [ ] **AC-8** `EvalHarness.register_benchmark` refuses any name under the
  reserved namespace, on either fidelity tier, registering nothing.

## Reconciliation notes

- ADR-088 (maistro-evolve is experimental, API not locked) governs: this spec
  adds a package-internal module plus two narrow guards (fitness namespace
  refusal, harness namespace refusal); it introduces no second scheduler,
  evaluator authority, or promotion authority — the canonical
  `Goal -> Graph -> Run -> NodeRun -> Attempt` spine is untouched, and
  curriculum practice never writes into `genome.eval_scores` through any
  shipped path.
- SPEC-202's fidelity tiers are unchanged: the reserved namespace is not a
  third fidelity tier and never reaches an `EvalResult`; practice signal stays
  inside `curriculum.Curriculum`.
