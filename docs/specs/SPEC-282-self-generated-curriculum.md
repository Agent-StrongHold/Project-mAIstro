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
  - packages/maistro-evolve/tests/test_lane_comparison.py
ac-modules:
  AC-1: maistro_evolve.curriculum
  AC-2: maistro_evolve.curriculum
  AC-3: maistro_evolve.curriculum
  AC-4: maistro_evolve.curriculum
  AC-5: maistro_evolve.curriculum
  AC-6: maistro_evolve.curriculum
  AC-7: maistro_evolve.fitness
  AC-8: maistro_evolve.harness
  AC-9: maistro_evolve.curriculum
  AC-10: maistro_evolve.lane_comparison
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

Explicitly **unverified by design**: a draft whose *statement leaks the
answer* is not rejected by any gate. Leakage detection is a difficulty-
calibration concern, not a solvability/validity one — a leaking challenge is
trivially solvable, so every gate affirms and it admits. This boundary is
pinned by test (`test_answer_leaking_draft_admits_and_is_recorded`): the gate
set must never be described as catching answer leakage, and any future
leakage check would be a new gate (new validator version), not a silent
extension of an existing one.

Fail closed throughout: a gate with a missing input (no solver seam, no
baseline answer, no reference solution) or one whose probe raises is recorded
as *not executed and not passed*. Admission requires every gate executed **and**
passed. "Checked and failed" and "could not be checked" stay different facts
in the decision's per-gate outcomes; both are refusals.

Every admitted item carries the pinned `CURRICULUM_PROVENANCE`
(`"self-generated"`); constructing an item under any other label raises.

Retention: an accepted challenge *keeps* its provenance as data. A
`CurriculumItem` is constructed only from the admitting `AdmissionDecision`
for exactly its own draft — rejected or unchecked drafts mint no item even
through the direct constructor — and retains the generator contract version
(`CURRICULUM_GENERATOR_VERSION`, or the host's own version passed at submit),
the validator version (`CURRICULUM_VALIDATOR_VERSION`, derived from the exact
gate set so a changed gate set is a new validator version), the exact content
identity (`content_digest`: a sha256 over the statement, acceptance, reference
solution, proposer, and the checker's identity), the per-gate validation
evidence verbatim, and any canonical `Goal -> Graph -> Run -> NodeRun ->
Attempt` references supplied by the host that executed the gates or practice
attempts under a canonical run (`run_refs`; empty records the fact that
validation ran in-process, outside the graph runtime — the shipped default).
`CurriculumItem.provenance_record()` exposes the whole set as JSON-safe
primitives.

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

## Measured lane comparison (recorded artifact)

The M4-D exit evidence requires measuring the bounded curriculum-enabled lane
against the same external evaluation without generated curriculum —
capability, cost and failures, *including no improvement*.
`maistro_evolve.lane_comparison.compare_lanes` is that measurement: both lanes
score identical external evidence under the population-owned objective, and
the curriculum lane additionally spends a bounded generation budget
(`LaneBudget`) behind the protected gates. The curriculum lane never writes a
score into `genome.eval_scores`, so any external capability delta is measured,
not assumed away.

Reference scenario (deterministic, pinned by
`test_lane_comparison.py::test_measured_numbers_match_the_recorded_artifact`):
5 generation rounds — one well-formed challenge admitted; one refused per gate
(unsatisfiable reference, independent solver fails, vacuous verifier); one
proposer crash. External evidence: `proxy_ifeval: 0.9`, single-genome
population, default objective. Reproduce with:

```
PYTHONPATH=packages/maistro-core/src:packages/maistro-evolve/tests:packages/maistro-evolve/src \
  uv run python -c "import asyncio; from test_lane_comparison import _genome, _measure; \
  print(asyncio.run(_measure(_genome({'proxy_ifeval': 0.9}))).summary)"
```

Measured result (capability, cost, failures):

```
lane comparison over identical external evidence (generation budget: 5 rounds)
  external-only      : capability=0.900000 fitness_total=58.500000 gate_passed=True
  curriculum-enabled : capability=0.900000 fitness_total=58.500000 gate_passed=True
  capability_delta   : +0.000000 (no improvement) — external evaluation remains the promotion gate
  admission_yield    : 0.200 of the generation budget admitted by the protected gates (well_formed+reference_solves+solver_solves+baseline_fails)
  cost_probes:
    external_evaluations: external_only=1 curriculum_enabled=1
    gate_probes: external_only=0 curriculum_enabled=16
    generator_proposals: external_only=0 curriculum_enabled=5
    solver_attempts: external_only=0 curriculum_enabled=4
  curriculum-lane failures:
    proposer_errors: 1
    refused_by/baseline_fails: 1
    refused_by/reference_solves: 1
    refused_by/solver_solves: 1
  accepted challenges retained: 1 (each with generator/validator version, content identity, validation evidence and run references)
```

Read honestly: the generated-curriculum lane produced **no improvement** in
external capability (delta exactly 0.0 — the practice signal never reaches
evaluation evidence, and this run measured that), at a bounded, fully counted
cost (5 proposer probes, 4 solver probes, 16 executed gate probes), with 3 of
4 gate-checked drafts refused and 1 proposer failure recorded. External
held-out evaluation remains the sole promotion gate; reusable changes still
promote through the #21/#116 candidate/evaluation/promotion contract.

## Acceptance criteria

- [ ] **AC-1** Admission is all-gates-passed and fail closed: a draft
  satisfying every gate is admitted; a missing solver, baseline answer, or
  reference solution is a recorded refusal (gate `executed=False`,
  `passed=False`); a decision with empty or partial gate outcomes never
  admits. An answer-leaking draft (statement contains the answer) is
  **explicitly unverified**: it admits, because the gates check
  solvability/validity, not difficulty — recorded here and pinned by test
  rather than claimed as a rejection.
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
- [ ] **AC-9** Retention: an admitted item retains the generator contract
  version (module default or the host's submit-time override, which must be a
  non-empty string), the validator version derived from the exact gate set,
  its exact content identity (`content_digest`), its admitting
  `AdmissionDecision` with all four per-gate outcomes, and any host-supplied
  canonical run references verbatim. Items cannot be constructed from a
  non-admitted decision, from another draft's decision, or with a content
  hash that does not match the draft; blank/non-string run references are
  refused; `provenance_record()` exposes the whole set as JSON-safe data.
- [ ] **AC-10** The lanes are measured, not assumed: `compare_lanes` scores
  identical external evidence on both lanes and reports the measured external
  capability delta with the verdicts `improvement`/`regression`/`no
  improvement` (an unchanged delta is reported as *no improvement*), bounded
  generation budgets only (`LaneBudget` refuses non-positive rounds), full
  cost counts (generator/solver/gate probes, external evaluations), refusals
  named per gate plus proposer errors, each accepted challenge's provenance
  record, and a rendered `summary` derived from those same numbers. The
  measured reference run is recorded in this spec and pinned by
  `test_measured_numbers_match_the_recorded_artifact`.

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
- Shipped surface: the package root re-exports the lane-comparison API
  (`from maistro_evolve import compare_lanes, LaneBudget, ...`), the same
  public-surface convention `maistro_rsi/__init__.py` uses. This keeps the
  measurement module on a real import path from every `maistro_evolve`
  entry point — the reachability ratchet treats an unwired module as dead —
  without adding a caller, scheduler, or evaluation authority; ADR-088's
  "API not locked" posture still applies.
