---
id: SPEC-207
title: "Evolve reflective prompt evolution — GEPA/MIPROv2-style propose-then-verify self-improve"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-06-10
substrate:
  - maistro-engine#ADR-088
  - maistro-engine#SPEC-202
implements: []
related:
  - maistro-engine#ADR-070
  - maistro-engine#ADR-007
  - maistro-engine#SPEC-184
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-evolve/tests/test_reflect.py
  - packages/maistro-evolve/tests/test_cycle.py
layer: Evolve
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-207: Evolve Reflective Prompt Evolution

## Context

`maistro-evolve`'s self-improve step (`EvolutionCycle._self_improve_top`) was a
one-shot LLM rewrite: a meta-prompt containing only a scalar benchmark score
asked for "an improved system prompt", and the result **overwrote the top
genome's prompt in place without re-evaluation**. One bad rewrite silently
degraded the champion. `extract_signal()`'s weakest-node heuristic was stubbed
(it effectively always read the queen's ifeval score), and benchmark runners
discarded all per-sample information, so the optimizer had no failure feedback
to reflect on.

The prompt-optimization literature (GEPA — reflective prompt evolution;
MIPROv2 — grounded instruction proposal, as packaged by DSPy) solves exactly
this. We adopt their conceptual ideas natively rather than adding a DSPy
dependency, because most of what evolve optimizes (DAG topology, model
selection, multi-objective cost/latency fitness, Elo tournaments) is outside
DSPy's programming model, and `PipelineGenome` is our representation.

## Goals

- Prompt self-improvement is **propose-then-verify**: no candidate prompt
  enters the population without re-scoring above the baseline on the benchmark
  it targets.
- Reflection consumes **execution feedback** (per-sample failure traces), not
  just a scalar score (GEPA).
- Proposals are **grounded** in a topology summary and a benchmark summary,
  and **diversified** via randomized proposal tips (MIPROv2).
- The champion is never mutated in place; accepted candidates join the pool as
  **child genomes** with lineage, and tournaments/culling decide their fate.
- Signal honesty per maistro-engine#SPEC-202: never verify candidates against
  stub (random) scores.

## Non-goals

- Adopting DSPy (or any optimizer framework) as a dependency.
- LLM-driven topology mutation (the existing `optimize_topology()` suggestion
  metadata is unchanged; structural search remains the GA's job).
- Real-fidelity benchmark adapters — that is maistro-engine#SPEC-202's scope.
  This loop inherits whatever fidelity the harness provides.
- Few-shot demo bootstrapping (MIPROv2 stage 1) — future work once per-example
  metrics are exposed by more benchmarks.

## Decision

New module `maistro_evolve.reflect`, wired into `EvolutionCycle._self_improve_top`:

1. **Signal.** Pick the weakest benchmark among `genome.eval_scores`
   restricted to `EvolutionConfig.target_benchmarks`. Target node = entry
   node, because benchmarks execute the entry node's prompt
   (`benchmarks.prompt_builder.build_system_prompt`). `extract_signal()` is
   fixed accordingly.
2. **Fresh rollout.** Re-run the weakest benchmark once via the existing
   `EvalHarness` to obtain the baseline score and per-sample failure traces.
   `benchmarks/ifeval.py` now records up to 5 entries
   (`instruction`, `failed_rules`, `response_excerpt`, `score`) in
   `EvalResult.metadata["failures"]`; other benchmarks may adopt the same
   metadata contract incrementally, and reflection degrades gracefully to
   score-only feedback where traces are absent.
3. **Stub guard.** If the baseline result carries `metadata.stub=True`, return
   `reason="stub_signal"` immediately — no LLM proposals are spent.
4. **Propose.** Build K (= `EvolutionConfig.self_improve_candidates`,
   default 2) meta-prompts containing: topology summary, benchmark summary,
   baseline score, failure feedback, current prompt, and one randomized tip
   from `PROPOSAL_TIPS`. Each LLM response is one candidate prompt
   (deduplicated, empty/unchanged responses dropped).
5. **Verify.** For each candidate, spawn a challenger via
   `spawn_challenger()` — a deep copy with new id, `parent_a_id` set to the
   parent, `generation+1`, cleared scores, and
   `harness_params.origin="reflective_improve"` — and evaluate it on the same
   benchmark.
6. **Accept.** The best challenger joins the population only if its score
   exceeds `baseline + EvolutionConfig.self_improve_accept_margin`
   (default 0.0). The parent genome is never modified; the full
   `ReflectionOutcome` (minus the challenger object) is recorded in
   `harness_params["last_optimization"].reflection`.

The superseded one-shot `optimizer.optimize_prompt()` is removed
(maistro-engine#ADR-088: evolve is experimental, no stability contract; no
external consumers existed).

Promotion of winners out of the population remains governed by the repertoire
flow (maistro-engine#ADR-070) and canary promotion (maistro-engine#ADR-007);
this spec only changes how candidates are generated and admitted *into* the
population.

## Acceptance criteria

- A candidate that re-scores above the baseline on the weakest benchmark is
  accepted and enters the population as a child genome (`parent_a_id` =
  parent id, `origin="reflective_improve"`); the parent's prompt is unchanged.
  (`test_reflect.py::TestReflectiveImprove::test_accepts_verified_better_candidate`,
  `TestCycleIntegration::test_self_improve_adds_challenger_child`)
- A candidate that does not beat the baseline (plus margin) is rejected; no
  genome is added or modified.
  (`test_reflect.py::test_rejects_candidate_that_does_not_beat_baseline`)
- A stub-scored baseline aborts reflection with `reason="stub_signal"` and
  zero proposal LLM calls.
  (`test_reflect.py::test_stub_signal_never_accepted`)
- The reflection meta-prompt contains the current prompt, topology summary,
  benchmark summary, failure feedback, and the proposal tip.
  (`test_reflect.py::TestReflectHelpers::test_build_reflection_prompt_grounding`)
- ifeval populates `metadata["failures"]` (capped at 5) when an LLM is
  attached and produces imperfect responses; never in heuristic (no-LLM) mode.
  (`test_reflect.py::TestIfevalFailureTraces`)
- With `llm_call=None` or no eval scores, the self-improve step is a no-op
  (pre-existing behavior, preserved).
  (`test_reflect.py::test_no_llm_or_no_scores_returns_none`,
  `test_cycle.py::test_cycle_with_self_improve`)

## Testing

Unit + integration in `packages/maistro-evolve/tests/test_reflect.py`
(12 tests) using a benchmark runner keyed on prompt content and fake LLM
callables; full-suite regression in `packages/maistro-evolve/tests/`
(95 tests). Not part of root pytest testpaths — run via the `/verify-evolve`
skill. Unseeded randomness rule applies: tests assert invariants, not exact
offspring.

## Open questions

- Should acceptance also require no regression on a second benchmark
  (cheap Pareto check), at the cost of one more eval per candidate?
- Which benchmarks adopt the `metadata["failures"]` contract next (bfcl is the
  natural second — per-sample tool-call mismatches are easily describable)?
- Once SPEC-202's real adapters land, should `self_improve_accept_margin`
  default above 0 to absorb benchmark variance?

## References

- GEPA: Agrawal et al., "GEPA: Reflective Prompt Evolution Can Outperform
  Reinforcement Learning" (2025) — reflective mutation over execution traces,
  propose-then-verify admission.
- MIPROv2: Opsahl-Ong et al., "Optimizing Instructions and Demonstrations for
  Multi-Stage Language Model Programs" (2024) — grounded proposal, tips,
  minibatch candidate evaluation.
- `docs/adr/ADR-088-maistro-evolve-experimental.md` — evolve stability posture.
- `docs/specs/SPEC-202-evolve-fitness-fidelity.md` — signal fidelity tiers the
  stub guard enforces.
- Implementation: `packages/maistro-evolve/src/maistro_evolve/reflect.py`,
  `cycle.py`, `optimizer.py`, `benchmarks/ifeval.py` (PR #143).
